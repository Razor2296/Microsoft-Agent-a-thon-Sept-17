# Import all libraries from main.libraries as requested
# pyrefly: ignore [missing-import]
# pyrefly: ignore [circular-import]
import os
import sys
import re
import subprocess
import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import docx
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
except ImportError:
    docx = None
    Inches = None
    Pt = None
    RGBColor = None
    WD_ALIGN_PARAGRAPH = None
    OxmlElement = None
    qn = None

# NumPy 2.0+ compatibility shim for openpyxl / dependencies expecting NumPy 1.x types
try:
    import numpy as _np
    _type_mapping = {
        'short': getattr(_np, 'int16', int),
        'ushort': getattr(_np, 'uint16', int),
        'intc': getattr(_np, 'int32', int),
        'uintc': getattr(_np, 'uint32', int),
        'int_': getattr(_np, 'int64', int),
        'uint': getattr(_np, 'uint64', int),
        'longlong': getattr(_np, 'int64', int),
        'ulonglong': getattr(_np, 'uint64', int),
        'half': getattr(_np, 'float16', float),
        'single': getattr(_np, 'float32', float),
        'double': getattr(_np, 'float64', float),
        'longdouble': getattr(_np, 'longdouble', getattr(_np, 'float64', float)),
        'bool_': getattr(_np, 'bool_', bool),
    }
    for _name, _typ in _type_mapping.items():
        if not hasattr(_np, _name):
            setattr(_np, _name, _typ)
except ImportError:
    pass

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None
    Font = None
    PatternFill = None
    Alignment = None
    Border = None
    Side = None
    get_column_letter = None

try:
    import pptx
    from pptx.util import Inches as PptInches, Pt as PptPt, Pt as PtFont
    from pptx.dml.color import RGBColor as PptRGBColor
    from pptx.enum.text import PP_ALIGN
except ImportError:
    pptx = None
    PptInches = None
    PptPt = None
    PtFont = None
    PptRGBColor = None
    PP_ALIGN = None

def _make_rgb(r, g, b):
    if PptRGBColor is not None:
        try:
            return PptRGBColor(r, g, b)
        except Exception:
            return None
    return None

# Maximum bullets rendered per slide before creating a continuation slide
_MAX_BULLETS_PER_SLIDE = 6

# Design colors for presentations
BG_COLOR     = _make_rgb(248, 249, 250)   # Soft off-white background
TITLE_COLOR  = _make_rgb(36, 60, 90)       # Dark blue headings
BODY_COLOR   = _make_rgb(80, 80, 80)       # Deep charcoal body text
ACCENT_COLOR = _make_rgb(79, 129, 189)    # Steel blue accents

# Ensure required libraries are imported, with graceful auto-installation if missing
def _ensure_dependencies():
    missing = []
    if docx is None:
        missing.append("python-docx")
    if openpyxl is None:
        missing.append("openpyxl")
    if pptx is None:
        missing.append("python-pptx")
        
    if missing:
        logger.info(f"Installing missing document libraries: {missing}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
            
            # Reload main.libraries to bind the newly installed packages
            importlib.reload(sys.modules['main.libraries'])
            
            # Re-import all symbols from main.libraries into document_generator's namespace
            lib_mod = sys.modules['main.libraries']
            for name in dir(lib_mod):
                if not name.startswith('_'):
                    globals()[name] = getattr(lib_mod, name)
                    
        except Exception as e:
            logger.error(f"Error auto-installing libraries: {e}")

# Run dependency check and ensure libraries are fully loaded
_ensure_dependencies()

# ----------------- COMMON FORMATTING HELPERS -----------------
def _add_styled_runs(p, text):
    """Appends styled runs to an existing paragraph, parsing bold, italic, and bold-italic markdown tags."""
    # Matches: ***bold/italic*** or **bold** or *italic*
    tokens = re.split(r'(\*\*\*.*?\*\*\*|\*\*.*?\*\*|\*.*?\*)', text)
    
    # Apply styles to tokens
    for token in tokens:
        if not token:
            continue
        if token.startswith('***') and token.endswith('***'):
            run = p.add_run(token[3:-3])
            run.bold = True
            run.italic = True
        elif token.startswith('**') and token.endswith('**'):
            run = p.add_run(token[2:-2])
            run.bold = True
        elif token.startswith('*') and token.endswith('*'):
            run = p.add_run(token[1:-1])
            run.italic = True
        else:
            p.add_run(token)
    return p

# ----------------- DOCX GENERATOR -----------------
# Function to add styled paragraph to Word document
def _add_styled_paragraph(doc, text, style_name=None, is_bullet=False):
    """Adds a paragraph to the Word document, parsing bold and italic markdown tags."""
    if is_bullet:
        p = doc.add_paragraph(style='List Bullet')
    else:
        p = doc.add_paragraph()
    _add_styled_runs(p, text)
    return p

# Function to set cell background color
def _set_cell_background(cell, hex_color):
    """Sets background color of a Word table cell."""
    if OxmlElement is None or qn is None:
        return
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)

# Function to generate DOCX document from markdown-like text
def generate_docx(content, filepath):
    """Generates a professional DOCX document from markdown-like text."""
    if docx is None or Inches is None or RGBColor is None:
        logger.error("python-docx is not installed or available.")
        raise RuntimeError("python-docx is not installed or available.")
    doc = docx.Document()
    
    # Page setup - 1 inch margins
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(1)
        s.bottom_margin = Inches(1)
        s.left_margin = Inches(1)
        s.right_margin = Inches(1)

    # Split lines
    lines = content.split('\n')
    in_table = False
    table_lines = []

    def flush_table(target_doc):
        nonlocal in_table, table_lines
        if not table_lines or target_doc is None:
            return
        
        # Parse table rows
        rows_data = []
        for line in table_lines:
            # Clean and split cell contents
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2:
                # Remove empty first/last elements if line started/ended with |
                if parts[0] == '':
                    parts.pop(0)
                if parts and parts[-1] == '':
                    parts.pop()
                rows_data.append(parts)
        
        # Filter out separator row (e.g. |---|---|)
        filtered_rows = []
        for r in rows_data:
            if all(re.match(r'^[-:]+$', cell) for cell in r):
                continue
            filtered_rows.append(r)
            
        if filtered_rows:
            num_cols = max(len(r) for r in filtered_rows)
            table = target_doc.add_table(rows=len(filtered_rows), cols=num_cols)
            table.style = 'Table Grid'
            
            for row_idx, r_data in enumerate(filtered_rows):
                row = table.rows[row_idx]
                is_header = (row_idx == 0)
                
                # Style and fill header and data cells
                for col_idx, val in enumerate(r_data):
                    if col_idx < len(row.cells):
                        cell = row.cells[col_idx]
                        p = cell.paragraphs[0]
                        p.text = ""  # Clear default text
                        _add_styled_runs(p, val)
                        
                        # Style headers
                        if is_header:
                            _set_cell_background(cell, "365F91") # Steel Blue
                            if WD_ALIGN_PARAGRAPH is not None:
                                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            for run in p.runs:
                                run.bold = True
                                run.font.color.rgb = RGBColor(255, 255, 255) # White text
                        else:
                            # Make numbers align to right, text left
                            if WD_ALIGN_PARAGRAPH is not None:
                                if re.match(r'^\$?\d+[\d.,]*%?$', val):
                                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                                else:
                                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        
        table_lines = []
        in_table = False

    i = 0
    last_was_empty = False
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Check if table
        if line.startswith('|'):
            in_table = True
            table_lines.append(line)
            i += 1
            continue
        elif in_table:
            # End of table
            flush_table(doc)
            
        # Headers
        if line.startswith('### '):
            p = doc.add_heading(level=3)
            _add_styled_runs(p, line[4:])
            if p.runs:
                for run in p.runs:
                    run.font.color.rgb = RGBColor(79, 129, 189)
            last_was_empty = False
        elif line.startswith('## '):
            p = doc.add_heading(level=2)
            _add_styled_runs(p, line[3:])
            if p.runs:
                for run in p.runs:
                    run.font.color.rgb = RGBColor(54, 95, 145)
            last_was_empty = False
        elif line.startswith('# '):
            p = doc.add_heading(level=1)
            _add_styled_runs(p, line[2:])
            if p.runs:
                for run in p.runs:
                    run.font.color.rgb = RGBColor(36, 60, 90)
            last_was_empty = False
        # Bullet list
        elif line.startswith('- ') or line.startswith('* '):
            _add_styled_paragraph(doc, line[2:], is_bullet=True)
            last_was_empty = False
        # Numbered list (e.g. 1. Item)
        elif re.match(r'^(\d+)\.\s+(.*)$', line):
            num_match = re.match(r'^(\d+)\.\s+(.*)$', line)
            if num_match is not None:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.25)
                run_num = p.add_run(f"{num_match.group(1)}. ")
                run_num.bold = True
                _add_styled_runs(p, num_match.group(2))
                last_was_empty = False
        # Regular paragraph
        elif line:
            _add_styled_paragraph(doc, line)
            last_was_empty = False
        else:
            if not last_was_empty:
                doc.add_paragraph() # Spacing
                last_was_empty = True
            
        i += 1
        
    if in_table:
        flush_table(doc)
        
    doc.save(filepath)
    return filepath

# ----------------- EXCEL GENERATOR -----------------
# Function to parse numeric value from string
def _parse_numeric_value(val):
    """Tries to parse a string into a number (int or float) and returns (parsed_number, format_code)."""
    if val is None:
        return None, None
    if isinstance(val, (int, float)):
        return val, None
    cleaned = str(val).strip()
    if not cleaned:
        return None, None
        
    # Check percentage
    is_percent = False
    if cleaned.endswith('%'):
        is_percent = True
        cleaned = cleaned[:-1].strip()
        
    # Check currency symbols (e.g., $, -$ or - $)
    is_currency = False
    if cleaned.startswith('$'):
        is_currency = True
        cleaned = cleaned[1:].strip()
    elif cleaned.startswith('-$'):
        is_currency = True
        cleaned = '-' + cleaned[2:].strip()
    elif cleaned.startswith('- $'):
        is_currency = True
        cleaned = '-' + cleaned[3:].strip()
        
    # Remove thousands separator commas
    cleaned_num = cleaned.replace(',', '')
    
    # Check if format matches a standard decimal or integer number
    if re.match(r'^-?\d+\.?\d*$', cleaned_num):
        try:
            if '.' in cleaned_num:
                num_val = float(cleaned_num)
            else:
                num_val = int(cleaned_num)
                
            if is_percent:
                # In Excel, percentages are stored as decimals and formatted as %
                return num_val / 100.0, '0.0%'
            elif is_currency:
                return num_val, '"$"#,##0.00'
            return num_val, None
        except ValueError:
            pass
            
    return None, None

# Function to clean sheet name
def clean_sheet_name(name):
    if not name:
        return "Sheet"
    # Remove #, Hoja X:, Sheet X:, etc.
    cleaned = re.sub(r'^[#\s]+', '', str(name))
    cleaned = re.sub(r'^(hoja|sheet)\s*\d+\s*:\s*', '', cleaned, flags=re.IGNORECASE).strip()
    # Excel sheet names cannot contain characters: \ / ? * : [ ]
    for char in ['\\', '/', '?', '*', ':', '[', ']']:
        cleaned = cleaned.replace(char, '_')
    cleaned = cleaned[:30].strip()
    if not cleaned:
        cleaned = "Sheet"
    return cleaned

# Function to generate XLSX document from markdown-like text
def generate_xlsx(content, filepath):
    """Generates an Excel spreadsheet, preserving both text paragraphs and formatting tables sequentially.
    
    Supports:
      - Multi-sheet generation: H1/H2 headings create new worksheet tabs
      - Numeric detection: currency ($), percentages (%), thousands separators
      - Styled headers (blue fill, white bold text) and auto-fit column widths
    """
    if (
        openpyxl is None
        or Font is None
        or PatternFill is None
        or Alignment is None
        or Border is None
        or Side is None
        or get_column_letter is None
    ):
        logger.error("openpyxl or its styles are not installed or available.")
        raise RuntimeError("openpyxl library is not available.")
    wb = openpyxl.Workbook()
    ws = wb.active
    if ws is None:
        ws = wb.create_sheet(title="Data Analysis")
    else:
        ws.title = "Data Analysis"

    # Enable grid lines using the stable sheet_view API
    if hasattr(ws, "sheet_view") and ws.sheet_view is not None:
        ws.sheet_view.showGridLines = True
    
    # Styles
    font_title = Font(name='Calibri', size=16, bold=True, color='243C5A')
    font_subtitle = Font(name='Calibri', size=13, bold=True, color='365F91')
    font_header = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    font_body = Font(name='Calibri', size=11)
    fill_header = PatternFill(start_color='365F91', end_color='365F91', fill_type='solid')
    align_center = Alignment(horizontal='center', vertical='center')
    align_left = Alignment(horizontal='left', vertical='center')
    align_right = Alignment(horizontal='right', vertical='center')
    
    thin_border = Border(
        left=Side(style='thin', color='BFBFBF'),
        right=Side(style='thin', color='BFBFBF'),
        top=Side(style='thin', color='BFBFBF'),
        bottom=Side(style='thin', color='BFBFBF')
    )
    
    lines = content.split('\n')
    row_idx = 1
    in_table = False
    table_lines = []
    is_default_sheet_empty = True
    
    def flush_xlsx_table(sheet):
        nonlocal row_idx, in_table, table_lines
        if not table_lines or sheet is None:
            return
            
        parsed_rows = []
        for line in table_lines:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2:
                if parts[0] == '':
                    parts.pop(0)
                if parts and parts[-1] == '':
                    parts.pop()
                parsed_rows.append(parts)
                
        # Filter out separator
        filtered_rows = []
        for r in parsed_rows:
            if all(re.match(r'^[-:]+$', cell) for cell in r):
                continue
            filtered_rows.append(r)
            
        for r_idx, row_data in enumerate(filtered_rows):
            sheet.row_dimensions[row_idx].height = 24 if r_idx == 0 else 20
            for c_idx, val in enumerate(row_data):
                cell = sheet.cell(row=row_idx, column=c_idx + 1)
                
                # Check for numerical conversion
                num_val, num_format = _parse_numeric_value(val)
                if num_val is not None:
                    cell.value = num_val
                    cell.alignment = align_right
                    if num_format:
                        cell.number_format = num_format
                else:
                    cell.value = val
                    cell.alignment = align_center if r_idx == 0 else align_left
                    
                # Apply styles
                if r_idx == 0:
                    cell.font = font_header
                    cell.fill = fill_header
                    cell.border = thin_border
                else:
                    cell.font = font_body
                    cell.border = thin_border
                    
            row_idx += 1
            
        row_idx += 1 # Add one blank row spacing after the table
        table_lines = []
        in_table = False

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if line.startswith('|'):
            in_table = True
            table_lines.append(line)
            is_default_sheet_empty = False
        else:
            if in_table:
                flush_xlsx_table(ws)
                
            if line:
                # Ordinary text paragraph or header
                if line.startswith('#'):
                    # Heading level (count # at start)
                    h_level = len(line) - len(line.lstrip('#'))
                    h_text = line.lstrip('#').strip()
                    
                    # Clean the sheet title
                    cleaned_title = clean_sheet_name(line)
                    
                    # We only create a new sheet for main headings (level 1 or 2)
                    if h_level <= 2:
                        if is_default_sheet_empty:
                            ws.title = cleaned_title
                            is_default_sheet_empty = False
                        else:
                            if cleaned_title in wb.sheetnames:
                                ws = wb[cleaned_title]
                            else:
                                ws = wb.create_sheet(title=cleaned_title)
                            # Use stable sheet_view API (see note in generate_xlsx header)
                            if hasattr(ws, "sheet_view") and ws.sheet_view is not None:
                                ws.sheet_view.showGridLines = True
                            row_idx = 1
                            is_default_sheet_empty = True
                    
                    cell = ws.cell(row=row_idx, column=1, value=h_text)
                    cell.font = font_title if h_level == 1 else font_subtitle
                    ws.row_dimensions[row_idx].height = 28
                else:
                    cell = ws.cell(row=row_idx, column=1, value=line)
                    cell.font = font_body
                    ws.row_dimensions[row_idx].height = 20
                    is_default_sheet_empty = False
                row_idx += 1
            else:
                # Empty line, add a tiny bit of vertical spacing
                ws.row_dimensions[row_idx].height = 10
                row_idx += 1
        i += 1
        
    if in_table:
        flush_xlsx_table(ws)
        
    # Auto-fit columns for all sheets in workbook
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = 0
            if col and len(col) > 0 and col[0].column is not None:
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    if cell.value:
                        max_len = max(max_len, len(str(cell.value)))
                sheet.column_dimensions[col_letter].width = max(max_len + 3, 12)
        
    wb.save(filepath)
    return filepath

# ----------------- POWERPOINT GENERATOR -----------------
# Function to clean slide titles
def clean_title(title_text):
    """Cleans slide titles, removing draft-like prefixes like 'Slide X:'."""
    if not title_text:
        return "Presentation"
    return re.sub(r'^(slide|diapositiva)\s*\d+\s*:\s*', '', str(title_text), flags=re.IGNORECASE).strip()

# Function to generate PPTX document from markdown-like text
def generate_pptx(content, filepath):
    """Generates a professional PowerPoint presentation based on content hierarchy. """
    if pptx is None or PtFont is None or PptRGBColor is None:
        logger.error("python-pptx is not installed or available.")
        raise RuntimeError("python-pptx is not installed or available.")
    prs = pptx.Presentation()
    
    # Helper: set slide background to a solid fill color
    def set_background(slide):
        background = slide.background
        fill = background.fill
        fill.solid()
        if BG_COLOR is not None:
            fill.fore_color.rgb = BG_COLOR

    # --- Parse content into slide data objects ---
    slides_data: list[dict[str, Any]] = []
    current_title: str = "Presentation"
    current_bullets: list[dict[str, Any]] = []
    
    lines = content.split('\n')
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
            
        # Slide boundaries: main headers (# and ## only; ### becomes bold bullet)
        if line_str.startswith('# ') or line_str.startswith('## '):
            header_text = re.sub(r'^#+\s*', '', line_str)
            # Flush the previous slide if it has real content
            if current_title != "Presentation" or current_bullets:
                slides_data.append({"title": current_title, "bullets": current_bullets})
            current_title = header_text
            current_bullets = []
        else:
            # Check for header-based bullets: ### -> level 0 bold, #### -> level 1, ##### -> level 2
            if line_str.startswith('### '):
                bullet_text = line_str.replace('### ', '').strip()
                current_bullets.append({"text": f"**{bullet_text}**", "level": 0})
            elif line_str.startswith('#### '):
                bullet_text = line_str.replace('#### ', '').strip()
                current_bullets.append({"text": bullet_text, "level": 1})
            elif line_str.startswith('##### '):
                bullet_text = line_str.replace('##### ', '').strip()
                current_bullets.append({"text": bullet_text, "level": 2})
            else:
                # Check space-based indentation for bullets
                leading_spaces = len(line) - len(line.lstrip(' '))
                level = 0
                if leading_spaces >= 4:
                    level = 2
                elif leading_spaces >= 2:
                    level = 1
                
                bullet_text = re.sub(r'^[-*]\s*', '', line_str)
                current_bullets.append({"text": bullet_text, "level": level})
            
    if current_title != "Presentation" or current_bullets:
        slides_data.append({"title": current_title, "bullets": current_bullets})
        
    # Fallback: if parsing produced nothing, summarise the raw content
    if not slides_data:
        slides_data.append({
            "title": "Document Summary",
            "bullets": [{"text": line.strip(), "level": 0} for line in lines if line.strip()][:8]
        })

    # --- Slide 1: Cover / Title Slide ---
    title_slide_layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(title_slide_layout)
    set_background(slide)
    
    title_ph    = slide.shapes.title
    subtitle_ph = slide.placeholders[1]
    
    title_ph.text = clean_title(slides_data[0]["title"])
    title_ph.text_frame.paragraphs[0].font.size  = PtFont(44)
    title_ph.text_frame.paragraphs[0].font.bold  = True
    if TITLE_COLOR is not None:
        title_ph.text_frame.paragraphs[0].font.color.rgb = TITLE_COLOR

    # Subtitle: show intro bullets as preview, or a default generated-by line
    intro_bullets = slides_data[0].get("bullets", [])
    if intro_bullets:
        preview_lines = []
        for b in intro_bullets[:4]:
            if isinstance(b, dict):
                preview_lines.append(f"• {b['text']}")
            else:
                preview_lines.append(f"• {b}")
        subtitle_ph.text = "\n".join(preview_lines)
    else:
        subtitle_ph.text = "Generated by Ignite Chat"
        subtitle_ph.text_frame.paragraphs[0].font.size  = PtFont(16)
        if ACCENT_COLOR is not None:
            subtitle_ph.text_frame.paragraphs[0].font.color.rgb = ACCENT_COLOR

    # Style all paragraphs in the subtitle placeholder
    for para in subtitle_ph.text_frame.paragraphs:
        para.font.size  = PtFont(16)
        if ACCENT_COLOR is not None:
            para.font.color.rgb = ACCENT_COLOR

    # --- Slides 2+: Content Slides ---    
    content_slides = slides_data[1:] if len(slides_data) > 1 else slides_data
    bullet_slide_layout = prs.slide_layouts[1]

    # For each slide_info in content_slides
    for slide_info in content_slides:
        all_bullets   = slide_info["bullets"]
        slide_title   = clean_title(slide_info["title"])

        # Paginate: split bullets into chunks of _MAX_BULLETS_PER_SLIDE
        # and create a continuation slide for each extra chunk instead of
        # silently dropping bullets that exceed the limit.
        bullet_chunks = [
            all_bullets[i : i + _MAX_BULLETS_PER_SLIDE]
            for i in range(0, max(len(all_bullets), 1), _MAX_BULLETS_PER_SLIDE)
        ]

        for chunk_idx, chunk in enumerate(bullet_chunks):
            slide = prs.slides.add_slide(bullet_slide_layout)
            set_background(slide)

            # Continuation slides get a "(cont.)" suffix so the reader knows
            # the content belongs to the same topic
            chunk_title = slide_title if chunk_idx == 0 else f"{slide_title} (cont. {chunk_idx + 1})"

            # --- Title placeholder ---
            title_shape = slide.shapes.title
            title_shape.text = chunk_title
            title_shape.text_frame.paragraphs[0].font.size  = PtFont(32)
            title_shape.text_frame.paragraphs[0].font.bold  = True
            if TITLE_COLOR is not None:
                title_shape.text_frame.paragraphs[0].font.color.rgb = TITLE_COLOR

            # --- Body / Bullets placeholder ---
            body_shape = slide.placeholders[1]
            tf = body_shape.text_frame
            tf.clear()

            for b_idx, bullet in enumerate(chunk):
                p = tf.add_paragraph() if b_idx > 0 else tf.paragraphs[0]
                
                bullet_text = ""
                bullet_level = 0
                if isinstance(bullet, dict):
                    bullet_text = bullet["text"]
                    bullet_level = bullet["level"]
                else:
                    bullet_text = bullet
                    bullet_level = 0

                p.level       = bullet_level
                p.space_after = PtFont(12)

                # Simple inline bold parser (**text**) for bullet runs
                tokens = re.split(r'(\*\*.*?\*\*)', bullet_text)
                for token in tokens:
                    if not token:
                        continue
                    run = p.add_run()
                    if token.startswith('**') and token.endswith('**'):
                        run.text       = token[2:-2]
                        run.font.bold  = True
                    else:
                        run.text = token
                    run.font.size       = PtFont(16)
                    if BODY_COLOR is not None:
                        run.font.color.rgb  = BODY_COLOR

    prs.save(filepath)
    return filepath