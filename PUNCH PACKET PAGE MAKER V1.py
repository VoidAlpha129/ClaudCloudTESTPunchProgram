"""
STRIKER PDF Packet Builder - v8 Final Cover Layout

Purpose:
- Combine selected PDFs, sorted by filename.
- Generate a master cover page at the front.
- Pull STRIKER program numbers from NC Filename / Program Number and add .dat.
- Pull each program's sheet count from Blank Qty.
- Pull part numbers and total quantities from the layout table.
- Show an editable preview of found programs and part totals before building.
- Draw cover-page charts/tables for program sheet counts and final packet counts.
- Dark mode UI.

Minimal install:
    py -m pip install pymupdf

Run:
    py striker_pdf_packet_builder_v8_final_layout.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF is not installed. Run: py -m pip install pymupdf")
    raise

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


# ----------------------------- SETTINGS -----------------------------

PART_RE = re.compile(r"^[A-Z0-9]{2,}(?:-[A-Z0-9]+)+[A-Z]?$", re.IGNORECASE)
INT_RE = re.compile(r"^\d+$")

COLOR_MAP = {
    "Black": (0, 0, 0),
    "Green": (0, 0.55, 0),
    "Red": (0.85, 0, 0),
    "Blue": (0, 0.15, 0.85),
    "Purple": (0.45, 0, 0.75),
    "Hot Pink": (1.0, 0.0, 0.55),
}

DARK_BG = "#1e1e1e"
DARK_PANEL = "#252526"
DARK_ENTRY = "#111111"
DARK_FG = "#e8e8e8"
DARK_MUTED = "#bdbdbd"
DARK_SELECT = "#0e639c"


@dataclass
class FileExtract:
    file_name: str
    program_name: str | None = None
    blank_qty: int = 0
    parts: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ExtractedInfo:
    program_sheets: Dict[str, int]
    part_totals: Dict[str, int]
    total_sheets: int
    file_extracts: List[FileExtract]
    warnings: List[str]


# ----------------------------- SORTING / CLEANUP -----------------------------


def natural_sort_key(path_or_name: str | Path):
    name = Path(path_or_name).name.lower()
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name)]


def clean_program_number(program: str) -> str:
    program = re.sub(r"\s+", " ", program.strip())
    program = program.rstrip(".-_ ")
    return program if program.lower().endswith(".dat") else program + ".dat"


def remove_trailing_nc(stem: str) -> str:
    stem = stem.strip()
    stem = re.sub(r"^\s*0\.\s*", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"-NC$", "", stem, flags=re.IGNORECASE)
    return stem.strip()


def line_list(page: fitz.Page) -> List[str]:
    return [line.strip() for line in page.get_text("text").splitlines() if line.strip()]


# ----------------------------- EXTRACTION -----------------------------


def extract_program_number(doc: fitz.Document, pdf_path: Path) -> str | None:
    """
    Pull the actual program number.

    Most reliable source on your STRIKER sheets is the NC Filename field on page 2.
    This also fixes files where the visible Program Number wraps across two lines, like:
        426-3037 (04,05)-01-
        01
    """
    text_by_page = [page.get_text("text") for page in doc]
    all_text = "\n".join(text_by_page)
    lines = [line.strip() for line in all_text.splitlines() if line.strip()]

    # 1) Best method: NC Filename. It is usually a single clean line.
    # Example: NC Filename: 426-3037 (04,05)-01-01
    m = re.search(r"NC\s+Filename\s*:\s*([^\r\n]+)", all_text, flags=re.IGNORECASE)
    if m:
        value = m.group(1).strip()
        if value:
            return clean_program_number(value)

    # 2) If the label and value are separated strangely, look near NC Filename.
    for i, line in enumerate(lines):
        if re.match(r"NC\s+Filename\s*:?", line, flags=re.IGNORECASE):
            tail = line.split(":", 1)[1].strip() if ":" in line else ""
            if tail:
                return clean_program_number(tail)
            for j in range(i + 1, min(i + 5, len(lines))):
                if looks_like_program_line(lines[j]):
                    return clean_program_number(lines[j])

    # 3) Program Number field. Sometimes wraps, so join the next few lines.
    for i, line in enumerate(lines):
        if re.match(r"Program\s+Number\s*:?", line, flags=re.IGNORECASE):
            chunk = " ".join(lines[i + 1 : i + 6])
            candidate = find_programish_value(chunk)
            if candidate:
                return clean_program_number(candidate)

    # 4) Filename fallback. This is often still right for STRIKER-generated PDFs.
    stem = remove_trailing_nc(pdf_path.stem)
    if looks_like_program_line(stem):
        return clean_program_number(stem)

    return None


def looks_like_program_line(value: str) -> bool:
    value = value.strip()
    return bool(re.search(r"\d{3,}-.+?-\d{1,2}-\d{1,2}$", value))


def find_programish_value(text: str) -> str | None:
    text = re.sub(r"\s+", "", text.strip())
    # Generic enough for: 426-3037(04,05)-01-01 and 426-6016-44-01-01
    m = re.search(r"\d{3,}-[A-Za-z0-9(),]+(?:-[A-Za-z0-9(),]+)*-\d{1,2}-\d{1,2}", text)
    return m.group(0) if m else None


def extract_blank_qty_from_first_page(doc: fitz.Document) -> int:
    """Pull Blank Qty from the first layout page. This is the program sheet count."""
    if doc.page_count == 0:
        return 0

    lines = line_list(doc[0])

    # In parsed STRIKER text, the label block starts with Blank Qty and the values follow.
    # The actual Blank Qty is the last integer before the table header area starts.
    try:
        start = next(i for i, line in enumerate(lines) if line.lower().startswith("blank qty"))
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lower().startswith("hole")), len(lines))
        values: List[int] = []
        for item in lines[start + 1 : end]:
            clean = item.replace(",", "")
            if INT_RE.match(clean):
                values.append(int(clean))
        if values:
            return values[-1]
    except StopIteration:
        pass

    # Coordinate fallback: find the words Blank + Qty, then the integer below/right of that label.
    words = doc[0].get_text("words")
    for idx, w in enumerate(words):
        if w[4].lower() == "blank" and idx + 1 < len(words) and words[idx + 1][4].lower().startswith("qty"):
            label_y = w[1]
            nearby_nums = []
            for nw in words:
                if nw[1] > label_y and nw[1] < label_y + 80:
                    clean = nw[4].replace(",", "")
                    if INT_RE.match(clean):
                        nearby_nums.append((abs(nw[0] - w[0]) + abs(nw[1] - label_y), int(clean)))
            if nearby_nums:
                return sorted(nearby_nums, key=lambda x: x[0])[0][1]

    return 0


def words_on_same_row(words, y: float, tolerance: float = 4.0):
    return [w for w in words if abs(w[1] - y) <= tolerance]


def find_total_qty_x(words) -> float | None:
    """Find the X position for the Total Qty column header."""
    # Look for header words Total and Qty near each other in the table header row.
    candidates = []
    for w in words:
        x0, y0, x1, y1, text, *_ = w
        if text.lower() != "total" or not (350 <= y0 <= 430):
            continue
        row = words_on_same_row(words, y0, tolerance=6)
        has_qty_near = any(rw[4].lower() == "qty" and abs(rw[0] - x0) < 35 for rw in row)
        if has_qty_near:
            candidates.append(x0)
    if candidates:
        # Total Qty is the one to the right of Qty, usually around x=330-380.
        return sorted(candidates)[0]
    return None


def extract_parts_from_first_page(doc: fitz.Document) -> Dict[str, int]:
    """
    Pull part rows from page 1 using PDF word coordinates.

    - Part number comes from the Name column.
    - Quantity comes from the Total Qty column, not the Qty column.
    """
    totals: Dict[str, int] = {}
    if doc.page_count == 0:
        return totals

    page = doc[0]
    words = page.get_text("words")
    if not words:
        return totals

    total_x = find_total_qty_x(words)
    if total_x is None:
        # Typical STRIKER landscape Total Qty X position.
        total_x = 345.0

    for w in words:
        x0, y0, x1, y1, text, *_ = w
        if y0 < 415:
            continue
        if x0 > 190:
            continue
        if not PART_RE.match(text):
            continue

        row = words_on_same_row(words, y0)
        row_ints: List[Tuple[float, int]] = []
        for rw in row:
            rx0, ry0, rx1, ry1, rtext, *_ = rw
            clean = rtext.replace(",", "")
            if INT_RE.match(clean):
                row_ints.append((rx0, int(clean)))

        if not row_ints:
            continue

        _, total_qty = min(row_ints, key=lambda item: abs(item[0] - total_x))
        totals[text] = totals.get(text, 0) + total_qty

    # Text-order fallback for odd PDFs.
    if not totals:
        lines = line_list(page)
        for i, line in enumerate(lines):
            if PART_RE.match(line):
                # Typical order after name: Qty, Total Qty, X Size, Y Size...
                integers = []
                for j in range(i + 1, min(i + 8, len(lines))):
                    clean = lines[j].replace(",", "")
                    if INT_RE.match(clean):
                        integers.append(int(clean))
                if len(integers) >= 2:
                    totals[line] = totals.get(line, 0) + integers[1]
                elif len(integers) == 1:
                    totals[line] = totals.get(line, 0) + integers[0]

    return totals


def looks_like_striker_pdf(path: Path) -> bool:
    try:
        with fitz.open(path) as doc:
            if doc.page_count == 0:
                return False
            sample = "\n".join(doc[i].get_text("text") for i in range(min(2, doc.page_count))).lower()
            return "layout_detail_wusedtools_landscape" in sample or "program number" in sample or "nc filename" in sample
    except Exception:
        return False


def striker_source_paths(pdf_paths: List[Path]) -> List[Path]:
    # Main workflow: files beginning with "0." are STRIKER-generated layout PDFs.
    marked = [p for p in pdf_paths if p.name.strip().lower().startswith("0.")]
    if marked:
        return marked

    # Fallback: if no "0." files are selected, read any selected STRIKER-looking PDFs.
    return [p for p in pdf_paths if looks_like_striker_pdf(p)]


def extract_from_striker_pdfs(pdf_paths: List[Path]) -> ExtractedInfo:
    program_sheets: Dict[str, int] = {}
    part_totals: Dict[str, int] = {}
    total_sheets = 0
    warnings: List[str] = []
    file_extracts: List[FileExtract] = []

    source_paths = striker_source_paths(pdf_paths)
    if not source_paths:
        warnings.append("No STRIKER PDFs found. Files named with '0.' are used first; if none exist, the program looks for STRIKER layout text.")

    for path in source_paths:
        fe = FileExtract(file_name=path.name)
        try:
            doc = fitz.open(path)
        except Exception as exc:
            fe.warnings.append(f"Could not read: {exc}")
            file_extracts.append(fe)
            warnings.append(f"Could not read {path.name}: {exc}")
            continue

        try:
            fe.program_name = extract_program_number(doc, path)
            fe.blank_qty = extract_blank_qty_from_first_page(doc)
            fe.parts = extract_parts_from_first_page(doc)

            if fe.blank_qty <= 0:
                fe.warnings.append("No Blank Qty found; counted as 0 sheets.")
            else:
                total_sheets += fe.blank_qty

            if fe.program_name:
                program_sheets[fe.program_name] = program_sheets.get(fe.program_name, 0) + fe.blank_qty
            else:
                fe.warnings.append("No Program Number / NC Filename found.")

            if fe.parts:
                for part, qty in fe.parts.items():
                    part_totals[part] = part_totals.get(part, 0) + qty
            else:
                fe.warnings.append("No part Total Qty values found.")

        except Exception as exc:
            fe.warnings.append(f"Extraction error: {exc}")
        finally:
            doc.close()

        if fe.warnings:
            for warning in fe.warnings:
                warnings.append(f"{path.name}: {warning}")
        file_extracts.append(fe)

    return ExtractedInfo(
        program_sheets=program_sheets,
        part_totals=part_totals,
        total_sheets=total_sheets,
        file_extracts=file_extracts,
        warnings=warnings,
    )


# ----------------------------- EDITABLE PREVIEW PARSING -----------------------------


def dict_to_lines(data: Dict[str, int], program_mode: bool = False) -> str:
    lines = []
    for key, qty in sorted(data.items(), key=lambda kv: natural_sort_key(kv[0])):
        if program_mode:
            word = "Sheet" if qty == 1 else "Sheets"
            lines.append(f"{key} = {qty} {word}")
        else:
            lines.append(f"{key} = {qty}")
    return "\n".join(lines)


def parse_qty_lines(raw_text: str, program_mode: bool = False) -> Tuple[Dict[str, int], List[str]]:
    """
    Accepts editable lines like:
        426-3037 (04,05)-01-01.dat = 2 Sheets
        00-20-01 = 10
    """
    data: Dict[str, int] = {}
    warnings: List[str] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("PROGRAM NAME") or line.upper().startswith("PART#") or line.upper().startswith("OVERALL"):
            continue

        if "=" in line:
            left, right = line.split("=", 1)
        elif ":" in line:
            left, right = line.split(":", 1)
        else:
            warnings.append(f"Skipped line with no '=': {line}")
            continue

        key = left.strip()
        if program_mode:
            key = clean_program_number(key)
        qty_match = re.search(r"\d+", right.replace(",", ""))
        if not key or not qty_match:
            warnings.append(f"Skipped unreadable line: {line}")
            continue
        data[key] = data.get(key, 0) + int(qty_match.group(0))

    return data, warnings


# ----------------------------- PDF CREATION -----------------------------


def insert_box_text(page: fitz.Page, rect: fitz.Rect, text: str, size: float, color=(0, 0, 0)):
    page.insert_textbox(rect, text, fontsize=size, fontname="helv", color=color, align=fitz.TEXT_ALIGN_LEFT)


def draw_table(
    page: fitz.Page,
    x: float,
    y: float,
    col_widths: List[float],
    headers: List[str],
    rows: List[List[str]],
    title: str,
    row_height: float = 20,
    header_height: float = 22,
    font_size: float = 10,
    title_size: float = 13,
    max_y: float | None = None,
) -> int:
    """
    Draw a clean chart/table and return how many data rows fit.
    Uses only PyMuPDF drawing/text; no extra packages.
    """
    black = (0, 0, 0)
    header_fill = (0.88, 0.88, 0.88)
    alt_fill = (0.96, 0.96, 0.96)

    if max_y is None:
        max_y = page.rect.height - 36

    page.insert_text((x, y), title, fontsize=title_size, fontname="helv", color=black)
    y += 10

    table_width = sum(col_widths)
    header_rect = fitz.Rect(x, y, x + table_width, y + header_height)
    page.draw_rect(header_rect, color=black, fill=header_fill, width=0.8)

    cx = x
    for i, header in enumerate(headers):
        cell = fitz.Rect(cx, y, cx + col_widths[i], y + header_height)
        page.draw_rect(cell, color=black, width=0.6)
        page.insert_text((cell.x0 + 4, cell.y0 + 15), header, fontsize=font_size, fontname="helv", color=black)
        cx += col_widths[i]

    y += header_height
    fit_count = 0
    for row_index, row in enumerate(rows):
        if y + row_height > max_y:
            break
        fill = alt_fill if row_index % 2 else None
        cx = x
        for i, value in enumerate(row):
            cell = fitz.Rect(cx, y, cx + col_widths[i], y + row_height)
            page.draw_rect(cell, color=black, fill=fill, width=0.5)
            align = fitz.TEXT_ALIGN_RIGHT if i == len(row) - 1 else fitz.TEXT_ALIGN_LEFT
            page.insert_text((cell.x1 - 8 - fitz.get_text_length(str(value), fontname="helv", fontsize=font_size), cell.y0 + 14), str(value), fontsize=font_size, fontname="helv", color=black) if align == fitz.TEXT_ALIGN_RIGHT else page.insert_text((cell.x0 + 4, cell.y0 + 14), str(value), fontsize=font_size, fontname="helv", color=black)
            cx += col_widths[i]
        y += row_height
        fit_count += 1

    return fit_count



def _text_width(text: str, size: float) -> float:
    return fitz.get_text_length(str(text), fontname="helv", fontsize=size)


def _fit_text(text: str, max_width: float, start_size: float = 8.5, min_size: float = 6.0) -> float:
    size = start_size
    while size > min_size and _text_width(text, size) > max_width:
        size -= 0.25
    return size


def draw_clean_table(
    page: fitz.Page,
    x: float,
    y: float,
    col_widths: List[float],
    headers: List[str],
    rows: List[List[str]],
    title: str,
    row_height: float = 16,
    header_height: float = 17,
    font_size: float = 8.2,
    title_size: float = 10.5,
    max_y: float | None = None,
) -> int:
    """Compact table with light gray header and thin lines."""
    black = (0, 0, 0)
    light = (0.90, 0.90, 0.90)
    alt = (0.975, 0.975, 0.975)
    if max_y is None:
        max_y = page.rect.height - 28

    table_width = sum(col_widths)
    page.insert_text((x, y), title, fontsize=title_size, fontname="helv", color=black)
    y += 8

    # Header
    cx = x
    for i, header in enumerate(headers):
        rect = fitz.Rect(cx, y, cx + col_widths[i], y + header_height)
        page.draw_rect(rect, color=black, fill=light, width=0.45)
        page.insert_text((rect.x0 + 3, rect.y0 + 12), header, fontsize=font_size, fontname="helv", color=black)
        cx += col_widths[i]
    y += header_height

    fit_count = 0
    for row_index, row in enumerate(rows):
        if y + row_height > max_y:
            break
        cx = x
        fill = alt if row_index % 2 else None
        for i, value in enumerate(row):
            value = str(value)
            rect = fitz.Rect(cx, y, cx + col_widths[i], y + row_height)
            page.draw_rect(rect, color=black, fill=fill, width=0.35)
            if i == len(row) - 1:
                size = _fit_text(value, col_widths[i] - 6, font_size, 6)
                page.insert_text((rect.x1 - 3 - _text_width(value, size), rect.y0 + 11.5), value, fontsize=size, fontname="helv", color=black)
            else:
                size = _fit_text(value, col_widths[i] - 6, font_size, 6)
                page.insert_text((rect.x0 + 3, rect.y0 + 11.5), value, fontsize=size, fontname="helv", color=black)
            cx += col_widths[i]
        y += row_height
        fit_count += 1
    return fit_count



def draw_part_columns(
    page: fitz.Page,
    x: float,
    y: float,
    rows: List[List[str]],
    title: str = "FINAL PACKET COUNTS",
    available_width: float = 720,
    max_y: float | None = None,
    preferred_columns: int | None = None,
    row_height: float = 14.2,
    header_height: float = 15.0,
    font_size: float = 7.5,
    title_size: float = 9.5,
) -> int:
    """
    Draw part counts as true vertical tables/columns.

    Instead of filling across the row first, this fills DOWN the first part table,
    then starts a new part table to the right. This reads more like shop-floor
    pick/count lists and removes the huge blank part-name columns.
    """
    black = (0, 0, 0)
    light = (0.90, 0.90, 0.90)
    alt = (0.975, 0.975, 0.975)
    if max_y is None:
        max_y = page.rect.height - 28

    if not rows:
        rows = [["No part totals found", ""]]

    page.insert_text((x, y), title, fontsize=title_size, fontname="helv", color=black)
    y += 8

    usable_height = max_y - y - header_height
    if usable_height <= row_height:
        return 0

    rows_per_col = max(1, int(usable_height // row_height))
    needed_cols = (len(rows) + rows_per_col - 1) // rows_per_col
    if preferred_columns:
        # Force the requested number of vertical tables when possible.
        # This is intentional so medium part lists become two easy-to-read columns
        # instead of one very tall list.
        needed_cols = min(max(1, preferred_columns), len(rows))
        rows_per_col = (len(rows) + needed_cols - 1) // needed_cols
    else:
        needed_cols = min(4, max(1, needed_cols))
        rows_per_col = (len(rows) + needed_cols - 1) // needed_cols

    qty_w = 28.0
    gap = 14.0
    max_part_text = max(_text_width(str(r[0]), font_size) for r in rows) if rows else 70
    part_w = max(58.0, min(max_part_text + 10.0, 140.0))
    col_w = part_w + qty_w

    # If the natural width does not fit, shrink the gap and part width before dropping columns.
    while needed_cols > 1 and needed_cols * col_w + (needed_cols - 1) * gap > available_width:
        if gap > 6:
            gap -= 2
        elif part_w > 62:
            part_w -= 4
            col_w = part_w + qty_w
        else:
            needed_cols -= 1
            rows_per_col = (len(rows) + needed_cols - 1) // needed_cols

    fit_items = 0
    idx = 0
    for col in range(needed_cols):
        cx = x + col * (col_w + gap)
        cy = y

        # Header for this vertical table.
        r1 = fitz.Rect(cx, cy, cx + part_w, cy + header_height)
        r2 = fitz.Rect(cx + part_w, cy, cx + col_w, cy + header_height)
        page.draw_rect(r1, color=black, fill=light, width=0.4)
        page.draw_rect(r2, color=black, fill=light, width=0.4)
        page.insert_text((r1.x0 + 3, r1.y0 + 10.8), "PART #", fontsize=font_size, fontname="helv", color=black)
        page.insert_text((r2.x0 + 3, r2.y0 + 10.8), "QTY", fontsize=font_size, fontname="helv", color=black)
        cy += header_height

        row_index = 0
        while row_index < rows_per_col and idx < len(rows):
            if cy + row_height > max_y:
                return fit_items
            fill = alt if row_index % 2 else None
            part, qty = str(rows[idx][0]), str(rows[idx][1])
            r1 = fitz.Rect(cx, cy, cx + part_w, cy + row_height)
            r2 = fitz.Rect(cx + part_w, cy, cx + col_w, cy + row_height)
            page.draw_rect(r1, color=black, fill=fill, width=0.3)
            page.draw_rect(r2, color=black, fill=fill, width=0.3)
            ps = _fit_text(part, part_w - 6, font_size, 5.8)
            qs = _fit_text(qty, qty_w - 5, font_size, 5.8)
            page.insert_text((r1.x0 + 3, r1.y0 + 10.4), part, fontsize=ps, fontname="helv", color=black)
            page.insert_text((r2.x1 - 3 - _text_width(qty, qs), r2.y0 + 10.4), qty, fontsize=qs, fontname="helv", color=black)
            cy += row_height
            row_index += 1
            idx += 1
            fit_items += 1

    return fit_items

def make_cover_pdf(
    page_width: float,
    page_height: float,
    user_text: str,
    job_text_color: Tuple[float, float, float],
    program_sheets: Dict[str, int],
    part_totals: Dict[str, int],
    total_sheets: int,
) -> fitz.Document:
    """
    v7 side-by-side compact cover layout:
    - PUNCH PACKET SUMMARY title.
    - PUNCH PROGRAM label at top right in black to match the title.
    - STARTED / FINISHED use the selected cover-text color.
    - Sheet counts and final packet counts start at the same height and run downward.
    - Overall total sheets sits in the bottom-right corner.
    """
    cover = fitz.open()
    black = (0, 0, 0)
    gray = (0.55, 0.55, 0.55)
    margin = 34

    program_rows = [[p, str(q)] for p, q in sorted(program_sheets.items(), key=lambda kv: natural_sort_key(kv[0]))]
    part_rows = [[p, str(q)] for p, q in sorted(part_totals.items(), key=lambda kv: natural_sort_key(kv[0]))]

    if not program_rows:
        program_rows = [["No program numbers found", ""]]
    if not part_rows:
        part_rows = [["No part totals found", ""]]

    page = cover.new_page(width=page_width, height=page_height)

    # Clean title bar.
    page.insert_text((margin, 23), "PUNCH PACKET SUMMARY", fontsize=12.5, fontname="helv", color=black)
    punch_label = "PUNCH PROGRAM"
    punch_size = 12.5
    page.insert_text((page_width - margin - _text_width(punch_label, punch_size), 23), punch_label, fontsize=punch_size, fontname="helv", color=black)
    page.draw_line((margin, 31), (page_width - margin, 31), color=gray, width=0.4)

    # Left free-text area. This is intentionally narrow so the count tables get vertical room.
    left_w = min(260, page_width * 0.33)
    info_lines = [line.rstrip() for line in user_text.strip().splitlines()]
    while info_lines and not info_lines[-1].strip():
        info_lines.pop()
    info = "\n".join(info_lines)
    info_rect = fitz.Rect(margin, 48, margin + left_w + 18, 282)
    insert_box_text(page, info_rect, info, size=17.0, color=job_text_color)

    # Started/Finished match the selected cover text color.
    sf_y = 330
    page.insert_text((margin, sf_y), "STARTED:", fontsize=17.0, fontname="helv", color=job_text_color)
    page.insert_text((margin, sf_y + 34), "FINISHED:", fontsize=17.0, fontname="helv", color=job_text_color)

    # Overall total sheets anchored bottom-right.
    bottom_y = page_height - margin - 44
    total_block_w = 180
    total_x = page_width - margin - total_block_w
    page.draw_line((total_x, bottom_y - 10), (page_width - margin, bottom_y - 10), color=gray, width=0.35)
    page.insert_text((total_x, bottom_y + 4), "OVERALL TOTAL SHEETS", fontsize=8.8, fontname="helv", color=black)
    total_text = str(total_sheets)
    page.insert_text((page_width - margin - _text_width(total_text, 22), bottom_y + 28), total_text, fontsize=22, fontname="helv", color=black)

    # Side-by-side tables: sheet counts on the left, final packet counts on the right.
    table_y = 50
    table_bottom = page_height - margin
    gap = 24

    prog_font = 7.2
    sheet_w = 38.0
    max_prog_text = max(_text_width(str(r[0]), prog_font) for r in program_rows)
    prog_name_w = max(135.0, min(max_prog_text + 10.0, 235.0))
    sheet_table_w = prog_name_w + sheet_w

    sheet_x = margin + left_w + 28
    # Keep sheet table from eating too much of the part area.
    max_sheet_w = max(150.0, page_width * 0.34)
    if sheet_table_w > max_sheet_w:
        prog_name_w = max_sheet_w - sheet_w
        sheet_table_w = max_sheet_w

    fit_programs = draw_clean_table(
        page,
        sheet_x,
        table_y,
        [prog_name_w, sheet_w],
        ["PROGRAM", "SHEET"],
        program_rows,
        "SHEET COUNTS",
        row_height=13.4,
        header_height=14.5,
        font_size=prog_font,
        title_size=9.4,
        max_y=table_bottom,
    )

    part_x = sheet_x + sheet_table_w + gap
    part_available = page_width - part_x - margin

    # If the selected first PDF is smaller than expected or the program names are very long,
    # shift tables left a bit and reclaim space for the parts.
    if part_available < 185:
        sheet_x = margin + left_w + 12
        max_sheet_w = max(145.0, page_width * 0.30)
        if sheet_table_w > max_sheet_w:
            prog_name_w = max_sheet_w - sheet_w
            sheet_table_w = max_sheet_w
        # Redraw on a fresh page to avoid ghosting from the first placement attempt.
        cover.delete_page(-1)
        page = cover.new_page(width=page_width, height=page_height)
        page.insert_text((margin, 23), "PUNCH PACKET SUMMARY", fontsize=12.5, fontname="helv", color=black)
        page.insert_text((page_width - margin - _text_width(punch_label, punch_size), 23), punch_label, fontsize=punch_size, fontname="helv", color=black)
        page.draw_line((margin, 31), (page_width - margin, 31), color=gray, width=0.4)
        insert_box_text(page, info_rect, info, size=17.0, color=job_text_color)
        page.insert_text((margin, sf_y), "STARTED:", fontsize=17.0, fontname="helv", color=job_text_color)
        page.insert_text((margin, sf_y + 34), "FINISHED:", fontsize=17.0, fontname="helv", color=job_text_color)
        page.draw_line((total_x, bottom_y - 10), (page_width - margin, bottom_y - 10), color=gray, width=0.35)
        page.insert_text((total_x, bottom_y + 4), "OVERALL TOTAL SHEETS", fontsize=8.8, fontname="helv", color=black)
        total_text = str(total_sheets)
        page.insert_text((page_width - margin - _text_width(total_text, 22), bottom_y + 28), total_text, fontsize=22, fontname="helv", color=black)
        fit_programs = draw_clean_table(
            page, sheet_x, table_y, [prog_name_w, sheet_w], ["PROGRAM", "SHEET"], program_rows, "SHEET COUNTS",
            row_height=13.4, header_height=14.5, font_size=prog_font, title_size=9.4, max_y=table_bottom
        )
        part_x = sheet_x + sheet_table_w + 18
        part_available = page_width - part_x - margin

    # Part counts use compact vertical columns inside the right-side area.
    fit_parts = draw_part_columns(
        page,
        part_x,
        table_y,
        part_rows,
        title="FINAL PACKET COUNTS",
        available_width=part_available,
        max_y=table_bottom,
        preferred_columns=(2 if len(part_rows) > 8 else None),
        row_height=13.4,
        header_height=14.5,
        font_size=7.2,
        title_size=9.4,
    )

    # Continuation pages: keep them clean and simple.
    remaining_parts = part_rows[fit_parts:]
    remaining_programs = program_rows[fit_programs:]
    while remaining_parts or remaining_programs:
        page = cover.new_page(width=page_width, height=page_height)
        page.insert_text((margin, 23), "PUNCH PACKET SUMMARY", fontsize=12.5, fontname="helv", color=black)
        page.insert_text((page_width - margin - _text_width(punch_label, punch_size), 23), punch_label, fontsize=punch_size, fontname="helv", color=black)
        page.draw_line((margin, 31), (page_width - margin, 31), color=gray, width=0.4)

        used_programs = 0
        if remaining_programs:
            used_programs = draw_clean_table(
                page,
                margin,
                table_y,
                [prog_name_w, sheet_w],
                ["PROGRAM", "SHEET"],
                remaining_programs,
                "SHEET COUNTS",
                row_height=13.4,
                header_height=14.5,
                font_size=prog_font,
                title_size=9.4,
                max_y=table_bottom,
            )
        remaining_programs = remaining_programs[used_programs:]

        used_parts = 0
        if remaining_parts:
            px = margin + (sheet_table_w + gap if used_programs else 0)
            pavail = page_width - px - margin
            used_parts = draw_part_columns(
                page,
                px,
                table_y,
                remaining_parts,
                title="FINAL PACKET COUNTS",
                available_width=pavail,
                max_y=table_bottom,
                preferred_columns=(3 if pavail > 380 and len(remaining_parts) > 16 else (2 if len(remaining_parts) > 8 else None)),
                row_height=13.4,
                header_height=14.5,
                font_size=7.2,
                title_size=9.4,
            )
        remaining_parts = remaining_parts[used_parts:]

        if used_parts <= 0 and used_programs <= 0:
            break

    return cover

def build_packet(
    pdf_paths: List[Path],
    output_path: Path,
    user_text: str,
    job_color_name: str,
    program_sheets: Dict[str, int],
    part_totals: Dict[str, int],
) -> None:
    if not pdf_paths:
        raise ValueError("No PDFs selected.")

    pdf_paths = sorted(pdf_paths, key=natural_sort_key)
    total_sheets = sum(program_sheets.values())

    first_doc = fitz.open(pdf_paths[0])
    page_rect = first_doc[0].rect
    first_doc.close()

    cover = make_cover_pdf(
        page_rect.width,
        page_rect.height,
        user_text,
        COLOR_MAP.get(job_color_name, (0, 0, 0)),
        program_sheets,
        part_totals,
        total_sheets,
    )

    out = fitz.open()
    out.insert_pdf(cover)
    cover.close()

    for pdf_path in pdf_paths:
        src = fitz.open(pdf_path)
        out.insert_pdf(src)
        src.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(output_path, garbage=4, deflate=True)
    out.close()


# ----------------------------- GUI -----------------------------


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STRIKER PDF Packet Builder v8 - Final Cover Layout")
        self.geometry("1120x820")
        self.minsize(980, 700)
        self.pdf_paths: List[Path] = []
        self.latest_info: ExtractedInfo | None = None
        self.configure_dark_mode()
        self.create_widgets()

    def configure_dark_mode(self):
        self.configure(bg=DARK_BG)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=DARK_BG)
        style.configure("Panel.TFrame", background=DARK_PANEL)
        style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
        style.configure("Muted.TLabel", background=DARK_BG, foreground=DARK_MUTED)
        style.configure("TButton", background=DARK_PANEL, foreground=DARK_FG, padding=6)
        style.map("TButton", background=[("active", "#333333")])
        style.configure("TEntry", fieldbackground=DARK_ENTRY, foreground=DARK_FG, insertcolor=DARK_FG)
        style.configure("TCombobox", fieldbackground=DARK_ENTRY, foreground=DARK_FG, background=DARK_PANEL)
        style.configure("TLabelframe", background=DARK_BG, foreground=DARK_FG)
        style.configure("TLabelframe.Label", background=DARK_BG, foreground=DARK_FG)

    def dark_text(self, widget: tk.Text):
        widget.configure(
            bg=DARK_ENTRY,
            fg=DARK_FG,
            insertbackground=DARK_FG,
            selectbackground=DARK_SELECT,
            selectforeground="white",
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#3c3c3c",
            wrap="none",
        )

    def create_widgets(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Button(top, text="Select PDFs", command=self.select_pdfs).pack(side="left", padx=4)
        ttk.Button(top, text="Select Folder", command=self.select_folder).pack(side="left", padx=4)
        ttk.Button(top, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(top, text="Move Up", command=lambda: self.move_selected(-1)).pack(side="left", padx=4)
        ttk.Button(top, text="Move Down", command=lambda: self.move_selected(1)).pack(side="left", padx=4)
        ttk.Button(top, text="Sort by Name", command=self.sort_by_name).pack(side="left", padx=4)
        ttk.Button(top, text="Scan / Refresh Found Data", command=self.scan_found_data).pack(side="left", padx=12)

        file_frame = ttk.Frame(self, padding=(10, 0, 10, 8))
        file_frame.pack(fill="both", expand=False)
        ttk.Label(file_frame, text="PDF order to append after the generated cover page:").pack(anchor="w")
        self.listbox = tk.Listbox(
            file_frame,
            selectmode=tk.EXTENDED,
            height=8,
            bg=DARK_ENTRY,
            fg=DARK_FG,
            selectbackground=DARK_SELECT,
            selectforeground="white",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#3c3c3c",
        )
        self.listbox.pack(fill="both", expand=True)

        main = ttk.Frame(self, padding=(10, 0, 10, 10))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        ttk.Label(left, text="Large JOB/TICKET cover text. Line breaks stay as typed:").pack(anchor="w")
        self.job_textbox = tk.Text(left, height=8)
        self.dark_text(self.job_textbox)
        self.job_textbox.insert("1.0", "JOB#\nTICKET#\nGAUGE/MAT\nJOB NAME")
        self.job_textbox.pack(fill="both", expand=True)

        color_row = ttk.Frame(left)
        color_row.pack(fill="x", pady=(8, 0))
        ttk.Label(color_row, text="JOB/TICKET text color:").pack(side="left")
        self.color_var = tk.StringVar(value="Black")
        self.color_combo = ttk.Combobox(
            color_row,
            textvariable=self.color_var,
            values=list(COLOR_MAP.keys()),
            state="readonly",
            width=14,
        )
        self.color_combo.pack(side="left", padx=8)

        ttk.Label(right, text="Extraction notes / per-file preview:").pack(anchor="w")
        self.notes_box = tk.Text(right, height=10)
        self.dark_text(self.notes_box)
        self.notes_box.pack(fill="both", expand=True)

        preview = ttk.Frame(self, padding=(10, 0, 10, 10))
        preview.pack(fill="both", expand=True)
        preview.columnconfigure(0, weight=1)
        preview.columnconfigure(1, weight=1)
        preview.rowconfigure(1, weight=1)

        ttk.Label(preview, text="Editable PROGRAMS / SHEET COUNTS:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(preview, text="Editable PARTS / FINAL PACKET COUNTS:").grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.programs_box = tk.Text(preview, height=14)
        self.dark_text(self.programs_box)
        self.programs_box.grid(row=1, column=0, sticky="nsew", padx=(0, 8))

        self.parts_box = tk.Text(preview, height=14)
        self.dark_text(self.parts_box)
        self.parts_box.grid(row=1, column=1, sticky="nsew", padx=(8, 0))

        output_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        output_frame.pack(fill="x")
        ttk.Label(output_frame, text="Output PDF:").pack(side="left")
        self.output_var = tk.StringVar(value=str(Path.home() / "Desktop" / "Combined_NC_Gens_Master.pdf"))
        ttk.Entry(output_frame, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(output_frame, text="Browse", command=self.choose_output).pack(side="left")

        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Build Master PDF From Editable Preview", command=self.build).pack(side="left")
        self.status_var = tk.StringVar(value="Ready - select PDFs, then click Scan / Refresh Found Data")
        ttk.Label(bottom, textvariable=self.status_var, style="Muted.TLabel").pack(side="left", padx=10)

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.pdf_paths:
            self.listbox.insert(tk.END, str(p))

    def select_pdfs(self):
        files = filedialog.askopenfilenames(title="Select PDFs", filetypes=[("PDF files", "*.pdf")])
        if files:
            self.pdf_paths = [Path(f) for f in files]
            self.sort_by_name()
            self.scan_found_data()

    def select_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing PDFs")
        if folder:
            folder_path = Path(folder)
            self.pdf_paths = [p for p in folder_path.glob("*.pdf") if p.is_file()]
            # Avoid accidentally re-including previous generated packet outputs.
            self.pdf_paths = [p for p in self.pdf_paths if "master" not in p.name.lower()]
            self.sort_by_name()
            self.output_var.set(str(folder_path / "Combined_NC_Gens_Master.pdf"))
            self.scan_found_data()

    def remove_selected(self):
        selected = set(self.listbox.curselection())
        self.pdf_paths = [p for i, p in enumerate(self.pdf_paths) if i not in selected]
        self.refresh_list()

    def move_selected(self, direction: int):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        if direction < 0:
            for i in sel:
                if i > 0:
                    self.pdf_paths[i - 1], self.pdf_paths[i] = self.pdf_paths[i], self.pdf_paths[i - 1]
        else:
            for i in reversed(sel):
                if i < len(self.pdf_paths) - 1:
                    self.pdf_paths[i + 1], self.pdf_paths[i] = self.pdf_paths[i], self.pdf_paths[i + 1]
        self.refresh_list()
        for i in [x + direction for x in sel if 0 <= x + direction < len(self.pdf_paths)]:
            self.listbox.selection_set(i)

    def sort_by_name(self):
        self.pdf_paths = sorted(self.pdf_paths, key=natural_sort_key)
        self.refresh_list()

    def choose_output(self):
        file = filedialog.asksaveasfilename(
            title="Save master PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile="Combined_NC_Gens_Master.pdf",
        )
        if file:
            self.output_var.set(file)

    def scan_found_data(self):
        if not self.pdf_paths:
            messagebox.showerror("No PDFs", "Select PDFs or a folder first.")
            return
        try:
            info = extract_from_striker_pdfs(self.pdf_paths)
            self.latest_info = info

            self.programs_box.delete("1.0", tk.END)
            self.programs_box.insert("1.0", dict_to_lines(info.program_sheets, program_mode=True))

            self.parts_box.delete("1.0", tk.END)
            self.parts_box.insert("1.0", dict_to_lines(info.part_totals, program_mode=False))

            notes = []
            notes.append(f"STRIKER source files scanned: {len(info.file_extracts)}")
            notes.append(f"Overall total sheets found: {info.total_sheets}")
            notes.append("")
            for fe in info.file_extracts:
                notes.append(f"FILE: {fe.file_name}")
                notes.append(f"  Program: {fe.program_name or 'NOT FOUND'}")
                notes.append(f"  Blank Qty / Sheets: {fe.blank_qty}")
                if fe.parts:
                    notes.append("  Parts:")
                    for part, qty in sorted(fe.parts.items(), key=lambda kv: natural_sort_key(kv[0])):
                        notes.append(f"    {part} = {qty}")
                else:
                    notes.append("  Parts: NOT FOUND")
                for warning in fe.warnings:
                    notes.append(f"  WARNING: {warning}")
                notes.append("")
            if info.warnings:
                notes.append("WARNINGS:")
                notes.extend(info.warnings)

            self.notes_box.delete("1.0", tk.END)
            self.notes_box.insert("1.0", "\n".join(notes))
            self.status_var.set("Scan complete - edit the preview boxes if needed, then build")
        except Exception as exc:
            self.status_var.set("Scan error")
            messagebox.showerror("Scan error", str(exc))

    def build(self):
        try:
            if not self.pdf_paths:
                messagebox.showerror("No PDFs", "Select PDFs or a folder first.")
                return

            programs, program_warnings = parse_qty_lines(self.programs_box.get("1.0", tk.END), program_mode=True)
            parts, part_warnings = parse_qty_lines(self.parts_box.get("1.0", tk.END), program_mode=False)

            if not programs:
                if not messagebox.askyesno("No programs", "No program lines were found in the editable preview. Build anyway?"):
                    return
            if not parts:
                if not messagebox.askyesno("No parts", "No part lines were found in the editable preview. Build anyway?"):
                    return

            output_path = Path(self.output_var.get()).expanduser()
            user_text = self.job_textbox.get("1.0", tk.END).strip()
            color_name = self.color_var.get()

            build_packet(self.pdf_paths, output_path, user_text, color_name, programs, parts)

            total_sheets = sum(programs.values())
            msg = f"Master PDF created:\n{output_path}\n\n"
            msg += f"Programs on cover: {len(programs)}\n"
            msg += f"Overall total sheets: {total_sheets}\n"
            msg += f"Part totals on cover: {len(parts)}"
            warnings = program_warnings + part_warnings
            if warnings:
                msg += "\n\nEditable preview warnings:\n" + "\n".join(warnings[:10])
            self.status_var.set("Done")
            messagebox.showinfo("Done", msg)
        except Exception as exc:
            self.status_var.set("Build error")
            messagebox.showerror("Build error", str(exc))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
