"""Read a pollster's crosstab workbook (.xlsx) into a benchmark the simulated survey is scored against.

The layout this reads is the standard banner-table export (More in Common's, and most UK
pollsters'): one sheet per question; inside it one block per table (a grid question has one
block per row item). A block is

    <group row>   ,,Gender,,Region,,,…,Segment          (banner groups, each spanning its columns)
    <label row>   <table label>,All,Male,Female,…       (the column labels)
    <answer rows> <option>,0.27,0.31,…                  (column shares, 0-1)
    Weighted N / Unweighted N                          (the bases)

Rows like "Net", "Trust", "Agree", "Heard combined" are the pollster's own roll-ups of the raw
options; they are kept but flagged `derived` so a score never double counts them. Open-text
sheets list one verbatim per row with its weighted share in each column; they are kept as
verbatims with the columns they fall in.

Stdlib only (zipfile + ElementTree): the backend does not ship a spreadsheet library."""
from __future__ import annotations

import re
import zipfile
from typing import Any, Optional
from xml.etree import ElementTree as ET

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_T = "{%s}t" % _NS["m"]

# Roll-up rows a pollster adds on top of the raw answer options.
DERIVED = re.compile(r"^(net\b.*|trust|don'?t trust|agree|disagree|heard combined|any .*|total .*)$", re.I)
BASE_ROWS = {"weighted n": "weighted_n", "unweighted n": "unweighted_n"}


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheets(path: str) -> list[tuple[str, list[list[str]]]]:
    """Every sheet of an .xlsx as (name, rows of cell strings), in workbook order."""
    z = zipfile.ZipFile(path)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(_T)))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = []
    for sh in wb.find("m:sheets", _NS):
        target = rels[sh.get("{%s}id" % _NS["r"])].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        rows: list[list[str]] = []
        for row in ET.fromstring(z.read(target)).iter("{%s}row" % _NS["m"]):
            cells: dict[int, str] = {}
            for c in row.findall("m:c", _NS):
                v, t = c.find("m:v", _NS), c.get("t")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(_T))
                elif v is None:
                    continue
                elif t == "s":
                    val = shared[int(v.text)]
                else:
                    val = v.text or ""
                cells[_col_index(c.get("r"))] = val
            rows.append([cells.get(k, "") for k in range(max(cells) + 1)] if cells else [])
        out.append((sh.get("name"), rows))
    return out


def _num(v: str) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _columns(group_row: list[str], label_row: list[str]) -> list[dict]:
    """Column keys from the banner: 'All', 'Gender: Male', 'Segment: Progressive Activists'."""
    cols, group = [], ""
    for k in range(1, len(label_row)):
        label = (label_row[k] or "").strip()
        if k < len(group_row) and (group_row[k] or "").strip():
            group = group_row[k].strip()
        if not label:
            continue
        g = "" if label == "All" else group
        cols.append({"index": k, "key": f"{g}: {label}" if g else label, "group": g or "All", "label": label})
    return cols


def parse_sheet(name: str, rows: list[list[str]]) -> dict:
    """One sheet → its question text and its tables (or verbatims)."""
    question = ""
    for r in rows[1:4]:
        if r and r[0].strip() and (len(r) < 2 or not r[1].strip()):
            question = r[0].strip()
            break
    tables, verbatims = [], []
    k = 0
    while k < len(rows):
        r = rows[k]
        if len(r) > 1 and r[1].strip() == "All" and r[0].strip():
            cols = _columns(rows[k - 1] if k else [], r)
            label = r[0].strip()
            item = label.split(":", 1)[1].strip() if ":" in label else None
            body, bases = [], {}
            j = k + 1
            while j < len(rows) and rows[j] and rows[j][0].strip() and not (len(rows[j]) > 1 and rows[j][1].strip() == "All"):
                first = rows[j][0].strip()
                if first.lower() == "weight":
                    break
                vals = {c["key"]: _num(rows[j][c["index"]]) if c["index"] < len(rows[j]) else None for c in cols}
                if first.lower() in BASE_ROWS:
                    bases[BASE_ROWS[first.lower()]] = vals
                else:
                    body.append({"label": first, "derived": bool(DERIVED.match(first)), "values": vals})
                j += 1
            # An open-text sheet: many rows, each a verbatim with a tiny share per column
            # (or an "Other (please specify)" sheet, however few rows it has).
            if len(body) > 60 or "specify" in name.lower() or question.lower().startswith("other (please specify"):
                for b in body:
                    cols_in = [key for key, v in b["values"].items() if key != "All" and v]
                    verbatims.append({"text": b["label"], "share": b["values"].get("All"), "columns": cols_in})
            else:
                tables.append({"label": label, "item": item, "columns": [{"key": c["key"], "group": c["group"], "label": c["label"]} for c in cols],
                               "rows": body, **bases})
            k = j
        else:
            k += 1
    return {"sheet": name, "question": question, "tables": tables, "verbatims": verbatims}


def parse_workbook(path: str) -> dict:
    """The whole workbook: its methodology lines (from the contents sheet) and every question."""
    sheets = read_sheets(path)
    method: dict[str, str] = {}
    out = []
    for name, rows in sheets:
        if name.lower().startswith("table of contents"):
            for r in rows:
                if len(r) >= 2 and r[0].strip() and r[1].strip():
                    method[r[0].strip()] = r[1].strip()
            continue
        out.append(parse_sheet(name, rows))
    return {"method": method, "sheets": out}


def table_shares(table: dict, column: str = "All", *, include_derived: bool = False) -> dict[str, float]:
    """{option: share 0-1} for one column of one table."""
    return {r["label"]: r["values"].get(column) for r in table.get("rows") or []
            if (include_derived or not r.get("derived")) and r["values"].get(column) is not None}


def summary(parsed: dict) -> list[dict[str, Any]]:
    return [{"sheet": s["sheet"], "tables": len(s["tables"]), "verbatims": len(s["verbatims"]),
             "columns": len(s["tables"][0]["columns"]) if s["tables"] else 0} for s in parsed["sheets"]]
