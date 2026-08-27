import re
from pathlib import Path

from batch_state import BatchItemError, BatchRunStore
from openai_responses_client import OpenAIResponsesError, generate_response_text
from prompt import system_prompt_step1, system_prompt_step2

BASE_DIR = Path(__file__).resolve().parent
ISSUES_DIR = BASE_DIR / "issues"
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
LETTERS_PATH = OUTPUT_DIR / "letters.json"
LETTERS_STATUS_PATH = OUTPUT_DIR / "letters.status.json"
PARSE_ERROR_PREVIEW_CHARS = 500


def _resolve_issue_path(issue_no: object, issues_dir: Path | None = None) -> Path:
    issues_dir = issues_dir or ISSUES_DIR
    raw_issue = str(issue_no)
    exact_path = issues_dir / raw_issue
    if exact_path.exists():
        return exact_path

    if Path(raw_issue).suffix:
        return exact_path

    fallback_path = issues_dir / f"{raw_issue}.txt"
    if fallback_path.exists():
        return fallback_path

    return exact_path

def step1(issue_no: object, *, model: str | None = None, issues_dir: Path | None = None) -> str:
    issue_path = _resolve_issue_path(issue_no, issues_dir)
    try:
        with issue_path.open("r", encoding="utf-8") as f:
            issue_description = f.read()
    except OSError as exc:
        raise BatchItemError("step1_read", f"Could not read issue file {issue_path}: {exc}") from exc
    
    try:
        text = generate_response_text(
            userprompt=issue_description,
            sysprompt=system_prompt_step1,
            stream=True,
            model=model,
        )
    except OpenAIResponsesError as exc:
        raise BatchItemError("step1_request", f"Request failed: {exc}") from exc
    
    pharse2_match = re.search(r"<phase2>(.*?)</phase2>", text, re.DOTALL)
    if not pharse2_match:
        preview = _preview_text(text)
        raise BatchItemError("step1_parse", f"No phase2 content found. Model output preview: {preview}")
    return pharse2_match.group(1)

def step2(instructions: str, *, model: str | None = None) -> str:
    try:
        text = generate_response_text(
            userprompt=instructions,
            sysprompt=system_prompt_step2,
            stream=True,
            model=model,
        )
    except OpenAIResponsesError as exc:
        raise BatchItemError("step2_request", f"Request failed: {exc}") from exc
    return text

def main(
    issues_list: list[object],
    *,
    model: str | None = None,
    issues_dir: Path | None = None,
    letters_path: Path | None = None,
    letters_status_path: Path | None = None,
) -> None:
    issues_dir = issues_dir or ISSUES_DIR
    letters_path = letters_path or LETTERS_PATH
    letters_status_path = letters_status_path or LETTERS_STATUS_PATH
    store = BatchRunStore(results_path=letters_path, status_path=letters_status_path)
    pending_issues = store.pending_items(issues_list)

    if not pending_issues:
        print("No new or failed issues to process.")
        return

    for issue_no in pending_issues:
        print(f"Processing issue {issue_no}...")
        try:
            instructions = step1(issue_no, model=model, issues_dir=issues_dir)
            print(f"Generated instructions for issue {issue_no}")
            letter = step2(instructions, model=model)
        except BatchItemError as exc:
            store.record_error(issue_no, stage=exc.stage, error=str(exc))
            print(f"Marked issue {issue_no} as error ({exc.stage}): {exc}\n")
            continue
        except Exception as exc:
            store.record_error(issue_no, stage="unexpected_error", error=str(exc))
            print(f"Marked issue {issue_no} as error (unexpected_error): {exc}\n")
            continue

        store.record_success(issue_no, letter)
        print(f"Generated letter for issue {issue_no}\n")


def _preview_text(text: str, *, limit: int = PARSE_ERROR_PREVIEW_CHARS) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "<empty>"
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}...<truncated>"

if __name__ == "__main__":
    issues_list = [f.name for f in ISSUES_DIR.iterdir() if f.is_file()]
    main(issues_list)
