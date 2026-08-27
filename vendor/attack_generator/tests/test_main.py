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

MODULE_PATH = ROOT_DIR / "main.py"
MODULE_SPEC = importlib.util.spec_from_file_location("compete_attack_main", MODULE_PATH)
assert MODULE_SPEC is not None
assert MODULE_SPEC.loader is not None
main = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(main)
if previous_openai_client is None:
    sys.modules.pop("openai_responses_client", None)
else:
    sys.modules["openai_responses_client"] = previous_openai_client


def test_step1_reads_issue_from_repo_relative_directory(monkeypatch, tmp_path):
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "123.txt").write_text("issue body", encoding="utf-8")

    monkeypatch.setattr(main, "ISSUES_DIR", issues_dir)
    monkeypatch.setattr(
        main,
        "generate_response_text",
        lambda **kwargs: "<phase1>ignore</phase1><phase2>follow up</phase2>",
    )

    assert main.step1(123, model="gpt-test") == "follow up"


def test_step1_passes_model_from_input_directory(monkeypatch, tmp_path):
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "123.txt").write_text("issue body", encoding="utf-8")
    captured_kwargs = {}

    def fake_generate_response_text(**kwargs):
        captured_kwargs.update(kwargs)
        return "<phase2>follow up</phase2>"

    monkeypatch.setattr(main, "generate_response_text", fake_generate_response_text)

    assert main.step1("123", model="gpt-4o", issues_dir=issues_dir) == "follow up"
    assert captured_kwargs["model"] == "gpt-4o"


def test_step1_parse_error_includes_model_output_preview(monkeypatch, tmp_path):
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "123.txt").write_text("issue body", encoding="utf-8")

    monkeypatch.setattr(main, "generate_response_text", lambda **kwargs: "No. I won't generate this output.")

    try:
        main.step1("123", model="claude-sonnet-4-6", issues_dir=issues_dir)
    except main.BatchItemError as exc:
        assert exc.stage == "step1_parse"
        assert "No phase2 content found" in str(exc)
        assert "No. I won't generate this output." in str(exc)
    else:
        raise AssertionError("Expected BatchItemError")


def test_main_writes_letters_to_repo_relative_output_directory(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"

    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main, "LETTERS_PATH", output_dir / "letters.json")
    monkeypatch.setattr(main, "LETTERS_STATUS_PATH", output_dir / "letters.status.json")
    monkeypatch.setattr(main, "step1", lambda issue_no, **kwargs: f"instructions-{issue_no}")
    monkeypatch.setattr(main, "step2", lambda instructions, **kwargs: instructions.upper())

    main.main([1, 2], model="gpt-test")

    output_path = output_dir / "letters.json"
    status_path = output_dir / "letters.status.json"
    assert output_path.exists()
    assert status_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "1": "INSTRUCTIONS-1",
        "2": "INSTRUCTIONS-2",
    }
    assert json.loads(status_path.read_text(encoding="utf-8")) == {
        "1": {"status": "success"},
        "2": {"status": "success"},
    }


def test_main_only_reruns_failed_or_missing_issues(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (output_dir / "letters.json").write_text(
        json.dumps(
            {
                "1": "existing-success",
                "2": "stale-error-result",
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "letters.status.json").write_text(
        json.dumps(
            {
                "2": {
                    "status": "error",
                    "stage": "step2_request",
                    "error": "Request failed: timeout",
                }
            }
        ),
        encoding="utf-8",
    )

    processed_issues = []

    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main, "LETTERS_PATH", output_dir / "letters.json")
    monkeypatch.setattr(main, "LETTERS_STATUS_PATH", output_dir / "letters.status.json")

    def fake_step1(issue_no):
        processed_issues.append(("step1", issue_no))
        return f"instructions-{issue_no}"

    monkeypatch.setattr(main, "step1", fake_step1)
    monkeypatch.setattr(main, "step2", lambda instructions, **kwargs: instructions.upper())

    def fake_step1_with_kwargs(issue_no, **kwargs):
        return fake_step1(issue_no)

    monkeypatch.setattr(main, "step1", fake_step1_with_kwargs)

    main.main([1, 2, 3], model="gpt-test")

    assert processed_issues == [("step1", 2), ("step1", 3)]
    assert json.loads((output_dir / "letters.json").read_text(encoding="utf-8")) == {
        "1": "existing-success",
        "2": "INSTRUCTIONS-2",
        "3": "INSTRUCTIONS-3",
    }
    assert json.loads((output_dir / "letters.status.json").read_text(encoding="utf-8")) == {
        "1": {"status": "success"},
        "2": {"status": "success"},
        "3": {"status": "success"},
    }


def test_main_marks_errors_and_keeps_them_pending_for_next_run(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"

    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main, "LETTERS_PATH", output_dir / "letters.json")
    monkeypatch.setattr(main, "LETTERS_STATUS_PATH", output_dir / "letters.status.json")

    attempts = {"1": 0}

    def fake_step1(issue_no, **kwargs):
        key = str(issue_no)
        attempts[key] = attempts.get(key, 0) + 1
        if key == "1" and attempts[key] == 1:
            raise main.BatchItemError("step1_request", "Request failed: boom")
        return f"instructions-{issue_no}"

    monkeypatch.setattr(main, "step1", fake_step1)
    monkeypatch.setattr(main, "step2", lambda instructions, **kwargs: instructions.upper())

    main.main([1, 2], model="gpt-test")

    assert json.loads((output_dir / "letters.json").read_text(encoding="utf-8")) == {
        "2": "INSTRUCTIONS-2",
    }
    assert json.loads((output_dir / "letters.status.json").read_text(encoding="utf-8")) == {
        "1": {
            "status": "error",
            "stage": "step1_request",
            "error": "Request failed: boom",
        },
        "2": {"status": "success"},
    }

    main.main([1, 2], model="gpt-test")

    assert attempts["1"] == 2
    assert json.loads((output_dir / "letters.json").read_text(encoding="utf-8")) == {
        "1": "INSTRUCTIONS-1",
        "2": "INSTRUCTIONS-2",
    }
    assert json.loads((output_dir / "letters.status.json").read_text(encoding="utf-8")) == {
        "1": {"status": "success"},
        "2": {"status": "success"},
    }
