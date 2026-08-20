"""Small generic HTML <table> -> list[dict] parser used by the solar-system
builder. Written against BeautifulSoup directly (not pandas.read_html) so we
have full control over multi-row headers and empty cells.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def parse_table_by_selector(html: str, selector: dict) -> list[dict]:
    """selector: kwargs for BeautifulSoup.find (e.g. {'id': 'sat_elem'})."""
    soup = BeautifulSoup(html, "html5lib")
    table = soup.find("table", **selector)
    if table is None:
        return []

    body_rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")
    headers = _flat_headers(table)

    records = []
    for tr in body_rows:
        cells = [_clean(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if not cells:
            continue
        if headers and len(headers) == len(cells):
            records.append(dict(zip(headers, cells)))
        else:
            records.append({f"col_{i}": v for i, v in enumerate(cells)})
    return records


def _flat_headers(table) -> list[str]:
    thead = table.find("thead")
    if thead is None:
        return []
    header_rows = thead.find_all("tr")
    if len(header_rows) == 1:
        return [_clean(th.get_text(" ", strip=True)) for th in header_rows[0].find_all("th")]

    # Two-row header (e.g. phys_par): first row has grouping ths with colspan,
    # second row has the (value, sigma, ref) sub-labels. Expand groups.
    top = header_rows[0].find_all("th")
    sub = header_rows[1].find_all("th") if len(header_rows) > 1 else []
    sub_labels = [_clean(th.get_text(" ", strip=True)) for th in sub]

    flat: list[str] = []
    sub_i = 0
    for th in top:
        colspan = int(th.get("colspan", 1))
        label = _clean(th.get_text(" ", strip=True))
        if colspan == 1:
            flat.append(label)
        else:
            for _ in range(colspan):
                sub_label = sub_labels[sub_i] if sub_i < len(sub_labels) else str(sub_i)
                flat.append(f"{label} {sub_label}".strip())
                sub_i += 1
    return flat
