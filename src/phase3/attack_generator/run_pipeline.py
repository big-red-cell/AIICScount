import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

import check as check_stage
import main as generate_stage

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
STAGES = ("all", "generate", "check")
CHECK_MODEL_KEYS = ("PHASE3_MODEL", "CHECK_MODEL", "CHECKMODEL", "checkmodel")


class PipelineConfigError(Exception):
    pass


def discover_model_dirs(input_dir: Path | None = None) -> list[tuple[str, Path]]:
    input_dir = input_dir or INPUT_DIR
    if not input_dir.exists():
        return []

    model_dirs: list[tuple[str, Path]] = []
    for child in input_dir.iterdir():
        stage3_dir = child / "stage3"
        if child.is_dir() and stage3_dir.is_dir():
            model_dirs.append((child.name, stage3_dir))
    return sorted(model_dirs, key=lambda item: item[0].lower())


def collect_issue_ids(stage3_dir: Path) -> list[str]:
    return sorted(path.stem for path in stage3_dir.glob("*.txt") if path.is_file())


def model_output_paths(model_name: str, output_dir: Path | None = None) -> dict[str, Path]:
    output_dir = output_dir or OUTPUT_DIR
    model_output_dir = output_dir / model_name
    return {
        "letters": model_output_dir / "letters.json",
        "letters_status": model_output_dir / "letters.status.json",
        "replay": model_output_dir / "replay.json",
        "replay_status": model_output_dir / "replay.status.json",
    }


def resolve_check_model(dotenv_path: str | Path | None = None) -> str | None:
    file_values: dict[str, str] = {}
    resolved_path: Path | None = None
    if dotenv_path is not None:
        resolved_path = Path(dotenv_path)
    else:
        discovered = find_dotenv(usecwd=True)
        if discovered:
            resolved_path = Path(discovered)

    if resolved_path and resolved_path.exists():
        file_values.update(
            {key: value for key, value in dotenv_values(resolved_path).items() if value is not None}
        )

    for key in CHECK_MODEL_KEYS:
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()

    for key in CHECK_MODEL_KEYS:
        value = file_values.get(key)
        if value and value.strip():
            return value.strip()
    return None


def select_model_dirs(
    *,
    requested_model: str | None,
    input_dir: Path | None = None,
) -> list[tuple[str, Path]]:
    model_dirs = discover_model_dirs(input_dir)
    if requested_model is None:
        return model_dirs

    selected = [(name, path) for name, path in model_dirs if name == requested_model]
    if not selected:
        raise PipelineConfigError(f"No input directory found for model {requested_model!r}: input/{requested_model}/stage3")
    return selected


def run_model(model_name: str, stage3_dir: Path, *, stage: str, check_model: str | None) -> None:
    issue_ids = collect_issue_ids(stage3_dir)
    paths = model_output_paths(model_name)
    print(f"=== {model_name}: {len(issue_ids)} stage3 items ===")

    if stage in {"all", "generate"}:
        generate_stage.main(
            issue_ids,
            model=model_name,
            issues_dir=stage3_dir,
            letters_path=paths["letters"],
            letters_status_path=paths["letters_status"],
        )

    if stage in {"all", "check"}:
        if not check_model:
            raise PipelineConfigError("PHASE3_MODEL is required for check stage. Set PHASE3_MODEL in .env or environment.")
        if not paths["letters"].exists():
            raise PipelineConfigError(
                f"Missing generated letters for model {model_name!r}: {paths['letters']}. "
                f"Run `uv run python run_pipeline.py --model {model_name} --stage generate` first, "
                "or run the default `uv run python run_pipeline.py` to generate and check together."
            )
        check_stage.run_checks(
            issue_ids,
            model=check_model,
            letters_path=paths["letters"],
            replay_path=paths["replay"],
            replay_status_path=paths["replay_status"],
        )


def run_pipeline(*, model: str | None = None, stage: str = "all") -> None:
    if stage not in STAGES:
        raise PipelineConfigError(f"Invalid stage {stage!r}. Expected one of: {', '.join(STAGES)}")
    run_models(model=model, stage=stage, workers=1)


def run_models(*, model: str | None = None, stage: str = "all", workers: int = 1) -> None:
    if stage not in STAGES:
        raise PipelineConfigError(f"Invalid stage {stage!r}. Expected one of: {', '.join(STAGES)}")
    if workers < 1:
        raise PipelineConfigError("--workers must be greater than or equal to 1.")

    check_model = resolve_check_model() if stage in {"all", "check"} else None
    if stage in {"all", "check"} and not check_model:
        raise PipelineConfigError("PHASE3_MODEL is required for check stage. Set PHASE3_MODEL in .env or environment.")

    model_dirs = select_model_dirs(requested_model=model)
    if not model_dirs:
        raise PipelineConfigError("No input/*/stage3 directories found.")

    if workers == 1 or len(model_dirs) == 1:
        for model_name, stage3_dir in model_dirs:
            run_model(model_name, stage3_dir, stage=stage, check_model=check_model)
        return

    max_workers = min(workers, len(model_dirs))
    print(f"Running {len(model_dirs)} models with {max_workers} workers.")
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_model = {
            executor.submit(run_model, model_name, stage3_dir, stage=stage, check_model=check_model): model_name
            for model_name, stage3_dir in model_dirs
        }
        for future in as_completed(future_to_model):
            model_name = future_to_model[future]
            try:
                future.result()
            except PipelineConfigError as exc:
                errors.append(f"{model_name}: {exc}")
            except Exception as exc:
                errors.append(f"{model_name}: unexpected error: {exc}")

    if errors:
        raise PipelineConfigError("One or more model runs failed:\n" + "\n".join(errors))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stage3 generation and check pipeline.")
    parser.add_argument("--model", help="Run only input/<model>/stage3.")
    parser.add_argument("--stage", choices=STAGES, default="all", help="Pipeline stage to run.")
    parser.add_argument("--workers", type=int, default=1, help="Number of model directories to process in parallel.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_models(model=args.model, stage=args.stage, workers=args.workers)
    except PipelineConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
