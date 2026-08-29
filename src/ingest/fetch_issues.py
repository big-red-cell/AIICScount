#!/usr/bin/env python3
"""Fetch raw Chromium issue updates for IDs produced by fetch_ids.py."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://issues.chromium.org/action/issues/{issue_id}/updates?currentTrackerId=157"


def _token() -> str | None:
    return os.getenv("CHROMIUM_XSRF_TOKEN") or os.getenv("XSRF_TOKEN") or os.getenv("XSRF-TOKEN")


def _cookies() -> dict[str, str]:
    raw = os.getenv("CHROMIUM_COOKIES_JSON") or os.getenv("CHROMIUM_COOKIES")
    if not raw:
        return {}
    path = Path(raw).expanduser()
    if path.is_file():
        raw = path.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Chromium cookies must be a JSON object")
    return {str(k): str(v) for k, v in value.items() if v is not None}


def _headers() -> dict[str, str]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.8",
        "content-type": "application/json",
        "user-agent": "aiic-three-stage-pipeline/0.1",
    }
    token = _token()
    if token:
        headers["x-xsrf-token"] = token
    return headers


def _decode_response(text: str) -> Any:
    cleaned = text.lstrip()
    if cleaned.startswith(")]}'"):
        cleaned = cleaned.split("\n", 1)[-1]
    return json.loads(cleaned)


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)


def parse_comments(data: Any) -> list[tuple[str, str]]:
    """Return likely (author, body) pairs from the tracker RPC response."""
    comments: list[tuple[str, str]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            strings = [s.strip() for s in _walk_strings(value) if s.strip()]
            emails = [s for s in strings if "@" in s and "." in s]
            if strings and emails:
                body = max((s for s in strings if s not in emails), key=len, default="")
                if len(body) >= 2:
                    pair = (emails[0], body)
                    if pair not in comments:
                        comments.append(pair)
            for child in value:
                walk(child)
        elif isinstance(value, dict):
            walk(list(value.values()))

    walk(data)
    return comments


def load_issue_ids(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def fetch_issue(session: requests.Session, issue_id: str, *, timeout: float) -> list[tuple[str, str]]:
    response = session.post(BASE_URL.format(issue_id=issue_id), headers=_headers(), cookies=_cookies(), data=json.dumps([issue_id, "ASC", None, None, 2]), timeout=timeout)
    response.raise_for_status()
    return parse_comments(_decode_response(response.text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, default=Path("results/chrome_issue/phase1/metadata/chromium_issue_ids.txt"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/chrome_issue/phase1/input"))
    parser.add_argument("--manifest", type=Path, default=Path("results/chrome_issue/phase1/metadata/chromium_fetch_manifest.json"))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not _token():
        parser.error("Set CHROMIUM_XSRF_TOKEN (or XSRF_TOKEN) from a current browser request")
    ids = load_issue_ids(args.ids)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"source": "Chromium Issue Tracker", "requested": len(ids), "succeeded": [], "failed": {}}
    with requests.Session() as session:
        for issue_id in ids:
            try:
                comments = fetch_issue(session, issue_id, timeout=args.timeout)
                destination = args.output_dir / f"{issue_id}.txt"
                body = "\n\n".join(f"Author: {author}\n{content}" for author, content in comments)
                destination.write_text(f"Issue ID: {issue_id}\n\n{body}\n", encoding="utf-8")
                manifest["succeeded"].append(issue_id)
                print(f"issue {issue_id}: {len(comments)} comments -> {destination}")
            except Exception as exc:
                manifest["failed"][issue_id] = str(exc)
                print(f"issue {issue_id} failed: {exc}")
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if not manifest["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
