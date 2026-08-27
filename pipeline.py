#!/usr/bin/env python3
"""Adapter pipeline for Report Analyzer -> OpenClaw reproduction -> Attack Generator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


WORKSPACE = Path(__file__).resolve().parent
load_dotenv(WORKSPACE / ".env", override=False)
SENIOR_STAGE1_ROOT = WORKSPACE / "vendor" / "senior_stage1"
ATTACK_ROOT = WORKSPACE / "vendor" / "attack_generator"
OPENCLAW_RUNNER = WORKSPACE / "scripts" / "run_openclaw_reproduction.ps1"
STAGE3_BUCKETS = frozenset({"REPRODUCED", "POTENTIAL"})
SKIP_SOURCE_DIR_NAMES = frozenset({"archive", "fixtures", "example_inputs"})


@dataclass(frozen=True)
class Paths:
    source: Path
    staged_raw: Path = WORKSPACE / "issues" / "staged_raw"
    final_selected: Path = WORKSPACE / "issues" / "final_selected"
    reproduced: Path = WORKSPACE / "issues" / "reproduced"
    analyzer_artifacts: Path = WORKSPACE / "artifacts" / "analyzer"
    reproduction: Path = WORKSPACE / "artifacts" / "reproduction"
    attack_prompts: Path = WORKSPACE / "artifacts" / "attack_prompts"


def issue_files(directory: Path, *, skip_dir_names: frozenset[str] | None = None) -> list[Path]:
    if not directory.is_dir():
        return []
    skip = skip_dir_names or frozenset()

    def keep(path: Path) -> bool:
        if not path.is_file():
            return False
        relative_dirs = path.relative_to(directory).parts[:-1]
        return not any(part in skip for part in relative_dirs)

    return sorted((path for path in directory.rglob("*.txt") if keep(path)), key=lambda path: path.as_posix())


def safe_staged_name(source_root: Path, issue: Path) -> str:
    relative = issue.relative_to(source_root)
    stem = "__".join(relative.with_suffix("").parts)
    digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:10]
    return f"{stem}__{digest}.txt"


def stage_source_files(source: Path, staged_raw: Path) -> list[Path]:
    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")
    staged_raw.mkdir(parents=True, exist_ok=True)
    expected: set[Path] = set()
    for issue in issue_files(source, skip_dir_names=SKIP_SOURCE_DIR_NAMES):
        destination = staged_raw / safe_staged_name(source, issue)
        shutil.copy2(issue, destination)
        expected.add(destination)
    for old_file in staged_raw.glob("*.txt"):
        if old_file not in expected:
            old_file.unlink()
    return sorted(expected)


def run_analyzer(paths: Paths, *, model: str | None, dry_run: bool) -> None:
    staged = stage_source_files(paths.source, paths.staged_raw)
    if not staged:
        raise ValueError(f"No .txt issue files found below: {paths.source}")

    command = [
        sys.executable,
        str(SENIOR_STAGE1_ROOT / "process_txt_with_llm.py"),
        "--input-dir",
        str(paths.staged_raw),
        "--stage",
        "1",
        "--final-dir",
        str(paths.final_selected),
    ]
    _write_json(paths.analyzer_artifacts / "command.json", {"command": command, "source_count": len(staged)})

    if dry_run:
        print(f"[dry-run] Staged {len(staged)} issue(s); senior Stage 1 command recorded.")
        return

    environment = os.environ.copy()
    if model:
        environment["LLM_MODEL"] = model
    subprocess.run(command, cwd=WORKSPACE, env=environment, check=True)
    if not paths.final_selected.is_dir():
        raise RuntimeError(f"Senior Stage 1 did not create final output: {paths.final_selected}")
    print(f"Phase 1 complete: {len(issue_files(paths.final_selected))} selected issue(s).")


def prepare_reproduction(paths: Paths, *, dry_run: bool) -> None:
    selected = issue_files(paths.final_selected)
    if not selected:
        raise ValueError(f"No selected issue files found: {paths.final_selected}")
    reports_dir = paths.reproduction / "reports"
    evidence_dir = paths.reproduction / "evidence"
    repro_dir = paths.reproduction / "repro"
    for directory in (reports_dir, evidence_dir, repro_dir):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": "behavior_reproducer",
        "status": "prepared" if dry_run else "pending_openclaw_reproduction",
        "skill": "skills/browser-agent-issue-reproduction",
        "issues": [
            {
                "issue_id": issue.stem,
                "path": str(issue.relative_to(WORKSPACE)).replace("\\", "/"),
                "report": f"artifacts/reproduction/reports/issue_{issue.stem}.md",
                "workspace": f"artifacts/reproduction/repro/issue_{issue.stem}/",
            }
            for issue in selected
        ],
    }
    _write_json(paths.reproduction / "manifest.json", manifest)
    mode = "[dry-run] " if dry_run else ""
    print(f"{mode}Phase 2 prepared: {len(selected)} issue(s) awaiting OpenClaw reproduction.")


def _read_report_bucket(report: Path) -> str | None:
    if not report.is_file():
        return None
    match = re.search(r"^\*\*Bucket:\*\*\s*(REPRODUCED|POTENTIAL|NOT_REPRODUCIBLE)\b", report.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def _validate_reproduced_report(report: Path) -> None:
    content = report.read_text(encoding="utf-8")
    if _read_report_bucket(report) != "REPRODUCED":
        raise ValueError(f"Report is not marked REPRODUCED: {report}")
    if not re.search(r"^\s*-\s*verify:\s*\S+", content, re.MULTILINE | re.IGNORECASE):
        raise ValueError(f"REPRODUCED report has no concrete verify evidence: {report}")


def _validate_stage3_report(report: Path, bucket: str) -> None:
    if bucket == "REPRODUCED":
        _validate_reproduced_report(report)
        return
    if bucket == "POTENTIAL":
        if _read_report_bucket(report) != "POTENTIAL":
            raise ValueError(f"Report is not marked POTENTIAL: {report}")
        return
    raise ValueError(f"Bucket {bucket} is not forwarded to Stage 3: {report}")


def _write_reproduction_summary(paths: Paths, selected: list[Path]) -> dict[str, str]:
    buckets: dict[str, list[str]] = {"REPRODUCED": [], "POTENTIAL": [], "NOT_REPRODUCIBLE": [], "MISSING": []}
    statuses: dict[str, str] = {}
    for issue in selected:
        issue_id = issue.stem
        report = paths.reproduction / "reports" / f"issue_{issue_id}.md"
        bucket = _read_report_bucket(report) or "MISSING"
        buckets[bucket].append(issue_id)
        statuses[issue_id] = bucket

    lines = [
        "# Reproduction Summary",
        f"Total: {len(selected)} | Reproduced: {len(buckets['REPRODUCED'])} | Potential: {len(buckets['POTENTIAL'])} | Not Reproducible: {len(buckets['NOT_REPRODUCIBLE'])}",
        "",
    ]
    for bucket, heading in (("REPRODUCED", "## Reproduced"), ("POTENTIAL", "## Potential"), ("NOT_REPRODUCIBLE", "## Not Reproducible"), ("MISSING", "## Missing reports")):
        lines.append(heading)
        if buckets[bucket]:
            lines.extend(f"- `{issue_id}`" for issue_id in buckets[bucket])
        else:
            lines.append("- none")
        lines.append("")
    (paths.reproduction / "reports" / "_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return statuses


def _kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True, text=True)


def _kill_issue_leftovers(issue_stem: str) -> None:
    escaped = re.escape(issue_stem)
    script = (
        "$skip = 'python.exe|powershell.exe|pwsh.exe'; "
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -notmatch $skip -and $_.CommandLine -and ("
        f"$_.CommandLine -match 'aiic-repro-{escaped}' -or "
        f"$_.CommandLine -match 'reproduction\\\\repro\\\\issue_{escaped}'"
        ") } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False, capture_output=True, text=True)


def _run_openclaw_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    issue_stem: str,
) -> tuple[int, str]:
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    output = ""
    try:
        output, _ = proc.communicate(timeout=timeout + 45)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc.pid)
        try:
            tail, _ = proc.communicate(timeout=20)
            output = (output or "") + (tail or "")
        except Exception:
            pass
        output = (output or "") + f"\nHARD_TIMEOUT after {timeout}s\n"
    _kill_issue_leftovers(issue_stem)
    code = 124 if timed_out else (proc.returncode if proc.returncode is not None else 1)
    return code, output or ""


def _openclaw_issue_command(issue: Path, report: Path, timeout: int) -> list[str]:
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(OPENCLAW_RUNNER),
        "-IssuePath",
        str(issue),
        "-ReportPath",
        str(report),
        "-TimeoutSeconds",
        str(timeout),
    ]


def run_reproduction(
    paths: Paths,
    *,
    dry_run: bool,
    timeout: int,
    keep_existing_reports: bool = False,
    issue_stems: list[str] | None = None,
) -> None:
    prepare_reproduction(paths, dry_run=dry_run)
    if dry_run:
        return
    if not OPENCLAW_RUNNER.is_file():
        raise RuntimeError(f"OpenClaw runner is missing: {OPENCLAW_RUNNER}")

    selected = issue_files(paths.final_selected)
    if issue_stems:
        needles = tuple(issue_stems)
        selected = [item for item in selected if any(needle in item.stem for needle in needles)]
        if not selected:
            raise ValueError(f"No final_selected issues matched --issue-stem: {', '.join(issue_stems)}")
    priority_stems = {item.stem for item in issue_files(paths.reproduced)}
    selected = sorted(selected, key=lambda item: (0 if item.stem in priority_stems else 1, item.as_posix()))
    paths.reproduced.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()

    def attempt(issue: Path, *, force: bool) -> None:
        report = paths.reproduction / "reports" / f"issue_{issue.stem}.md"
        if keep_existing_reports and not force and _read_report_bucket(report) in {"REPRODUCED", "POTENTIAL", "NOT_REPRODUCIBLE"}:
            print(f"Skip existing report: {report.name}")
            return
        if report.exists():
            report.unlink()
        command = _openclaw_issue_command(issue, report, timeout)
        print(f"OpenClaw start: {issue.name} (timeout {timeout}s)", flush=True)
        code, text = _run_openclaw_command(
            command,
            cwd=WORKSPACE,
            env=environment,
            timeout=timeout,
            issue_stem=issue.stem,
        )
        log = paths.reproduction / "openclaw" / f"issue_{issue.stem}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
        bucket = _read_report_bucket(report)
        if bucket in {"REPRODUCED", "POTENTIAL", "NOT_REPRODUCIBLE"}:
            print(f"OpenClaw wrote {bucket} report for {issue.name} (exit {code})", flush=True)
            return
        if code:
            print(
                f"OpenClaw failed for {issue.name} (exit {code}); "
                f"see {log.relative_to(WORKSPACE)}",
                file=sys.stderr,
            )

    for issue in selected:
        attempt(issue, force=False)

    statuses = _write_reproduction_summary(paths, selected)
    if not keep_existing_reports:
        for issue in selected:
            if issue.stem in priority_stems and statuses.get(issue.stem) == "MISSING":
                print(f"Retry priority issue with no report: {issue.name}", flush=True)
                attempt(issue, force=True)
        statuses = _write_reproduction_summary(paths, selected)
    summary_issues = issue_files(paths.final_selected) if keep_existing_reports else selected
    statuses = _write_reproduction_summary(paths, summary_issues)
    forwarded: list[dict[str, str]] = []
    for issue in summary_issues:
        bucket = statuses[issue.stem]
        if bucket not in STAGE3_BUCKETS:
            continue
        report = paths.reproduction / "reports" / f"issue_{issue.stem}.md"
        try:
            _validate_stage3_report(report, bucket)
        except ValueError as exc:
            print(f"Skip invalid Stage 3 report for {issue.name}: {exc}", file=sys.stderr)
            continue
        shutil.copy2(issue, paths.reproduced / issue.name)
        forwarded.append({"issue_id": issue.stem, "bucket": bucket, "file": issue.name})
    if forwarded and not keep_existing_reports:
        expected_names = {item["file"] for item in forwarded}
        for old_issue in paths.reproduced.glob("*.txt"):
            if old_issue.name not in expected_names:
                old_issue.unlink()

    _write_json(paths.reproduction / "stage3_input.json", {"issues": forwarded})
    forwarded_issues = issue_files(paths.reproduced)
    missing = [issue.name for issue in summary_issues if statuses[issue.stem] == "MISSING"]
    if missing and len(missing) == len(summary_issues) and not keep_existing_reports:
        raise RuntimeError("OpenClaw created no reports: " + ", ".join(missing))
    reproduced_count = sum(1 for item in forwarded if item["bucket"] == "REPRODUCED")
    potential_count = sum(1 for item in forwarded if item["bucket"] == "POTENTIAL")
    print(
        f"Phase 2 complete: {len(forwarded_issues)} issue(s) forwarded to Stage 3 "
        f"({reproduced_count} REPRODUCED, {potential_count} POTENTIAL); "
        f"missing reports: {len(missing)}."
    )


def run_attack_generator(paths: Paths, *, model: str | None, attack_input: str, dry_run: bool) -> None:
    input_dir = paths.reproduced if attack_input == "reproduced" else paths.final_selected
    selected = issue_files(input_dir)
    if not selected:
        raise ValueError(f"No .txt issue files found for Phase 3: {input_dir}")
    paths.attack_prompts.mkdir(parents=True, exist_ok=True)
    issues = [issue.name for issue in selected]
    record = {
        "stage": "attack_generator",
        "input": attack_input,
        "issue_count": len(issues),
        "issues": issues,
        "model": model,
    }
    _write_json(paths.attack_prompts / "run.json", record)
    if dry_run:
        print(f"[dry-run] Phase 3 routed {len(issues)} issue(s) from {input_dir.name}.")
        return

    sys.path.insert(0, str(ATTACK_ROOT))
    try:
        import main as attack_main

        attack_main.main(
            issues,
            model=model,
            issues_dir=input_dir,
            letters_path=paths.attack_prompts / "letters.json",
            letters_status_path=paths.attack_prompts / "letters.status.json",
        )
    finally:
        sys.path.remove(str(ATTACK_ROOT))
    print(f"Phase 3 complete: generated output under {paths.attack_prompts}.")


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the three-stage AIIC research pipeline.")
    parser.add_argument("--stage", choices=("analyze", "reproduce", "attack", "all"), default="all")
    parser.add_argument("--source", type=Path, default=WORKSPACE / "issues" / "source")
    parser.add_argument("--model", help="Model passed to the active LLM-backed stage.")
    parser.add_argument("--attack-input", choices=("final", "reproduced"), default="reproduced")
    parser.add_argument("--reproduction-timeout", type=int, default=900, help="Per-issue OpenClaw timeout in seconds.")
    parser.add_argument(
        "--keep-existing-reports",
        action="store_true",
        help="Skip OpenClaw for issues that already have a bucketed Stage 2 report.",
    )
    parser.add_argument(
        "--issue-stem",
        action="append",
        default=None,
        help="Only reproduce issues whose filename stem contains this value. Repeatable.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Prepare inputs and records without calling an LLM.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    os.chdir(WORKSPACE)
    args = parse_args(argv)
    paths = Paths(source=args.source.resolve())
    try:
        if args.stage in {"analyze", "all"}:
            run_analyzer(paths, model=args.model, dry_run=args.dry_run)
        if args.stage in {"reproduce", "all"}:
            run_reproduction(
                paths,
                dry_run=args.dry_run,
                timeout=args.reproduction_timeout,
                keep_existing_reports=args.keep_existing_reports,
                issue_stems=args.issue_stem,
            )
        if args.stage in {"attack", "all"}:
            run_attack_generator(paths, model=args.model, attack_input=args.attack_input, dry_run=args.dry_run)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
