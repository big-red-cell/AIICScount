import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "pipeline.py"
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


def test_analyzer_dry_run_calls_senior_stage1_only(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "123.txt").write_text("issue", encoding="utf-8")
    paths = pipeline.Paths(
        source=source,
        staged_raw=tmp_path / "staged_raw",
        final_selected=tmp_path / "final_selected",
        analyzer_artifacts=tmp_path / "analyzer",
    )

    pipeline.run_analyzer(paths, model="test-model", dry_run=True)

    command = json.loads((paths.analyzer_artifacts / "command.json").read_text(encoding="utf-8"))["command"]
    assert command[1] == str(pipeline.SENIOR_STAGE1_ROOT / "process_txt_with_llm.py")
    assert command[command.index("--stage") + 1] == "1"
    assert command[command.index("--final-dir") + 1] == str(paths.final_selected)


def test_prepare_reproduction_creates_openclaw_manifest(tmp_path):
    selected = tmp_path / "final_selected"
    selected.mkdir()
    (selected / "123.txt").write_text("issue", encoding="utf-8")
    paths = pipeline.Paths(source=tmp_path / "source", final_selected=selected, reproduction=tmp_path / "reproduction")

    pipeline.prepare_reproduction(paths, dry_run=True)

    manifest = json.loads((paths.reproduction / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "prepared"
    assert manifest["issues"][0]["issue_id"] == "123"


def test_reproduction_dry_run_prepares_without_openclaw(tmp_path):
    selected = tmp_path / "final_selected"
    selected.mkdir()
    (selected / "123.txt").write_text("issue", encoding="utf-8")
    paths = pipeline.Paths(source=tmp_path / "source", final_selected=selected, reproduction=tmp_path / "reproduction")

    pipeline.run_reproduction(paths, dry_run=True, timeout=1)

    manifest = json.loads((paths.reproduction / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "prepared"


def test_reproduction_continues_after_openclaw_failure(tmp_path, monkeypatch):
    selected = tmp_path / "final_selected"
    selected.mkdir()
    (selected / "123.txt").write_text("issue", encoding="utf-8")
    (selected / "456.txt").write_text("issue", encoding="utf-8")
    stale = tmp_path / "reproduction" / "reports"
    stale.mkdir(parents=True)
    (stale / "issue_123.md").write_text("**Bucket:** REPRODUCED\n- verify: stale\n", encoding="utf-8")
    paths = pipeline.Paths(
        source=tmp_path / "source",
        final_selected=selected,
        reproduced=tmp_path / "reproduced",
        reproduction=tmp_path / "reproduction",
    )
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
    monkeypatch.setattr(pipeline, "OPENCLAW_RUNNER", Path(__file__))

    pipeline.run_reproduction(paths, dry_run=False, timeout=1)

    assert len(calls) == 2
    summary = (paths.reproduction / "reports" / "_summary.md").read_text(encoding="utf-8")
    assert "123" in summary
    assert "456" in summary
    assert not (paths.reproduction / "reports" / "issue_123.md").exists()
    assert {item.name for item in paths.reproduced.glob("*.txt")} == {"456.txt"}
    stage3 = json.loads((paths.reproduction / "stage3_input.json").read_text(encoding="utf-8"))
    assert stage3["issues"] == [{"issue_id": "456", "bucket": "POTENTIAL", "file": "456.txt"}]


def test_reproduced_report_requires_verify_evidence(tmp_path):
    report = tmp_path / "issue_123.md"
    report.write_text("# Issue 123\n\n**Bucket:** REPRODUCED\n\n- verify: browser title was example\n", encoding="utf-8")

    pipeline._validate_reproduced_report(report)

    report.write_text("# Issue 123\n\n**Bucket:** REPRODUCED\n", encoding="utf-8")
    try:
        pipeline._validate_reproduced_report(report)
    except ValueError as exc:
        assert "verify evidence" in str(exc)
    else:
        raise AssertionError("Expected reproduced reports without evidence to fail")


def test_stage3_input_forwards_reproduced_and_potential(tmp_path, monkeypatch):
    selected = tmp_path / "final_selected"
    selected.mkdir()
    (selected / "ok.txt").write_text("reproduced issue", encoding="utf-8")
    (selected / "maybe.txt").write_text("potential issue", encoding="utf-8")
    (selected / "dead.txt").write_text("not reproducible", encoding="utf-8")
    paths = pipeline.Paths(
        source=tmp_path / "source",
        final_selected=selected,
        reproduced=tmp_path / "reproduced",
        reproduction=tmp_path / "reproduction",
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
    monkeypatch.setattr(pipeline, "OPENCLAW_RUNNER", Path(__file__))

    pipeline.run_reproduction(paths, dry_run=False, timeout=1)

    assert {item.name for item in paths.reproduced.glob("*.txt")} == {"ok.txt", "maybe.txt"}
    stage3 = json.loads((paths.reproduction / "stage3_input.json").read_text(encoding="utf-8"))
    assert [item["bucket"] for item in stage3["issues"]] == ["POTENTIAL", "REPRODUCED"]


def test_attack_dry_run_uses_final_selected(tmp_path):
    selected = tmp_path / "final_selected"
    selected.mkdir()
    (selected / "123.txt").write_text("issue", encoding="utf-8")
    output = tmp_path / "attack"
    paths = pipeline.Paths(source=tmp_path / "source", final_selected=selected, attack_prompts=output)

    pipeline.run_attack_generator(paths, model="example-model", attack_input="final", dry_run=True)

    recorded = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert recorded["input"] == "final"
    assert recorded["issues"] == ["123.txt"]


def test_attack_defaults_to_reproduced_input():
    assert pipeline.parse_args([]).attack_input == "reproduced"


def test_source_tree_has_no_extra_repo_absolute_paths():
    forbidden = (
        r"C:\Users",
        r"D:\Codes",
        "/Users/",
        "Program Files",
        r"scoop\persist",
    )
    roots = [
        pipeline.WORKSPACE / "pipeline.py",
        pipeline.WORKSPACE / "scripts",
        pipeline.WORKSPACE / "vendor",
        pipeline.WORKSPACE / "skills",
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
