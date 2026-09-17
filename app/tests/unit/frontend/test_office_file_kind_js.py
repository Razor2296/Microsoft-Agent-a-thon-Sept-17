"""Smoke-check Office brand kind classification used by frontend cards.

The real classifier lives in app/frontend/js/files.js (getOfficeFileKind).
This Python mirror keeps the brand mapping covered in CI without a browser.
"""


def get_office_file_kind(name: str, mime: str = "") -> str | None:
    name = (name or "").lower()
    mime = (mime or "").lower()
    if (
        name.endswith(".xlsx")
        or name.endswith(".xls")
        or name.endswith(".csv")
        or "sheet" in mime
        or "excel" in mime
        or "csv" in mime
    ):
        return "excel"
    if (
        name.endswith(".pptx")
        or name.endswith(".ppt")
        or "presentation" in mime
        or "powerpoint" in mime
    ):
        return "powerpoint"
    if (
        name.endswith(".docx")
        or name.endswith(".doc")
        or "wordprocessingml" in mime
        or "msword" in mime
        or ("word" in mime and "powerpoint" not in mime)
    ):
        return "word"
    return None


def test_office_kinds_match_brand_targets():
    assert get_office_file_kind("Documento.docx") == "word"
    assert get_office_file_kind("Hoja.xlsx") == "excel"
    assert get_office_file_kind("Presentacion.pptx") == "powerpoint"
    assert get_office_file_kind("notes.pdf") is None


def test_office_kinds_from_mime():
    assert (
        get_office_file_kind(
            "a.bin",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        == "word"
    )
    assert (
        get_office_file_kind(
            "a.bin",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        == "excel"
    )
    assert (
        get_office_file_kind(
            "a.bin",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        == "powerpoint"
    )
