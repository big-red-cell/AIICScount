#!/usr/bin/env python3
"""Fetch Chromium issue updates and linked attachments by ID or URL."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests

from fetch_ids import DEFAULT_SORT, fetch_page
from fetch_issues import BASE_URL, _cookies, _decode_response, _headers, parse_comments

ISSUE_URL_RE = re.compile(r"/issues?/([0-9]+)")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def issue_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value
    match = ISSUE_URL_RE.search(value)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract Chromium issue ID from {value!r}")


def query_from_value(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if "issues.chromium.org" not in parsed.netloc or not parsed.path.rstrip("/").endswith("/issues"):
        return None
    query = parse_qs(parsed.query).get("q", [])
    return unquote(query[0]) if query else None


def attachment_urls(data: object) -> list[str]:
    found: list[str] = []
    for value in _walk_strings(data):
        for url in URL_RE.findall(value):
            clean = url.rstrip(".,);]")
            parsed = urlparse(clean)
            if "attachment" in clean.lower() or "download" in clean.lower():
                if parsed.scheme in {"http", "https"} and clean not in found:
                    found.append(clean)
    return found


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)


def fetch_one(session: requests.Session, value: str, output_dir: Path, attachment_dir: Path, download: bool, timeout: float) -> dict[str, object]:
    ident = issue_id(value)
    response = session.post(BASE_URL.format(issue_id=ident), headers=_headers(), cookies=_cookies(), data=json.dumps([ident, "ASC", None, None, 2]), timeout=timeout)
    response.raise_for_status()
    payload = _decode_response(response.text)
    comments = parse_comments(payload)
    urls = attachment_urls(payload)
    destination = output_dir / f"{ident}.txt"
    body = "\n\n".join(f"Author: {author}\n{content}" for author, content in comments)
    destination.write_text(f"Issue ID: {ident}\n\n{body}\n", encoding="utf-8")
    downloaded: list[str] = []
    if download:
        target = attachment_dir / ident
        target.mkdir(parents=True, exist_ok=True)
        for index, url in enumerate(urls, start=1):
            item = session.get(url, headers={"User-Agent": _headers()["user-agent"]}, cookies=_cookies(), timeout=timeout)
            item.raise_for_status()
            name = Path(urlparse(url).path).name or f"attachment-{index}"
            path = target / f"{index:03d}-{name}"
            path.write_bytes(item.content)
            downloaded.append(str(path))
    return {"issue_id": ident, "input": value, "comments": len(comments), "attachments": urls, "downloaded": downloaded}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("values", nargs="+", help="Issue IDs, issue URLs, or an issues?q=... tracker URL")
    parser.add_argument("--max-pages", type=int, default=20, help="Pages to read when a tracker query URL is supplied")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--output-dir", type=Path, default=Path("results/chrome_issue/phase1/input"))
    parser.add_argument("--attachment-dir", type=Path, default=Path("results/chrome_issue/phase1/attachments"))
    parser.add_argument("--download-attachments", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not (os.getenv("CHROMIUM_XSRF_TOKEN") or os.getenv("XSRF_TOKEN") or os.getenv("XSRF-TOKEN")):
        parser.error("Set CHROMIUM_XSRF_TOKEN (or XSRF_TOKEN) from a current browser request")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"source": "Chromium Issue Tracker", "issues": [], "failed": {}}
    with requests.Session() as session:
        expanded: list[str] = []
        for value in args.values:
            query = query_from_value(value)
            if query is None:
                expanded.append(value)
                continue
            for page in range(args.max_pages):
                ids = fetch_page(session, page * args.page_size, page_size=args.page_size, query=query, sort=DEFAULT_SORT, timeout=args.timeout)
                expanded.extend(ids)
                if len(ids) < args.page_size:
                    break
        for value in dict.fromkeys(expanded):
            try:
                manifest["issues"].append(fetch_one(session, value, args.output_dir, args.attachment_dir, args.download_attachments, args.timeout))
            except Exception as exc:
                manifest["failed"][value] = str(exc)
                print(f"{value} failed: {exc}")
    manifest_path = args.output_dir.parent / "metadata" / "chromium_issue_fetch_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Fetched {len(manifest['issues'])} issue(s); manifest: {manifest_path}")
    return 0 if not manifest["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
