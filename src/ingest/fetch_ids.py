#!/usr/bin/env python3
"""Fetch Chromium issue IDs from the public tracker list endpoint.

The endpoint requires the current browser XSRF token in many deployments. Keep
tokens and cookies in the environment, never in this source file.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://issues.chromium.org/action/issues/list"
DEFAULT_QUERY = "type:vulnerability status:intended_behavior"
DEFAULT_SORT = "created_time desc"


def _token() -> str | None:
    return os.getenv("CHROMIUM_XSRF_TOKEN") or os.getenv("XSRF_TOKEN") or os.getenv("XSRF-TOKEN")


def _cookies() -> dict[str, str]:
    raw = os.getenv("CHROMIUM_COOKIES_JSON") or os.getenv("CHROMIUM_COOKIES")
    if not raw:
        return {}
    path = Path(raw).expanduser()
    if path.is_file():
        raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CHROMIUM_COOKIES_JSON must be a JSON object or a path to one") from exc
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


def build_body(start_index: int, *, page_size: int, query: str, sort: str) -> str:
    return json.dumps([None, None, None, None, None, ["157"], [[query, sort, page_size, f"start_index:{start_index}"]]], separators=(",", ":"))


def _decode_response(text: str) -> Any:
    cleaned = text.lstrip()
    if cleaned.startswith(")]}'"):
        cleaned = cleaned.split("\n", 1)[-1]
    return json.loads(cleaned)


def extract_issue_ids(data: Any) -> list[str]:
    """Extract IDs while tolerating minor tracker envelope changes."""
    found: list[str] = []

    # Current tracker envelope: response -> block 6 -> rows block 0 -> row[1].
    # Prefer this narrow path so timestamps and unrelated numeric fields are not
    # mistaken for issue IDs.
    try:
        for row in data[0][6][0]:
            if isinstance(row, list) and len(row) > 1:
                candidate = str(row[1])
                if candidate.isdigit() and len(candidate) >= 6:
                    found.append(candidate)
    except (IndexError, TypeError, KeyError):
        pass
    if found:
        return list(dict.fromkeys(found))

    def walk(value: Any) -> None:
        if isinstance(value, list):
            if len(value) > 1 and isinstance(value[1], (int, str)):
                candidate = str(value[1])
                if candidate.isdigit() and len(candidate) >= 6:
                    found.append(candidate)
            for child in value:
                walk(child)
        elif isinstance(value, dict):
            for key in ("issue_id", "issueId", "id"):
                candidate = value.get(key)
                if isinstance(candidate, (int, str)) and str(candidate).isdigit():
                    found.append(str(candidate))
            for child in value.values():
                walk(child)

    walk(data)
    return list(dict.fromkeys(found))


def fetch_page(session: requests.Session, start_index: int, *, page_size: int, query: str, sort: str, timeout: float) -> list[str]:
    response = session.post(BASE_URL, headers=_headers(), cookies=_cookies(), data=build_body(start_index, page_size=page_size, query=query, sort=sort), timeout=timeout)
    response.raise_for_status()
    return extract_issue_ids(_decode_response(response.text))


def fetch_ids(*, output: Path, page_size: int, max_pages: int, query: str, sort: str, delay: float, timeout: float) -> list[str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    all_ids: list[str] = []
    with requests.Session() as session:
        for page in range(max_pages):
            ids = fetch_page(session, page * page_size, page_size=page_size, query=query, sort=sort, timeout=timeout)
            if not ids:
                break
            all_ids.extend(ids)
            if len(ids) < page_size:
                break
            if delay:
                time.sleep(delay)
    ids = list(dict.fromkeys(all_ids))
    output.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/chrome_issue/phase1/metadata/chromium_issue_ids.txt"))
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--sort", default=DEFAULT_SORT)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not _token():
        parser.error("Set CHROMIUM_XSRF_TOKEN (or XSRF_TOKEN) from a current browser request")
    ids = fetch_ids(output=args.output, page_size=args.page_size, max_pages=args.max_pages, query=args.query, sort=args.sort, delay=args.delay, timeout=args.timeout)
    print(f"Wrote {len(ids)} Chromium issue IDs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
