"""A report is a list of tables. The same tables are shown on screen and written to the PDF."""
from dataclasses import dataclass, field

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table as PdfTable, TableStyle

from core.formatting import NUMERIC_KINDS, TEXT, format_cell
from core.letterhead import letterhead_flowables

BRAND = colors.HexColor('#0b3d3a')
ZEBRA = colors.HexColor('#f4f6f6')


@dataclass
class Column:
    label: str
    kind: str = TEXT

    @property
    def numeric(self):
        return self.kind in NUMERIC_KINDS


@dataclass
class ReportTable:
    title: str
    columns: list
    rows: list
    totals: list = None  # same length as columns; None for no total row
    note: str = ''
    cells: list = field(default_factory=list, init=False)
    total_cells: list = field(default_factory=list, init=False)

    def __post_init__(self):
        self.refresh()

    def refresh(self):
        self.cells = [self._format(row) for row in self.rows]
        self.total_cells = self._format(self.totals) if self.totals else []

    def _format(self, row):
        return [(format_cell(value, column.kind), column.numeric) for value, column in zip(row, self.columns)]

    @property
    def headers(self):
        return [(column.label, column.numeric) for column in self.columns]


def _draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(doc.leftMargin, 8 * mm, f'{doc.company_name} - {doc.report_title}')
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 8 * mm, f'Page {canvas.getPageNumber()}')
    canvas.restoreState()


def build_pdf(target, title, filter_lines, tables, user):
    """Write the report as an A4 landscape PDF with the company letterhead to `target`."""
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('cell', parent=styles['BodyText'], fontSize=7.5, leading=9)
    head = ParagraphStyle('head', parent=cell, textColor=colors.white, fontName='Helvetica-Bold')
    company = ParagraphStyle('company', parent=styles['Title'], alignment=0, textColor=BRAND, fontSize=17, spaceAfter=0)
    subtitle = ParagraphStyle('subtitle', parent=styles['Heading2'], textColor=colors.HexColor('#d97706'), fontSize=12, spaceAfter=2)
    meta = ParagraphStyle('meta', parent=cell, fontSize=8.5, leading=11, textColor=colors.HexColor('#495057'))
    section = ParagraphStyle('section', parent=styles['Heading3'], fontSize=10, textColor=BRAND, spaceBefore=10, spaceAfter=4)

    doc = SimpleDocTemplate(
        target, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=16 * mm, title=title,
    )
    header, profile = letterhead_flowables(doc.width, company, meta)
    doc.company_name = profile.display_name
    doc.report_title = title

    elements = [*header, Spacer(1, 4), Paragraph(title, subtitle)]
    if filter_lines:
        elements.append(Paragraph(' &nbsp;|&nbsp; '.join(filter_lines), meta))
    elements += [
        Paragraph(f'Generated {timezone.localtime():%d %b %Y, %I:%M %p} by {user.get_full_name() or user.username}', meta),
        Spacer(1, 4),
    ]

    for table in tables:
        elements.append(Paragraph(table.title, section))
        header_row = [Paragraph(label, head) for label, _ in table.headers]
        data = [header_row]
        for row in table.cells:
            data.append([Paragraph(text, cell) if not numeric else text for text, numeric in row])
        if not table.cells:
            data.append(['No data'] + [''] * (len(table.columns) - 1))
        has_totals = bool(table.total_cells)
        if has_totals:
            data.append([Paragraph(f'<b>{text}</b>', cell) if not numeric else text for text, numeric in table.total_cells])

        weights = [1.8] + [1.0] * (len(table.columns) - 1)
        widths = [doc.width * weight / sum(weights) for weight in weights]
        pdf_table = PdfTable(data, colWidths=widths, repeatRows=1)
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), BRAND),
            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#ced4da')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]
        for index, column in enumerate(table.columns):
            if column.numeric:
                style.append(('ALIGN', (index, 0), (index, -1), 'RIGHT'))
        if has_totals:
            style += [
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e2ecea')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ]
        pdf_table.setStyle(TableStyle(style))
        elements.append(pdf_table)
        if table.note:
            elements.append(Paragraph(table.note, meta))

    doc.build(elements, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
