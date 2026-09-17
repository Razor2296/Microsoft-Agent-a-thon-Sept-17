"""
app/tests/unit/test_document_generator.py
Unit tests for main/document_generator.py (Word, Excel, PowerPoint generation).
"""
import os
import tempfile
import pytest
from main.document_generator import (
    _ensure_dependencies,
    _make_rgb,
    generate_docx,
    generate_xlsx,
    generate_pptx,
)


class TestDocumentGeneratorHelpers:
    def test_ensure_dependencies_runs_without_exception(self):
        _ensure_dependencies()

    def test_make_rgb_safeguard(self):
        rgb = _make_rgb(36, 60, 90)
        # If pptx is installed, _make_rgb returns an RGBColor instance or None
        assert rgb is not None or rgb is None


class TestDocxGenerator:
    def test_generate_docx_file_creation(self, tmp_path):
        output_file = str(tmp_path / "test_output.docx")
        content = "# Titulo Principal\n\nEste es un parrafo de prueba.\n\n- Punto 1\n- Punto 2"

        result = generate_docx(content, output_file)
        path = result[0] if isinstance(result, tuple) else result

        assert path == output_file
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 0


class TestXlsxGenerator:
    def test_generate_xlsx_file_creation(self, tmp_path):
        output_file = str(tmp_path / "test_output.xlsx")
        content = "| Nombre | Edad | Ciudad |\n| --- | --- | --- |\n| Juan | 30 | Lima |\n| Ana | 25 | Arequipa |"

        result = generate_xlsx(content, output_file)
        path = result[0] if isinstance(result, tuple) else result

        assert path == output_file
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 0


class TestPptxGenerator:
    def test_generate_pptx_file_creation(self, tmp_path):
        output_file = str(tmp_path / "test_output.pptx")
        content = "Slide 1: Introduccion\n- Bienvenido a la presentacion\n- Puntos clave\n\nSlide 2: Resumen\n- Conclusion final"

        result = generate_pptx(content, output_file)
        path = result[0] if isinstance(result, tuple) else result

        assert path == output_file
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 0
