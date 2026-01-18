#!/usr/bin/env python3
"""
Generate a professional PDF from CZFlux_Python_Scripting_Guide.md

Requires: pip install reportlab pygments markdown
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, Flowable, Preformatted
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfgen import canvas
from reportlab.lib import colors
import re
from datetime import datetime
from pathlib import Path


# Colors
NAVY = HexColor('#0a1628')
BLUE = HexColor('#3b82f6')
LIGHT_BLUE = HexColor('#60a5fa')
CODE_BG = HexColor('#1e293b')
CODE_BORDER = HexColor('#334155')
GREEN = HexColor('#22c55e')
YELLOW = HexColor('#fbbf24')
RED = HexColor('#ef4444')
GRAY = HexColor('#94a3b8')
LIGHT_GRAY = HexColor('#e2e8f0')


class CodeBlock(Flowable):
    """A styled code block with syntax highlighting"""

    def __init__(self, code, width=6.5*inch):
        Flowable.__init__(self)
        self.code = code
        self.width = width
        self.padding = 12

        # Calculate height based on lines
        lines = code.split('\n')
        self.line_height = 12
        self.height = len(lines) * self.line_height + self.padding * 2

    def draw(self):
        # Background
        self.canv.setFillColor(CODE_BG)
        self.canv.setStrokeColor(CODE_BORDER)
        self.canv.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)

        # Code text
        self.canv.setFillColor(LIGHT_GRAY)
        self.canv.setFont('Courier', 9)

        lines = self.code.split('\n')
        y = self.height - self.padding - 9

        for line in lines:
            # Simple syntax highlighting
            colored_line = self.highlight_line(line)
            self.canv.drawString(self.padding, y, line)
            y -= self.line_height

    def highlight_line(self, line):
        # Basic highlighting - could be expanded
        return line


class HorizontalRule(Flowable):
    """A horizontal divider line"""

    def __init__(self, width=6.5*inch):
        Flowable.__init__(self)
        self.width = width
        self.height = 20

    def draw(self):
        self.canv.setStrokeColor(HexColor('#334155'))
        self.canv.setLineWidth(1)
        self.canv.line(0, 10, self.width, 10)


def create_styles():
    """Create custom paragraph styles"""
    styles = getSampleStyleSheet()

    # Title style
    styles.add(ParagraphStyle(
        name='DocTitle',
        parent=styles['Title'],
        fontSize=28,
        textColor=NAVY,
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))

    # Subtitle
    styles.add(ParagraphStyle(
        name='Subtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=GRAY,
        spaceAfter=30,
        alignment=TA_CENTER
    ))

    # Section heading (##)
    styles.add(ParagraphStyle(
        name='SectionHeading',
        parent=styles['Heading2'],
        fontSize=18,
        textColor=NAVY,
        spaceBefore=24,
        spaceAfter=12,
        fontName='Helvetica-Bold',
        borderPadding=(0, 0, 4, 0),
        borderWidth=0,
        borderColor=BLUE
    ))

    # Subsection heading (###)
    styles.add(ParagraphStyle(
        name='SubsectionHeading',
        parent=styles['Heading3'],
        fontSize=13,
        textColor=HexColor('#1e3a5f'),
        spaceBefore=16,
        spaceAfter=8,
        fontName='Helvetica-Bold'
    ))

    # Body text
    styles.add(ParagraphStyle(
        name='DocBody',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#334155'),
        spaceAfter=8,
        alignment=TA_JUSTIFY,
        leading=14
    ))

    # Bullet list
    styles.add(ParagraphStyle(
        name='BulletItem',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#334155'),
        leftIndent=20,
        spaceAfter=4,
        bulletIndent=8,
        leading=14
    ))

    # Numbered list
    styles.add(ParagraphStyle(
        name='NumberedItem',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#334155'),
        leftIndent=20,
        spaceAfter=4,
        leading=14
    ))

    # Inline code
    styles.add(ParagraphStyle(
        name='InlineCode',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Courier',
        textColor=HexColor('#0ea5e9'),
        backColor=HexColor('#f1f5f9')
    ))

    # Table header
    styles.add(ParagraphStyle(
        name='TableHeader',
        parent=styles['Normal'],
        fontSize=9,
        textColor=white,
        fontName='Helvetica-Bold',
        alignment=TA_LEFT
    ))

    # Table cell
    styles.add(ParagraphStyle(
        name='TableCell',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#334155'),
        leading=12
    ))

    return styles


def parse_markdown(md_content, styles):
    """Parse markdown content and return flowables"""
    flowables = []
    lines = md_content.split('\n')

    i = 0
    in_code_block = False
    code_buffer = []

    while i < len(lines):
        line = lines[i]

        # Code block handling
        if line.startswith('```'):
            if in_code_block:
                # End code block
                code_text = '\n'.join(code_buffer)
                flowables.append(Spacer(1, 6))
                flowables.append(CodeBlock(code_text))
                flowables.append(Spacer(1, 6))
                code_buffer = []
                in_code_block = False
            else:
                # Start code block
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            code_buffer.append(line)
            i += 1
            continue

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # Horizontal rule
        if line.strip() == '---':
            flowables.append(HorizontalRule())
            i += 1
            continue

        # Main title
        if line.startswith('# ') and not line.startswith('## '):
            text = line[2:].strip()
            flowables.append(Paragraph(text, styles['DocTitle']))
            i += 1
            continue

        # Section heading
        if line.startswith('## '):
            text = line[3:].strip()
            flowables.append(Spacer(1, 12))
            flowables.append(Paragraph(text, styles['SectionHeading']))
            i += 1
            continue

        # Subsection heading
        if line.startswith('### '):
            text = line[4:].strip()
            flowables.append(Paragraph(text, styles['SubsectionHeading']))
            i += 1
            continue

        # Bullet list
        if line.strip().startswith('- '):
            text = line.strip()[2:]
            text = format_inline(text)
            flowables.append(Paragraph(f"<bullet>&bull;</bullet> {text}", styles['BulletItem']))
            i += 1
            continue

        # Numbered list
        match = re.match(r'^(\d+)\.\s+(.+)$', line.strip())
        if match:
            num, text = match.groups()
            text = format_inline(text)
            flowables.append(Paragraph(f"{num}. {text}", styles['NumberedItem']))
            i += 1
            continue

        # Table
        if line.strip().startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i])
                i += 1

            if table_lines:
                table = parse_table(table_lines, styles)
                if table:
                    flowables.append(Spacer(1, 8))
                    flowables.append(table)
                    flowables.append(Spacer(1, 8))
            continue

        # Regular paragraph
        text = format_inline(line.strip())
        if text:
            flowables.append(Paragraph(text, styles['DocBody']))

        i += 1

    return flowables


def format_inline(text):
    """Format inline markdown elements"""
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

    # Inline code - use blue color
    text = re.sub(r'`([^`]+)`', r'<font face="Courier" color="#0ea5e9">\1</font>', text)

    # Links (just show text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    return text


def parse_table(table_lines, styles):
    """Parse markdown table and return a Table flowable"""
    if len(table_lines) < 2:
        return None

    # Parse header
    header = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]

    # Skip separator line
    # Parse data rows
    data_rows = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        if cells:
            data_rows.append(cells)

    if not header or not data_rows:
        return None

    # Create table data
    table_data = [header] + data_rows

    # Format cells
    formatted_data = []
    for row_idx, row in enumerate(table_data):
        formatted_row = []
        for cell in row:
            cell_text = format_inline(cell)
            if row_idx == 0:
                formatted_row.append(Paragraph(cell_text, styles['TableHeader']))
            else:
                formatted_row.append(Paragraph(cell_text, styles['TableCell']))
        formatted_data.append(formatted_row)

    # Calculate column widths
    num_cols = len(header)
    col_width = 6.5 * inch / num_cols

    table = Table(formatted_data, colWidths=[col_width] * num_cols)

    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), BLUE),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),

        # Body
        ('BACKGROUND', (0, 1), (-1, -1), white),
        ('TEXTCOLOR', (0, 1), (-1, -1), HexColor('#334155')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),

        # Alternating rows
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8fafc')]),

        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#cbd5e1')),

        # Alignment
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    return table


def add_header_footer(canvas, doc):
    """Add header and footer to each page"""
    canvas.saveState()

    # Header
    canvas.setFillColor(HexColor('#f8fafc'))
    canvas.rect(0, letter[1] - 40, letter[0], 40, fill=1, stroke=0)

    canvas.setFillColor(BLUE)
    canvas.setFont('Helvetica-Bold', 10)
    canvas.drawString(inch, letter[1] - 26, "CZFlux Python Scripting Guide")

    # Footer
    canvas.setFillColor(HexColor('#f8fafc'))
    canvas.rect(0, 0, letter[0], 35, fill=1, stroke=0)

    canvas.setFillColor(GRAY)
    canvas.setFont('Helvetica', 8)
    canvas.drawString(inch, 15, f"Generated: {datetime.now().strftime('%Y-%m-%d')}")
    canvas.drawRightString(letter[0] - inch, 15, f"Page {doc.page}")

    canvas.restoreState()


def generate_pdf(md_path, pdf_path):
    """Generate PDF from markdown file"""

    # Read markdown
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # Create document
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )

    # Create styles
    styles = create_styles()

    # Add cover content
    flowables = []

    # Spacer for title positioning
    flowables.append(Spacer(1, 1.5*inch))

    # Parse and add content
    content_flowables = parse_markdown(md_content, styles)
    flowables.extend(content_flowables)

    # Add final spacer
    flowables.append(Spacer(1, inch))

    # Build PDF
    doc.build(flowables, onFirstPage=add_header_footer, onLaterPages=add_header_footer)

    print(f"PDF generated: {pdf_path}")


if __name__ == '__main__':
    # Paths
    script_dir = Path(__file__).parent
    md_path = script_dir / 'CZFlux_Python_Scripting_Guide.md'
    pdf_path = script_dir / 'CZFlux_Python_Scripting_Guide.pdf'

    generate_pdf(md_path, pdf_path)
