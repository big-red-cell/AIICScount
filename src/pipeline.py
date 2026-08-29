#!/usr/bin/env python3
"""Adapter pipeline for Report Analyzer -> OpenClaw reproduction -> Attack Generator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


WORKSPACE = Path(__file__).resolve().parents[1]
load_dotenv(WORKSPACE / ".env", override=False)
SENIOR_STAGE1_ROOT = WORKSPACE / "src" / "phase1"
ATTACK_ROOT = WORKSPACE / "src" / "phase3" / "attack_generator"
OPENCLAW_UNIX_RUNNER = WORKSPACE / "src" / "phase2" / "run_openclaw_reproduction.sh"
STAGE3_BUCKETS = frozenset({"REPRODUCED", "POTENTIAL"})
SKIP_SOURCE_DIR_NAMES = frozenset({"archive", "fixtures", "example_inputs"})
RESULT_FAMILIES = {"chrome": "chrome_issue", "ubuntu": "ubuntu_issue"}


@dataclass(frozen=True)
class Paths:
    source: Path
    staged_raw: Path = WORKSPACE / "results" / "phase1" / "prepared_input"
    stage1: Path = WORKSPACE / "results" / "phase1" / "stage1"
    stage2: Path = WORKSPACE / "results" / "phase1" / "stage2"
    stage3: Path = WORKSPACE / "results" / "phase1" / "stage3"
    # ``reproduce`` is the only Phase 2 directory consumed by Phase 3.
    # Keep all diagnostic artifacts below ``tmp`` so the hand-off stays text-only.
    reproduce: Path = WORKSPACE / "results" / "phase2" / "reproduce"
    analyzer_artifacts: Path = WORKSPACE / "results" / "phase1" / "metadata"
    tmp: Path = WORKSPACE / "results" / "phase2" / "tmp"
    attack_prompts: Path = WORKSPACE / "results" / "phase3"


def paths_for_family(family: str, source: Path | None = None) -> Paths:
    """Build paths rooted at results/{chrome_issue,ubuntu_issue}."""
    bucket = RESULT_FAMILIES.get(family, family)
    root = WORKSPACE / "results" / bucket
    return Paths(
        source=(source or (root / "phase1" / "input")).resolve(),
        staged_raw=root / "phase1" / "prepared_input",
        stage1=root / "phase1" / "stage1",
        stage2=root / "phase1" / "stage2",
        stage3=root / "phase1" / "stage3",
        reproduce=root / "phase2" / "reproduce",
        analyzer_artifacts=root / "phase1" / "metadata",
        tmp=root / "phase2" / "tmp",
        attack_prompts=root / "phase3",
    )


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


def run_analyzer(paths: Paths, *, model: str | None, platform: str = "chrome") -> None:
    staged = stage_source_files(paths.source, paths.staged_raw)
    if not staged:
        raise ValueError(f"No .txt issue files found below: {paths.source}")

    command = [
        sys.executable,
        str(SENIOR_STAGE1_ROOT / "analyze_issues.py"),
        "--input-dir",
        str(paths.staged_raw),
        "--stage1-dir",
        str(paths.stage1),
        "--stage2-dir",
        str(paths.stage2),
        "--stage3-dir",
        str(paths.stage3),
        "--platform",
        platform if platform in {"chrome", "ubuntu"} else "chrome",
    ]
    _write_json(paths.analyzer_artifacts / "command.json", {"command": command, "source_count": len(staged)})
    environment = os.environ.copy()
    node_path = os.getenv("OPENCLAW_NODE_PATH")
    if node_path:
        environment["PATH"] = str(Path(node_path).expanduser().parent) + os.pathsep + environment.get("PATH", "")
    if model:
        environment["PHASE1_MODEL"] = model
    subprocess.run(command, cwd=WORKSPACE, env=environment, check=True)
    if not paths.stage3.is_dir():
        raise RuntimeError(f"Senior Stage 1 did not create Stage 3 output: {paths.stage3}")
    _validate_phase1_consistency(paths)
    print(f"Phase 1 complete: {len(issue_files(paths.stage3))} selected issue(s).")


def _validate_phase1_consistency(paths: Paths) -> None:
    """Ensure every Stage 3 selection has all three Phase 1 stage artifacts."""
    selected = {path.name for path in issue_files(paths.stage3)}
    missing = {
        stage: sorted(selected - {path.name for path in issue_files(directory)})
        for stage, directory in (("stage1", paths.stage1), ("stage2", paths.stage2), ("stage3", paths.stage3))
    }
    missing = {stage: names for stage, names in missing.items() if names}
    if missing:
        details = "; ".join(f"{stage}: {', '.join(names)}" for stage, names in missing.items())
        raise RuntimeError(f"Phase 1 artifacts are inconsistent; selected issue(s) missing prerequisites ({details})")


def _platform_for_issue(issue: Path, requested: str) -> str:
    """Resolve a target platform from an explicit flag or input directory name."""
    if requested in {"chrome", "ubuntu"}:
        return requested
    parts = {part.lower() for part in issue.parts}
    if any("ubuntu" in part or "launchpad" in part for part in parts):
        return "ubuntu"
    return "chrome"


def _workspace_relative(path: Path) -> str:
    """Return a portable manifest path, including temporary test workspaces."""
    try:
        return str(path.relative_to(WORKSPACE)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def prepare_reproduction(paths: Paths, *, platform: str = "chrome") -> None:
    selected = issue_files(paths.stage3)
    if not selected:
        raise ValueError(f"No Stage 3 issue files found: {paths.stage3}")
    reports_dir = paths.tmp / "reports"
    evidence_dir = paths.tmp / "evidence"
    repro_dir = paths.tmp / "workspaces"
    for directory in (reports_dir, evidence_dir, repro_dir):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": "behavior_reproducer",
        "status": "pending_openclaw_reproduction",
        "skill": ("src/phase2/ubuntu_issue_reproduction" if platform == "ubuntu" else "src/phase2/browser_agent_issue_reproduction"),
        "issues": [
            {
                "issue_id": issue.stem,
                "path": _workspace_relative(issue),
                "report": _workspace_relative(paths.tmp / "reports" / f"issue_{issue.stem}.md"),
                "workspace": _workspace_relative(paths.tmp / "workspaces" / f"issue_{issue.stem}") + "/",
                "platform": _platform_for_issue(issue, platform),
            }
            for issue in selected
        ],
    }
    _write_json(paths.tmp / "manifest.json", manifest)
    print(f"Phase 2 prepared: {len(selected)} issue(s) awaiting OpenClaw reproduction.")


def _read_report_bucket(report: Path) -> str | None:
    if not report.is_file():
        return None
    match = re.search(r"^\*\*Bucket:\*\*\s*(REPRODUCED|POTENTIAL|NOT_REPRODUCIBLE)\b", report.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def _validate_reproduce_report(report: Path) -> None:
    content = report.read_text(encoding="utf-8")
    if _read_report_bucket(report) != "REPRODUCED":
        raise ValueError(f"Report is not marked REPRODUCED: {report}")
    if not re.search(r"^\s*-\s*verify:\s*\S+", content, re.MULTILINE | re.IGNORECASE):
        raise ValueError(f"REPRODUCED report has no concrete verify evidence: {report}")


def _validate_stage3_report(report: Path, bucket: str) -> None:
    if bucket == "REPRODUCED":
        _validate_reproduce_report(report)
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
        report = paths.tmp / "reports" / f"issue_{issue_id}.md"
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
    (paths.tmp / "reports" / "_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return statuses


def _kill_process_tree(pid: int, *, force: bool = False) -> None:
    """Terminate a runner and its descendants on the current host.

    Unix runners are started in their own process group, so signalling the
    group also reaches OpenClaw's child processes. A forced pass is used after
    a timeout when a child ignores SIGTERM.
    """
    if pid <= 0:
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            return


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
        start_new_session=True,
    )
    timed_out = False
    output = ""
    try:
        output, _ = proc.communicate(timeout=timeout + 45)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc.pid)
        try:
            tail, _ = proc.communicate(timeout=5)
            output = (output or "") + (tail or "")
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid, force=True)
            try:
                tail, _ = proc.communicate(timeout=5)
                output = (output or "") + (tail or "")
            except Exception:
                pass
        except Exception:
            pass
        output = (output or "") + f"\nHARD_TIMEOUT after {timeout}s\n"
    code = 124 if timed_out else (proc.returncode if proc.returncode is not None else 1)
    return code, output or ""


def _openclaw_issue_command(issue: Path, report: Path, timeout: int, platform: str = "chrome") -> list[str]:
    """Build a platform-specific OpenClaw runner command."""
    resolved_platform = _platform_for_issue(issue, platform)
    # This project runs on Ubuntu; always use the native Bash runner.
    return ["bash", str(OPENCLAW_UNIX_RUNNER), "-IssuePath", str(issue), "-ReportPath", str(report),
            "-TimeoutSeconds", str(timeout), "-Platform", resolved_platform]


def run_reproduction(
    paths: Paths,
    *,
    timeout: int,
    keep_existing_reports: bool = False,
    issue_stems: list[str] | None = None,
    platform: str = "chrome",
) -> None:
    prepare_reproduction(paths, platform=platform)
    unix_runner = OPENCLAW_UNIX_RUNNER
    if not unix_runner.is_file():
        raise RuntimeError(f"OpenClaw runner is missing: {unix_runner}")

    selected = issue_files(paths.stage3)
    if issue_stems:
        needles = tuple(issue_stems)
        selected = [item for item in selected if any(needle in item.stem for needle in needles)]
        if not selected:
            raise ValueError(f"No Stage 3 issues matched --issue-stem: {', '.join(issue_stems)}")
    priority_stems = {item.stem for item in issue_files(paths.reproduce)}
    selected = sorted(selected, key=lambda item: (0 if item.stem in priority_stems else 1, item.as_posix()))
    paths.reproduce.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    node_path = os.getenv("OPENCLAW_NODE_PATH")
    if node_path:
        environment["PATH"] = str(Path(node_path).expanduser().parent) + os.pathsep + environment.get("PATH", "")

    def attempt(issue: Path, *, force: bool) -> None:
        report = paths.tmp / "reports" / f"issue_{issue.stem}.md"
        if keep_existing_reports and not force and _read_report_bucket(report) in {"REPRODUCED", "POTENTIAL", "NOT_REPRODUCIBLE"}:
            print(f"Skip existing report: {report.name}")
            return
        if report.exists():
            report.unlink()
        command = _openclaw_issue_command(issue, report, timeout, platform)
        print(f"OpenClaw start: {issue.name} (timeout {timeout}s)", flush=True)
        code, text = _run_openclaw_command(
            command,
            cwd=WORKSPACE,
            env=environment,
            timeout=timeout,
            issue_stem=issue.stem,
        )
        log = paths.tmp / "openclaw" / f"issue_{issue.stem}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
        bucket = _read_report_bucket(report)
        if bucket in {"REPRODUCED", "POTENTIAL", "NOT_REPRODUCIBLE"}:
            print(f"OpenClaw wrote {bucket} report for {issue.name} (exit {code})", flush=True)
            return
        if code:
            print(
                f"OpenClaw failed for {issue.name} (exit {code}); "
                f"see {_workspace_relative(log)}",
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
    summary_issues = issue_files(paths.stage3) if keep_existing_reports else selected
    statuses = _write_reproduction_summary(paths, summary_issues)
    forwarded: list[dict[str, str]] = []
    for issue in summary_issues:
        bucket = statuses[issue.stem]
        if bucket not in STAGE3_BUCKETS:
            continue
        report = paths.tmp / "reports" / f"issue_{issue.stem}.md"
        try:
            _validate_stage3_report(report, bucket)
        except ValueError as exc:
            print(f"Skip invalid Stage 3 report for {issue.name}: {exc}", file=sys.stderr)
            continue
        shutil.copy2(issue, paths.reproduce / issue.name)
        forwarded.append({"issue_id": issue.stem, "bucket": bucket, "file": issue.name})
    # The hand-off directory is deliberately a flat, text-only output. Remove
    # stale files/directories even when this run forwards no issues.
    expected_names = {item["file"] for item in forwarded}
    for old_entry in paths.reproduce.iterdir():
        if old_entry.is_file() and not old_entry.is_symlink() and old_entry.name in expected_names and old_entry.suffix == ".txt":
            continue
        if old_entry.is_dir():
            shutil.rmtree(old_entry)
        else:
            old_entry.unlink()

    _write_json(paths.tmp / "stage3_input.json", {"issues": forwarded})
    forwarded_issues = issue_files(paths.reproduce)
    missing = [issue.name for issue in summary_issues if statuses[issue.stem] == "MISSING"]
    if missing and len(missing) == len(summary_issues) and not keep_existing_reports:
        raise RuntimeError("OpenClaw created no reports: " + ", ".join(missing))
    reproduce_count = sum(1 for item in forwarded if item["bucket"] == "REPRODUCED")
    potential_count = sum(1 for item in forwarded if item["bucket"] == "POTENTIAL")
    print(
        f"Phase 2 complete: {len(forwarded_issues)} issue(s) forwarded to Stage 3 "
        f"({reproduce_count} REPRODUCED, {potential_count} POTENTIAL); "
        f"missing reports: {len(missing)}."
    )


def run_attack_generator(paths: Paths, *, model: str | None, attack_input: str, platform: str = "chrome") -> None:
    input_dir = paths.reproduce if attack_input == "reproduce" else paths.stage3
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
    sys.path.insert(0, str(ATTACK_ROOT))
    previous_log_path = os.environ.get("PHASE3_LOG_PATH")
    os.environ["PHASE3_LOG_PATH"] = str(paths.attack_prompts / "openai_responses.log")
    try:
        import main as attack_main

        attack_main.main(
            issues,
            model=model,
            issues_dir=input_dir,
            letters_path=paths.attack_prompts / "letters.json",
            letters_status_path=paths.attack_prompts / "letters.status.json",
            platform=platform,
        )
    finally:
        sys.path.remove(str(ATTACK_ROOT))
        if previous_log_path is None:
            os.environ.pop("PHASE3_LOG_PATH", None)
        else:
            os.environ["PHASE3_LOG_PATH"] = previous_log_path
    print(f"Phase 3 complete: generated output under {paths.attack_prompts}.")


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the three-stage AIIC research pipeline.")
    parser.add_argument("--stage", choices=("analyze", "reproduce", "attack", "all"), default="all")
    parser.add_argument("--source", type=Path, default=None, help="Override the family input directory")
    parser.add_argument("--model", help="Model passed to the active LLM-backed stage.")
    parser.add_argument("--attack-input", choices=("stage3", "reproduce"), default="reproduce")
    parser.add_argument("--reproduction-timeout", type=int, default=900, help="Per-issue OpenClaw timeout in seconds.")
    parser.add_argument("--platform", choices=("chrome", "ubuntu", "auto", "both"), default="chrome",
                        help="Phase 2 target environment. 'both' infers platform from input path names.")
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
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    os.chdir(WORKSPACE)
    args = parse_args(argv)
    family = args.platform if args.platform in RESULT_FAMILIES else "chrome"
    paths = paths_for_family(family, args.source)
    try:
        if args.stage in {"analyze", "all"}:
            run_analyzer(paths, model=args.model, platform=family)
        if args.stage in {"reproduce", "all"}:
            run_reproduction(
                paths,
                timeout=args.reproduction_timeout,
                keep_existing_reports=args.keep_existing_reports,
                issue_stems=args.issue_stem,
                platform=args.platform,
            )
        if args.stage in {"attack", "all"}:
            run_attack_generator(paths, model=args.model, attack_input=args.attack_input, platform=family)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
