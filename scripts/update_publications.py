#!/usr/bin/env python3
"""Update the latest publications from a Google Scholar profile.

This script keeps the existing hand-authored page structure and replaces only
publication cards from START_YEAR onward. It is intended to run monthly in
GitHub Actions so newly listed Scholar entries are added without disturbing
older publications.
"""
from __future__ import annotations

import html
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCHOLAR_USER = "4MJdIuwAAAAJ"
START_YEAR = 2024
MAX_PAGES = 3
PAGE_SIZE = 100
PUBLICATIONS_PAGE = Path("publications/index.html")

@dataclass(frozen=True)
class Publication:
    title: str
    authors: str
    venue: str
    year: int


def fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def scholar_pages() -> list[str]:
    pages: list[str] = []
    for cstart in range(0, MAX_PAGES * PAGE_SIZE, PAGE_SIZE):
        url = "https://scholar.google.com/citations?" + urlencode(
            {
                "hl": "en",
                "user": SCHOLAR_USER,
                "view_op": "list_works",
                "sortby": "pubdate",
                "cstart": cstart,
                "pagesize": PAGE_SIZE,
            }
        )
        page = fetch(url)
        pages.append(page)
        if "gsc_a_tr" not in page or "gsc_a_nn" not in page:
            break
    return pages


def parse_publications(pages: list[str]) -> list[Publication]:
    publications: list[Publication] = []
    row_re = re.compile(r'<tr class="gsc_a_tr">(.*?)</tr>', re.S)
    for page in pages:
        for row in row_re.findall(page):
            title_match = re.search(r'class="gsc_a_at"[^>]*>(.*?)</a>', row, re.S)
            author_matches = re.findall(r'<div class="gs_gray">(.*?)</div>', row, re.S)
            year_match = re.search(r'<span class="gsc_a_h gsc_a_hc gs_ibl">(\d{4})</span>', row)
            if not (title_match and len(author_matches) >= 2 and year_match):
                continue
            year = int(year_match.group(1))
            if year < START_YEAR:
                continue
            publications.append(
                Publication(
                    title=clean(title_match.group(1)),
                    authors=clean(author_matches[0]),
                    venue=clean(author_matches[1]),
                    year=year,
                )
            )
    return publications


def format_authors(authors: str) -> str:
    authors = authors.replace("Sui-Seng Tee", "SS Tee")
    authors = authors.replace("Sui Seng Tee", "SS Tee")
    authors = authors.replace("Sui-seng Tee", "SS Tee")
    return html.escape(authors).replace("SS Tee", "<strong>SS Tee</strong>")


def render_publications(publications: list[Publication]) -> str:
    by_year: dict[int, list[Publication]] = defaultdict(list)
    for publication in publications:
        by_year[publication.year].append(publication)

    blocks: list[str] = []
    for year in sorted(by_year, reverse=True):
        blocks.append(f"<h2>{year}</h2>\n")
        for publication in by_year[year]:
            blocks.append(
                '<div class="card">\n'
                '  <div class="pub-title">\n'
                f'    {html.escape(publication.title)}\n'
                '  </div>\n'
                '  <div class="small">\n'
                f'    {format_authors(publication.authors)}<br/>\n'
                f'    <em>{html.escape(publication.venue)}</em>, {publication.year}\n'
                '  </div>\n'
                '</div>\n'
            )
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def replace_latest_section(page: str, replacement: str) -> str:
    pattern = re.compile(r"<h2>\d{4}</h2>\n.*?(?=\n    </main>)", re.S)
    if pattern.search(page):
        return pattern.sub(replacement, page)
    insertion = re.search(r"\n<h1>Publications</h1>\n", page)
    if not insertion:
        raise RuntimeError("Could not find publications heading")
    return page[: insertion.end()] + "\n" + replacement + page[insertion.end() :]


def main() -> int:
    page_path = PUBLICATIONS_PAGE
    page = page_path.read_text()
    publications = parse_publications(scholar_pages())
    if not publications:
        raise RuntimeError("No recent publications found on Google Scholar")
    updated = replace_latest_section(page, render_publications(publications))
    page_path.write_text(updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
