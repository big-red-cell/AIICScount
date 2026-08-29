#!/usr/bin/env python3
"""Fetch public Ubuntu Launchpad bug content and linked attachments."""
from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

BUG_RE = re.compile(r"/(?:ubuntu|source/[^/]+)/\+bug/([0-9]+)")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def bug_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value
    match = BUG_RE.search(urlparse(value).path)
    if match:
        return match.group(1)
    match = re.search(r"(?:bug[ /:+])([0-9]{5,})", value, re.I)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract Launchpad bug ID from {value!r}")


def fetch_one(session: requests.Session, value: str, output_dir: Path, attachment_dir: Path, download: bool, timeout: float) -> dict[str, object]:
    ident = bug_id(value)
    url = f"https://bugs.launchpad.net/ubuntu/+bug/{ident}"
    response = session.get(url, timeout=timeout, headers={"User-Agent": "aiic-three-stage-pipeline/0.1"})
    response.raise_for_status()
    parser = _PageParser()
    parser.feed(response.text)
    text = "\n".join(parser.parts)
    urls = []
    for href in parser.links:
        absolute = urljoin(response.url, href)
        lower = absolute.lower()
        if "attachment" in lower or "/+download/" in lower or "/+file/" in lower:
            if absolute not in urls:
                urls.append(absolute)
    destination = output_dir / f"{ident}.txt"
    destination.write_text(f"Launchpad Bug: {ident}\nURL: {response.url}\n\n{text}\n", encoding="utf-8")
    downloaded: list[str] = []
    if download:
        target = attachment_dir / ident
        target.mkdir(parents=True, exist_ok=True)
        for index, attachment_url in enumerate(urls, start=1):
            item = session.get(attachment_url, timeout=timeout, headers={"User-Agent": "aiic-three-stage-pipeline/0.1"})
            item.raise_for_status()
            name = Path(urlparse(attachment_url).path).name or f"attachment-{index}"
            path = target / f"{index:03d}-{name}"
            path.write_bytes(item.content)
            downloaded.append(str(path))
    return {"bug_id": ident, "input": value, "url": response.url, "attachments": urls, "downloaded": downloaded}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("values", nargs="+", help="Launchpad bug IDs or URLs")
    parser.add_argument("--output-dir", type=Path, default=Path("results/ubuntu_issue/phase1/input"))
    parser.add_argument("--attachment-dir", type=Path, default=Path("results/ubuntu_issue/phase1/attachments"))
    parser.add_argument("--download-attachments", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"source": "Launchpad", "issues": [], "failed": {}}
    with requests.Session() as session:
        for value in args.values:
            try:
                manifest["issues"].append(fetch_one(session, value, args.output_dir, args.attachment_dir, args.download_attachments, args.timeout))
            except Exception as exc:
                manifest["failed"][value] = str(exc)
                print(f"{value} failed: {exc}")
    manifest_path = args.output_dir.parent / "metadata" / "ubuntu_issue_fetch_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Fetched {len(manifest['issues'])} issue(s); manifest: {manifest_path}")
    return 0 if not manifest["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
