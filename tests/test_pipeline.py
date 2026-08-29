import importlib.util
import json
from pathlib import Path
import sys
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "pipeline.py"
SPEC = importlib.util.spec_from_file_location("three_stage_pipeline", MODULE_PATH)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = pipeline
SPEC.loader.exec_module(pipeline)


def test_stage_source_files_skips_archive_and_example_dirs(tmp_path):
    source = tmp_path / "source"
    (source / "archive" / "look2").mkdir(parents=True)
    (source / "example_inputs").mkdir()
    (source / "keep").mkdir()
    (source / "archive" / "look2" / "old.txt").write_text("old", encoding="utf-8")
    (source / "example_inputs" / "nested_example.txt").write_text("example", encoding="utf-8")
    (source / "keep" / "325707095.txt").write_text("live", encoding="utf-8")

    staged = pipeline.stage_source_files(source, tmp_path / "staged")

    assert len(staged) == 1
    assert staged[0].read_text(encoding="utf-8") == "live"


def test_stage_source_files_is_recursive_and_collision_safe(tmp_path):
    source = tmp_path / "source"
    (source / "one").mkdir(parents=True)
    (source / "two").mkdir()
    (source / "one" / "same.txt").write_text("one", encoding="utf-8")
    (source / "two" / "same.txt").write_text("two", encoding="utf-8")

    staged = pipeline.stage_source_files(source, tmp_path / "staged")

    assert len(staged) == 2
    assert len({item.name for item in staged}) == 2
    assert {item.read_text(encoding="utf-8") for item in staged} == {"one", "two"}


def test_phase2_paths_keep_only_reproduce_as_public_output():
    paths = pipeline.paths_for_family("chrome")

    assert paths.reproduce == ROOT / "results" / "chrome_issue" / "phase2" / "reproduce"
    assert paths.tmp == ROOT / "results" / "chrome_issue" / "phase2" / "tmp"


def test_phase1_consistency_rejects_missing_prerequisite(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "123.txt").write_text("issue", encoding="utf-8")
    paths = pipeline.Paths(
        source=tmp_path / "source", stage3=selected,
        stage1=tmp_path / "stage1", stage2=tmp_path / "stage2",
    )
    paths.stage1.mkdir(); paths.stage2.mkdir()
    (paths.stage1 / "123.txt").write_text("ok", encoding="utf-8")
    with pytest.raises(RuntimeError, match="inconsistent"):
        pipeline._validate_phase1_consistency(paths)


def test_prepare_reproduction_creates_openclaw_manifest(tmp_path):
    selected = tmp_path / "stage3"
    selected.mkdir()
    (selected / "123.txt").write_text("issue", encoding="utf-8")
    paths = pipeline.Paths(source=tmp_path / "source", stage3=selected, tmp=tmp_path / "phase2_tmp")

    pipeline.prepare_reproduction(paths)

    manifest = json.loads((paths.tmp / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "pending_openclaw_reproduction"
    assert manifest["issues"][0]["issue_id"] == "123"


def test_reproduction_continues_after_openclaw_failure(tmp_path, monkeypatch):
    selected = tmp_path / "stage3"
    selected.mkdir()
    (selected / "123.txt").write_text("issue", encoding="utf-8")
    (selected / "456.txt").write_text("issue", encoding="utf-8")
    stale = tmp_path / "phase2_tmp" / "reports"
    stale.mkdir(parents=True)
    (stale / "issue_123.md").write_text("**Bucket:** REPRODUCED\n- verify: stale\n", encoding="utf-8")
    paths = pipeline.Paths(
        source=tmp_path / "source",
        stage3=selected,
        reproduce=tmp_path / "reproduce",
        tmp=tmp_path / "phase2_tmp",
    )
    paths.reproduce.mkdir(parents=True)
    (paths.reproduce / "stale.json").write_text("stale", encoding="utf-8")
    (paths.reproduce / "stale-dir").mkdir()
    calls: list[str] = []

    def fake_run(command, **kwargs):
        issue_path = command[command.index("-IssuePath") + 1]
        calls.append(issue_path)
        report = command[command.index("-ReportPath") + 1]
        if issue_path.endswith("123.txt"):
            return 1, "fail"
        Path(report).write_text(
            "# Issue 456\n\n**Bucket:** POTENTIAL\n\n- verify: skipped in this environment\n",
            encoding="utf-8",
        )
        return 0, "ok"

    monkeypatch.setattr(pipeline, "_run_openclaw_command", fake_run)
    monkeypatch.setattr(pipeline, "OPENCLAW_UNIX_RUNNER", Path(__file__))

    pipeline.run_reproduction(paths, timeout=1)

    assert len(calls) == 2
    summary = (paths.tmp / "reports" / "_summary.md").read_text(encoding="utf-8")
    assert "123" in summary
    assert "456" in summary
    assert not (paths.tmp / "reports" / "issue_123.md").exists()
    assert {item.name for item in paths.reproduce.glob("*.txt")} == {"456.txt"}
    assert {item.name for item in paths.reproduce.iterdir()} == {"456.txt"}
    stage3 = json.loads((paths.tmp / "stage3_input.json").read_text(encoding="utf-8"))
    assert stage3["issues"] == [{"issue_id": "456", "bucket": "POTENTIAL", "file": "456.txt"}]


def test_reproduce_report_requires_verify_evidence(tmp_path):
    report = tmp_path / "issue_123.md"
    report.write_text("# Issue 123\n\n**Bucket:** REPRODUCED\n\n- verify: browser title was example\n", encoding="utf-8")

    pipeline._validate_reproduce_report(report)

    report.write_text("# Issue 123\n\n**Bucket:** REPRODUCED\n", encoding="utf-8")
    try:
        pipeline._validate_reproduce_report(report)
    except ValueError as exc:
        assert "verify evidence" in str(exc)
    else:
        raise AssertionError("Expected reproduced reports without evidence to fail")


def test_stage3_input_forwards_reproduce_and_potential(tmp_path, monkeypatch):
    selected = tmp_path / "stage3"
    selected.mkdir()
    (selected / "ok.txt").write_text("reproduced issue", encoding="utf-8")
    (selected / "maybe.txt").write_text("potential issue", encoding="utf-8")
    (selected / "dead.txt").write_text("not reproducible", encoding="utf-8")
    paths = pipeline.Paths(
        source=tmp_path / "source",
        stage3=selected,
        reproduce=tmp_path / "reproduce",
        tmp=tmp_path / "phase2_tmp",
    )

    def fake_run(command, **kwargs):
        issue_path = Path(command[command.index("-IssuePath") + 1])
        report = Path(command[command.index("-ReportPath") + 1])
        reports = {
            "ok.txt": "# Issue\n\n**Bucket:** REPRODUCED\n\n- verify: title matched\n",
            "maybe.txt": "# Issue\n\n**Bucket:** POTENTIAL\n\nMissing Android device.\n",
            "dead.txt": "# Issue\n\n**Bucket:** NOT_REPRODUCIBLE\n\nFixed upstream.\n",
        }
        report.write_text(reports[issue_path.name], encoding="utf-8")
        return 0, "ok"

    monkeypatch.setattr(pipeline, "_run_openclaw_command", fake_run)
    monkeypatch.setattr(pipeline, "OPENCLAW_UNIX_RUNNER", Path(__file__))

    pipeline.run_reproduction(paths, timeout=1)

    assert {item.name for item in paths.reproduce.glob("*.txt")} == {"ok.txt", "maybe.txt"}
    stage3 = json.loads((paths.tmp / "stage3_input.json").read_text(encoding="utf-8"))
    assert [item["bucket"] for item in stage3["issues"]] == ["POTENTIAL", "REPRODUCED"]


def test_attack_defaults_to_reproduce_input():
    assert pipeline.parse_args([]).attack_input == "reproduce"


def test_source_tree_has_no_extra_repo_absolute_paths():
    forbidden = (
        r"C:\Users",
        r"D:\Codes",
        "/Users/",
        "Program Files",
        r"scoop\persist",
    )
    roots = [
        pipeline.WORKSPACE / "src",
        pipeline.WORKSPACE / "README.md",
        pipeline.WORKSPACE / "DEPLOYMENT.md",
        pipeline.WORKSPACE / ".env.example",
    ]
    files: list[Path] = []
    text_suffixes = {".py", ".ps1", ".md", ".toml", ".json", ".txt", ".example"}
    skip_parts = {"__pycache__", ".venv", ".tmp"}
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.lower() in text_suffixes
                and not any(part in skip_parts for part in path.parts)
            )
    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append(f"{path.relative_to(pipeline.WORKSPACE)}: {token}")
    assert hits == []
