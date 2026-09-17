"""Unit tests for Office document text extraction."""

import io
import zipfile

from backend.integrations.office_extract import (
    extract_text_from_docx,
    extract_text_from_pptx,
    extract_text_from_xlsx,
)


def _minimal_pptx(slide_text: str = "Ignite Ecosystem Enterprise") -> bytes:
    slide = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:txBody><a:p><a:r><a:t>{slide_text}</a:t></a:r></a:p></p:txBody></p:sp>
  </p:spTree></p:cSld>
</p:sld>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        z.writestr("ppt/slides/slide1.xml", slide)
    return buf.getvalue()


def _minimal_docx(paragraph: str = "Documento de prueba") -> bytes:
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p></w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def _minimal_xlsx(cell_text: str = "Planilla Ignite") -> bytes:
    shared = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">
  <si><t>{cell_text}</t></si>
</sst>"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c></row>
  </sheetData>
</worksheet>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def test_extract_text_from_pptx_reads_slide_text():
    text = extract_text_from_pptx(_minimal_pptx("Ignite_Ecosystem_Enterprise"))
    assert "Ignite_Ecosystem_Enterprise" in text
    assert "Slide 1" in text
    assert "name 'zipfile' is not defined" not in text
    assert "[Error parsing PowerPoint" not in text


def test_extract_text_from_docx_reads_paragraphs():
    text = extract_text_from_docx(_minimal_docx("Hola Julian"))
    assert "Hola Julian" in text
    assert "[Error parsing Word" not in text


def test_extract_text_from_xlsx_reads_shared_strings():
    text = extract_text_from_xlsx(_minimal_xlsx("Revenue 2026"))
    assert "Revenue 2026" in text
    assert "[Error parsing Excel" not in text


def test_extract_text_from_pptx_corrupt_bytes_returns_stable_error_string():
    text = extract_text_from_pptx(b"not-a-pptx")
    assert text == (
        "[Error parsing PowerPoint document text: unsupported or corrupt file]"
    )
    # Must not leak exception class/message details to the model/UI.
    assert "BadZipFile" not in text
    assert "zipfile" not in text


def test_extract_text_from_docx_corrupt_bytes_returns_stable_error_string():
    text = extract_text_from_docx(b"not-a-docx")
    assert text == (
        "[Error parsing Word document text: unsupported or corrupt file]"
    )


def test_extract_text_from_xlsx_corrupt_bytes_returns_stable_error_string():
    text = extract_text_from_xlsx(b"not-a-xlsx")
    assert text == (
        "[Error parsing Excel document text: unsupported or corrupt file]"
    )
