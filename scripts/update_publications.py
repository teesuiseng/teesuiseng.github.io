#!/usr/bin/env python3
"""Update recent publications from Sui-Seng Tee's public ORCID record."""
from __future__ import annotations

import html
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ORCID_ID = "0000-0002-9891-4622"
ORCID_API = f"https://pub.orcid.org/v3.0/{ORCID_ID}"
START_YEAR = 2024
PUBLICATIONS_PAGE = Path("publications/index.html")
FETCH_ATTEMPTS = 3


class SourceUnavailableError(RuntimeError):
    """Raised when the ORCID public API cannot be reached after retrying."""


@dataclass(frozen=True)
class Publication:
    title: str
    authors: tuple[str, ...]
    venue: str
    year: int
    doi: str = ""


def fetch_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "teesuiseng.github.io publication updater",
        },
    )
    for attempt in range(FETCH_ATTEMPTS):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504}:
                raise
            last_error: OSError = error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error

        if attempt + 1 < FETCH_ATTEMPTS:
            time.sleep(2**attempt)

    raise SourceUnavailableError(
        f"ORCID could not be reached after {FETCH_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def nested_value(data: dict, *keys: str) -> str:
    value: object = data
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return str(value).strip() if value is not None else ""


def external_id(work: dict, id_type: str) -> str:
    if not isinstance(work.get("external-ids"), dict):
        return ""
    for item in work["external-ids"].get("external-id", []):
        if str(item.get("external-id-type", "")).lower() == id_type:
            return str(item.get("external-id-value", "")).strip()
    return ""


def parse_work(work: dict) -> Publication | None:
    try:
        year = int(nested_value(work, "publication-date", "year", "value"))
    except ValueError:
        return None
    title = nested_value(work, "title", "title", "value")
    if year < START_YEAR or not title:
        return None

    contributors = work.get("contributors") or {}
    authors = tuple(
        name
        for contributor in contributors.get("contributor", [])
        if (name := nested_value(contributor, "credit-name", "value"))
    )
    return Publication(
        title=title,
        authors=authors,
        venue=nested_value(work, "journal-title", "value"),
        year=year,
        doi=external_id(work, "doi"),
    )


def orcid_publications() -> list[Publication]:
    works = fetch_json(f"{ORCID_API}/works")
    publications: list[Publication] = []
    seen: set[str] = set()
    for group in works.get("group", []):
        summaries = group.get("work-summary", [])
        if not summaries:
            continue
        summary = summaries[0]
        try:
            year = int(nested_value(summary, "publication-date", "year", "value"))
        except ValueError:
            continue
        put_code = summary.get("put-code")
        if year < START_YEAR or put_code is None:
            continue
        publication = parse_work(fetch_json(f"{ORCID_API}/work/{put_code}"))
        if publication is None:
            continue
        key = publication.doi.lower() or publication.title.casefold()
        if key not in seen:
            seen.add(key)
            publications.append(publication)
    return sorted(publications, key=lambda item: (-item.year, item.title.casefold()))


def format_author(author: str) -> str:
    escaped = html.escape(author)
    if re.search(r"\bSui[ -]Seng Tee\b|\bSS Tee\b", author, re.I):
        return f"<strong>{escaped}</strong>"
    return escaped


def render_publications(publications: list[Publication]) -> str:
    by_year: dict[int, list[Publication]] = defaultdict(list)
    for publication in publications:
        by_year[publication.year].append(publication)

    blocks = ['<div class="publication-years">']
    for year in sorted(by_year, reverse=True):
        count = len(by_year[year])
        blocks.extend(
            [
                '  <section class="publication-year" aria-labelledby="year-' + str(year) + '">',
                '    <div class="year-heading">',
                f'      <h2 id="year-{year}">{year}</h2>',
                f'      <span>{count} publication{"s" if count != 1 else ""}</span>',
                "    </div>",
                '    <div class="publication-list">',
            ]
        )
        for publication in by_year[year]:
            title = html.escape(publication.title)
            if publication.doi:
                doi = html.escape(publication.doi, quote=True)
                title = f'<a href="https://doi.org/{doi}">{title}</a>'
            authors = ", ".join(format_author(author) for author in publication.authors)
            meta = " · ".join(filter(None, [html.escape(publication.venue), str(publication.year)]))
            blocks.extend(
                [
                    '      <article class="publication-card">',
                    f'        <h3>{title}</h3>',
                    *([f'        <p class="publication-authors">{authors}</p>'] if authors else []),
                    f'        <p class="publication-meta">{meta}</p>',
                    "      </article>",
                ]
            )
        blocks.extend(["    </div>", "  </section>"])
    blocks.append("</div>")
    return "\n".join(blocks) + "\n"


def replace_latest_section(page: str, replacement: str) -> str:
    pattern = re.compile(
        r"<!-- publications:start -->.*?<!-- publications:end -->", re.S
    )
    marked = (
        "<!-- publications:start -->\n"
        + replacement
        + "<!-- publications:end -->"
    )
    if pattern.search(page):
        return pattern.sub(marked, page)
    raise RuntimeError("Could not find publication section markers")


def main() -> int:
    page = PUBLICATIONS_PAGE.read_text()
    try:
        publications = orcid_publications()
    except SourceUnavailableError as error:
        print(f"::warning title=ORCID unavailable::{error}", file=sys.stderr)
        return 0
    if not publications:
        raise RuntimeError("No recent publications found in the ORCID record")
    PUBLICATIONS_PAGE.write_text(replace_latest_section(page, render_publications(publications)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
