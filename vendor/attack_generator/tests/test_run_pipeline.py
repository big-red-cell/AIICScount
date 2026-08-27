import importlib.util
import json
import os
import sys
import threading
import time
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

fake_openai_client = types.ModuleType("openai_responses_client")


class FakeOpenAIResponsesError(Exception):
    pass


def _unexpected_generate_response_text(**kwargs):
    raise AssertionError("Tests should monkeypatch generate_response_text explicitly.")


fake_openai_client.OpenAIResponsesError = FakeOpenAIResponsesError
fake_openai_client.generate_response_text = _unexpected_generate_response_text
previous_openai_client = sys.modules.get("openai_responses_client")
sys.modules["openai_responses_client"] = fake_openai_client

MODULE_PATH = ROOT_DIR / "run_pipeline.py"
MODULE_SPEC = importlib.util.spec_from_file_location("compete_attack_pipeline", MODULE_PATH)
assert MODULE_SPEC is not None
assert MODULE_SPEC.loader is not None
pipeline = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(pipeline)
if previous_openai_client is None:
    sys.modules.pop("openai_responses_client", None)
else:
    sys.modules["openai_responses_client"] = previous_openai_client


def test_discover_model_dirs_only_includes_final_selected(tmp_path):
    (tmp_path / "gpt-4o" / "final_selected").mkdir(parents=True)
    (tmp_path / "gpt-5.4-mini" / "filtered_txt").mkdir(parents=True)
    (tmp_path / "DeepSeek-V3" / "final_selected").mkdir(parents=True)

    assert pipeline.discover_model_dirs(tmp_path) == [
        ("DeepSeek-V3", tmp_path / "DeepSeek-V3" / "final_selected"),
        ("gpt-4o", tmp_path / "gpt-4o" / "final_selected"),
    ]


def test_pipeline_isolates_model_outputs_and_routes_models(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    for model_name in ["gpt-4o", "gpt-5.4-mini"]:
        final_selected = input_dir / model_name / "final_selected"
        final_selected.mkdir(parents=True)
        (final_selected / "444059024.txt").write_text(f"body-{model_name}", encoding="utf-8")

    generate_calls = []
    check_calls = []

    def fake_generate_main(issue_ids, **kwargs):
        generate_calls.append((list(issue_ids), kwargs["model"], kwargs["issues_dir"]))
        kwargs["letters_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["letters_path"].write_text(json.dumps({"444059024": f"letter-{kwargs['model']}"}), encoding="utf-8")
        kwargs["letters_status_path"].write_text(json.dumps({"444059024": {"status": "success"}}), encoding="utf-8")

    def fake_run_checks(issue_ids, **kwargs):
        check_calls.append((list(issue_ids), kwargs["model"], kwargs["letters_path"], kwargs["replay_path"]))
        kwargs["replay_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["replay_path"].write_text(json.dumps({"444059024": "ok"}), encoding="utf-8")

    monkeypatch.setattr(pipeline, "INPUT_DIR", input_dir)
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(pipeline.generate_stage, "main", fake_generate_main)
    monkeypatch.setattr(pipeline.check_stage, "run_checks", fake_run_checks)
    monkeypatch.setattr(pipeline, "resolve_check_model", lambda: "check-model")

    pipeline.run_pipeline(stage="all")

    assert generate_calls == [
        (["444059024"], "gpt-4o", input_dir / "gpt-4o" / "final_selected"),
        (["444059024"], "gpt-5.4-mini", input_dir / "gpt-5.4-mini" / "final_selected"),
    ]
    assert check_calls == [
        (["444059024"], "check-model", output_dir / "gpt-4o" / "letters.json", output_dir / "gpt-4o" / "replay.json"),
        (["444059024"], "check-model", output_dir / "gpt-5.4-mini" / "letters.json", output_dir / "gpt-5.4-mini" / "replay.json"),
    ]


def test_resolve_check_model_prefers_environment_alias(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("CHECK_MODEL=file-check\n", encoding="utf-8")

    monkeypatch.setattr(os, "environ", {"CHECKMODEL": "env-check"})

    assert pipeline.resolve_check_model(env_path) == "env-check"


def test_check_stage_requires_check_model(monkeypatch, tmp_path):
    final_selected = tmp_path / "input" / "gpt-4o" / "final_selected"
    final_selected.mkdir(parents=True)
    (final_selected / "1.txt").write_text("body", encoding="utf-8")

    monkeypatch.setattr(pipeline, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(pipeline, "resolve_check_model", lambda: None)

    try:
        pipeline.run_pipeline(model="gpt-4o", stage="check")
    except pipeline.PipelineConfigError as exc:
        assert "CHECK_MODEL is required" in str(exc)
    else:
        raise AssertionError("Expected PipelineConfigError")


def test_check_stage_requires_generated_letters(monkeypatch, tmp_path):
    final_selected = tmp_path / "input" / "gpt-5.4-mini" / "final_selected"
    final_selected.mkdir(parents=True)
    (final_selected / "1.txt").write_text("body", encoding="utf-8")

    monkeypatch.setattr(pipeline, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(pipeline, "resolve_check_model", lambda: "check-model")

    try:
        pipeline.run_pipeline(model="gpt-5.4-mini", stage="check")
    except pipeline.PipelineConfigError as exc:
        message = str(exc)
        assert "Missing generated letters" in message
        assert "--stage generate" in message
    else:
        raise AssertionError("Expected PipelineConfigError")


def test_workers_process_model_directories_in_parallel(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    for model_name in ["gpt-4o", "gpt-5.4-mini"]:
        final_selected = input_dir / model_name / "final_selected"
        final_selected.mkdir(parents=True)
        (final_selected / "1.txt").write_text("body", encoding="utf-8")

    lock = threading.Lock()
    started: list[str] = []
    release = threading.Event()

    def fake_run_model(model_name, final_selected_dir, **kwargs):
        with lock:
            started.append(model_name)
            if len(started) == 2:
                release.set()
        assert release.wait(timeout=1.0)

    monkeypatch.setattr(pipeline, "INPUT_DIR", input_dir)
    monkeypatch.setattr(pipeline, "run_model", fake_run_model)

    pipeline.run_models(stage="generate", workers=2)

    assert sorted(started) == ["gpt-4o", "gpt-5.4-mini"]


def test_parallel_errors_are_reported_with_model_names(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    for model_name in ["gpt-4o", "gpt-5.4-mini"]:
        final_selected = input_dir / model_name / "final_selected"
        final_selected.mkdir(parents=True)
        (final_selected / "1.txt").write_text("body", encoding="utf-8")

    def fake_run_model(model_name, final_selected_dir, **kwargs):
        if model_name == "gpt-4o":
            raise pipeline.PipelineConfigError("boom")
        time.sleep(0.01)

    monkeypatch.setattr(pipeline, "INPUT_DIR", input_dir)
    monkeypatch.setattr(pipeline, "run_model", fake_run_model)

    try:
        pipeline.run_models(stage="generate", workers=2)
    except pipeline.PipelineConfigError as exc:
        message = str(exc)
        assert "One or more model runs failed" in message
        assert "gpt-4o: boom" in message
    else:
        raise AssertionError("Expected PipelineConfigError")
