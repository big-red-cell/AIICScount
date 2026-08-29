import importlib.util
import json
import sys
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

MODULE_PATH = ROOT_DIR / "check.py"
MODULE_SPEC = importlib.util.spec_from_file_location("compete_attack_check", MODULE_PATH)
assert MODULE_SPEC is not None
assert MODULE_SPEC.loader is not None
check_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(check_module)
if previous_openai_client is None:
    sys.modules.pop("openai_responses_client", None)
else:
    sys.modules["openai_responses_client"] = previous_openai_client

from template import CONTENT_PLACEHOLDER, render_template


def test_render_template_replaces_placeholder_with_json_escaped_content():
    content = 'Line 1\nHe said "hello".'

    rendered = render_template(content)

    assert CONTENT_PLACEHOLDER not in rendered
    assert 'Line 1\\nHe said \\"hello\\".' in rendered


def test_check_passes_rendered_prompt_to_generate_response_text(monkeypatch):
    captured_kwargs = {}
    content = 'Body\nwith "quotes"'

    def fake_generate_response_text(**kwargs):
        captured_kwargs.update(kwargs)
        return "ok"

    monkeypatch.setattr(check_module, "generate_response_text", fake_generate_response_text)

    assert check_module.check(content, model="check-model") == "ok"
    assert captured_kwargs == {
        "userprompt": render_template(content),
        "stream": True,
        "model": "check-model",
    }


def test_run_checks_only_reruns_failed_or_missing_items(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (output_dir / "letters.json").write_text(
        json.dumps(
            {
                "1": "letter-1",
                "2": "letter-2",
                "3": "letter-3",
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "replay.json").write_text(
        json.dumps(
            {
                "1": "existing-success",
                "2": "stale-error-replay",
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "replay.status.json").write_text(
        json.dumps(
            {
                "2": {
                    "status": "error",
                    "stage": "check_request",
                    "error": "Request failed: timeout",
                }
            }
        ),
        encoding="utf-8",
    )

    processed_letters = []

    monkeypatch.setattr(check_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(check_module, "LETTERS_PATH", output_dir / "letters.json")
    monkeypatch.setattr(check_module, "REPLAY_PATH", output_dir / "replay.json")
    monkeypatch.setattr(check_module, "REPLAY_STATUS_PATH", output_dir / "replay.status.json")

    def fake_check(letter, **kwargs):
        processed_letters.append(letter)
        assert kwargs["model"] == "check-model"
        if letter == "letter-2":
            raise check_module.BatchItemError("check_request", "Request failed: retry me")
        return f"ok:{letter}"

    monkeypatch.setattr(check_module, "check", fake_check)

    check_module.run_checks([1, 2, 3], model="check-model")

    assert processed_letters == ["letter-2", "letter-3"]
    assert json.loads((output_dir / "replay.json").read_text(encoding="utf-8")) == {
        "1": "existing-success",
        "3": "ok:letter-3",
    }
    assert json.loads((output_dir / "replay.status.json").read_text(encoding="utf-8")) == {
        "1": {"status": "success"},
        "2": {
            "status": "error",
            "stage": "check_request",
            "error": "Request failed: retry me",
        },
        "3": {"status": "success"},
    }


def test_run_checks_prints_progress_before_request(monkeypatch, tmp_path, capsys):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (output_dir / "letters.json").write_text(json.dumps({"1": "letter-1"}), encoding="utf-8")

    monkeypatch.setattr(check_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(check_module, "LETTERS_PATH", output_dir / "letters.json")
    monkeypatch.setattr(check_module, "REPLAY_PATH", output_dir / "replay.json")
    monkeypatch.setattr(check_module, "REPLAY_STATUS_PATH", output_dir / "replay.status.json")

    def fake_check(letter, **kwargs):
        assert letter == "letter-1"
        assert kwargs["model"] == "check-model"
        return "ok"

    monkeypatch.setattr(check_module, "check", fake_check)

    check_module.run_checks([1], model="check-model")

    output = capsys.readouterr().out
    assert "Running check stage with model check-model: 1 pending replay(s)." in output
    assert "[1/1] Checking replay 1..." in output
    assert "Check stage complete: 1 succeeded, 0 failed, 1 attempted." in output
