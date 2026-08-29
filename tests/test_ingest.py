import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / "ingest" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_issue_ids_prefers_tracker_rows():
    module = load("fetch_ids")
    fixture = [[None, None, None, None, None, None, [[[None, 123456789], [None, 987654321]]]]]
    assert module.extract_issue_ids(fixture) == ["123456789", "987654321"]


def test_decode_xssi_and_parse_comments():
    ids = load("fetch_ids")
    issues = load("fetch_issues")
    assert ids._decode_response(")]}'\n[[1]]") == [[1]]
    payload = [["response", [[None, [[None, "alice@example.com"], ["A useful comment"]]]]]]
    assert issues.parse_comments(payload) == [("alice@example.com", "A useful comment")]


def test_fetch_issue_ids_ignores_comments(tmp_path):
    module = load("fetch_issues")
    path = tmp_path / "ids.txt"
    path.write_text("# comment\n123456789\n\n", encoding="utf-8")
    assert module.load_issue_ids(path) == ["123456789"]
