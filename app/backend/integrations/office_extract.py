"""Pure Office document text extractors (no provider / API dependencies)."""

from __future__ import annotations

import io
import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile

try:
    import openpyxl
except ImportError:
    openpyxl = None

logger = logging.getLogger("office_extract")


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text content from a .docx file bytes using built-in libraries."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as docx:
            xml_content = docx.read("word/document.xml")
            root = ET.fromstring(xml_content)
            namespaces = {
                "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            }

            paragraphs = []
            for p in root.findall(".//w:p", namespaces):
                p_text = "".join(
                    node.text for node in p.findall(".//w:t", namespaces) if node.text
                )
                if p_text:
                    paragraphs.append(p_text)
            return "\n\n".join(paragraphs)
    except Exception as e:
        logger.error("Error parsing .docx file: %s", e, exc_info=True)
        # Stable UX string — never leak raw exception details to the model/UI.
        return "[Error parsing Word document text: unsupported or corrupt file]"


def extract_text_from_xlsx(file_bytes: bytes) -> str:
    """Extract text content from a .xlsx Excel file bytes.

    Tries openpyxl first (handles all cell types, inline strings, merged cells, etc.).
    Falls back to a robust manual XML parser if openpyxl is unavailable.
    """
    # ── Strategy 1: openpyxl (most accurate) ──────────────────────────────────
    if openpyxl is not None:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            output_sheets = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows_text = []
                for row in ws.iter_rows(values_only=True):
                    # Filter out completely empty rows
                    if all(cell is None or str(cell).strip() == "" for cell in row):
                        continue
                    cells = [str(cell) if cell is not None else "" for cell in row]
                    # Strip trailing empty cells from each row
                    while cells and cells[-1] == "":
                        cells.pop()
                    if cells:
                        rows_text.append("\t".join(cells))
                if rows_text:
                    output_sheets.append(f"--- Sheet: {sheet_name} ---\n" + "\n".join(rows_text))
            wb.close()
            result = "\n\n".join(output_sheets)
            if result.strip():
                return result
            # If openpyxl returned empty (e.g. data_only missed something), fall through
        except Exception as opy_err:
            logger.warning("openpyxl failed to parse xlsx, falling back to XML parser: %s", opy_err)

    # ── Strategy 2: Raw XML parser (pure stdlib) ───────────────────────────────
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as xlsx:
            # Parse sharedStrings
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in xlsx.namelist():
                ss_xml = xlsx.read("xl/sharedStrings.xml")
                ss_root = ET.fromstring(ss_xml)
                ns = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in ss_root.findall(".//ns:si", ns):
                    # Concatenate all <t> text (including rich text runs)
                    t_val = "".join(
                        t.text for t in si.findall(".//ns:t", ns) if t.text
                    )
                    shared_strings.append(t_val)

            # Find all sheet XML paths
            sheet_paths = sorted(
                f for f in xlsx.namelist()
                if f.startswith("xl/worksheets/sheet") and f.endswith(".xml")
            )

            # Try to map friendly sheet names via workbook.xml.rels + workbook.xml
            friendly_names: dict[str, str] = {}
            try:
                if "xl/workbook.xml" in xlsx.namelist():
                    wb_xml = xlsx.read("xl/workbook.xml")
                    wb_root = ET.fromstring(wb_xml)
                    wb_ns = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    if "xl/_rels/workbook.xml.rels" in xlsx.namelist():
                        rels_xml = xlsx.read("xl/_rels/workbook.xml.rels")
                        rels_root = ET.fromstring(rels_xml)
                        # Build rid -> target map
                        rid_map = {}
                        for rel in rels_root:
                            rid = rel.get("Id")
                            target = rel.get("Target", "")
                            rid_map[rid] = "xl/" + target.lstrip("/")
                        for sheet_el in wb_root.findall(".//ns:sheet", wb_ns):
                            name = sheet_el.get("name", "")
                            rid = sheet_el.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                            if rid and rid in rid_map:
                                friendly_names[rid_map[rid]] = name
            except Exception:
                pass  # friendly names are best-effort

            ns = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            output_sheets = []
            for sheet_path in sheet_paths:
                display_name = friendly_names.get(sheet_path) or (
                    os.path.basename(sheet_path).replace(".xml", "").capitalize()
                )
                sheet_xml = xlsx.read(sheet_path)
                sheet_root = ET.fromstring(sheet_xml)

                rows: dict[int, str] = {}
                for row_el in sheet_root.findall(".//ns:row", ns):
                    r_idx = row_el.get("r")
                    if not r_idx:
                        continue
                    r_val = int(r_idx)
                    row_cells: list[tuple[int, str]] = []

                    for cell in row_el.findall(".//ns:c", ns):
                        c_ref = cell.get("r", "")
                        t_attr = cell.get("t", "")
                        val = ""

                        if t_attr == "inlineStr":
                            # Inline string — concatenate <is><t> elements
                            is_node = cell.find("ns:is", ns)
                            if is_node is not None:
                                val = "".join(
                                    t.text for t in is_node.findall(".//ns:t", ns) if t.text
                                )
                        else:
                            v_node = cell.find("ns:v", ns)
                            if v_node is not None and v_node.text:
                                val = v_node.text
                                if t_attr == "s":
                                    # Shared string reference
                                    try:
                                        idx = int(val)
                                        if 0 <= idx < len(shared_strings):
                                            val = shared_strings[idx]
                                    except ValueError:
                                        pass
                                elif t_attr == "b":
                                    val = "TRUE" if val == "1" else "FALSE"

                        # Compute column index from ref like "A1", "BC12"
                        col_letters = "".join(ch for ch in c_ref if ch.isalpha())
                        col_idx = 0
                        for ch in col_letters:
                            col_idx = col_idx * 26 + (ord(ch.upper()) - 64)

                        if col_idx > 0:
                            row_cells.append((col_idx, val))

                    if row_cells:
                        row_cells.sort(key=lambda x: x[0])
                        max_col = max(c[0] for c in row_cells)
                        row_list = [""] * max_col
                        for c_idx, val in row_cells:
                            row_list[c_idx - 1] = val
                        # Strip trailing empty cells
                        while row_list and row_list[-1] == "":
                            row_list.pop()
                        if any(v.strip() for v in row_list):
                            rows[r_val] = "\t".join(row_list)

                if rows:
                    sorted_keys = sorted(rows.keys())
                    sheet_text = [rows[r] for r in sorted_keys]
                    output_sheets.append(
                        f"--- Sheet: {display_name} ---\n" + "\n".join(sheet_text)
                    )

            return "\n\n".join(output_sheets)
    except Exception as e:
        logger.error("Error parsing .xlsx file: %s", e, exc_info=True)
        return "[Error parsing Excel document text: unsupported or corrupt file]"


def extract_text_from_pptx(file_bytes: bytes) -> str:
    """Extract text content from a .pptx PowerPoint file bytes using built-in libraries."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as pptx:
            slide_names = [
                f
                for f in pptx.namelist()
                if f.startswith("ppt/slides/slide") and f.endswith(".xml")
            ]

            output_slides = []
            ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

            def _slide_sort_key(x: str) -> int:
                m = re.search(r"slide(\d+)\.xml", x)
                return int(m.group(1)) if m else 999999

            # Sort slides
            try:
                slide_names.sort(key=_slide_sort_key)
            except Exception:
                slide_names.sort()

            for slide_path in slide_names:
                slide_num = re.search(r"slide(\d+)\.xml", slide_path)
                slide_label = (
                    f"Slide {slide_num.group(1)}" if slide_num else slide_path
                )

                slide_xml = pptx.read(slide_path)
                slide_root = ET.fromstring(slide_xml)

                slide_texts = []
                for t in slide_root.findall(".//a:t", ns):
                    if t.text:
                        slide_texts.append(t.text)

                if slide_texts:
                    output_slides.append(
                        f"--- {slide_label} ---\n" + "\n".join(slide_texts)
                    )

            # Notes can carry speaker content when slides are mostly visual.
            notes_names = [
                f
                for f in pptx.namelist()
                if f.startswith("ppt/notesSlides/notesSlide") and f.endswith(".xml")
            ]

            def _notes_sort_key(x: str) -> int:
                m = re.search(r"notesSlide(\d+)\.xml", x)
                return int(m.group(1)) if m else 999999

            try:
                notes_names.sort(key=_notes_sort_key)
            except Exception:
                notes_names.sort()

            for notes_path in notes_names:
                notes_num = re.search(r"notesSlide(\d+)\.xml", notes_path)
                notes_label = (
                    f"Notes {notes_num.group(1)}" if notes_num else notes_path
                )
                notes_xml = pptx.read(notes_path)
                notes_root = ET.fromstring(notes_xml)
                notes_texts = [
                    t.text for t in notes_root.findall(".//a:t", ns) if t.text
                ]
                # Skip the duplicated slide body that PowerPoint often embeds in notes.
                if notes_texts:
                    output_slides.append(
                        f"--- {notes_label} ---\n" + "\n".join(notes_texts)
                    )

            if not output_slides:
                return (
                    "[PowerPoint parsed successfully but no extractable text nodes "
                    "were found. The slides may be image-only or use unsupported shapes.]"
                )
            return "\n\n".join(output_slides)
    except Exception as e:
        logger.error("Error parsing .pptx file: %s", e, exc_info=True)
        return "[Error parsing PowerPoint document text: unsupported or corrupt file]"


# Aliases for backward compatibility and uniform API
extract_docx_text = extract_text_from_docx
extract_xlsx_text = extract_text_from_xlsx
extract_pptx_text = extract_text_from_pptx


def extract_all_office_files(files_dict: dict[str, bytes]) -> dict[str, str]:
    """Extract text from a mapping of filename -> bytes."""
    results: dict[str, str] = {}
    for filename, data in files_dict.items():
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".docx":
            results[filename] = extract_text_from_docx(data)
        elif ext == ".xlsx":
            results[filename] = extract_text_from_xlsx(data)
        elif ext == ".pptx":
            results[filename] = extract_text_from_pptx(data)
    return results
