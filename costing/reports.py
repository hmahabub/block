from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BRAND = colors.HexColor('#0b3d3a')
ZEBRA = colors.HexColor('#f4f6f6')


def describe_filters(applied):
    """Human-readable lines for the report header, e.g. 'Period: 01 Mar 2026 to 31 Mar 2026'."""
    date_from, date_to = applied['date_from'], applied['date_to']
    if date_from and date_to:
        period = f'{date_from:%d %b %Y} to {date_to:%d %b %Y}'
    elif date_from:
        period = f'from {date_from:%d %b %Y}'
    elif date_to:
        period = f'up to {date_to:%d %b %Y}'
    else:
        period = 'All dates'
    parts = [f'Period: {period}', f'Project: {applied["project"].project_name if applied["project"] else "All"}']
    parts.append({'shared': 'Type: Shared costs only', 'direct': 'Type: Direct flat costs only'}.get(applied['type'], 'Type: Shared & direct'))
    if applied['q']:
        parts.append(f'Search: "{applied["q"]}"')
    return parts


def _money(value):
    return f'{value:,.2f}'


def _draw_page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(doc.leftMargin, 8 * mm, f'{settings.COMPANY_NAME} - Project Cost Report')
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 8 * mm, f'Page {canvas.getPageNumber()}')
    canvas.restoreState()


def build_cost_report_pdf(target, costs, applied, user):
    """Write the filtered project costs as an A4 landscape PDF to `target` (file-like or HttpResponse)."""
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('cell', parent=styles['BodyText'], fontSize=7.5, leading=9)
    head = ParagraphStyle('head', parent=cell, textColor=colors.white, fontName='Helvetica-Bold')
    company = ParagraphStyle('company', parent=styles['Title'], alignment=0, textColor=BRAND, fontSize=17, spaceAfter=0)
    subtitle = ParagraphStyle('subtitle', parent=styles['Heading2'], textColor=colors.HexColor('#d97706'), fontSize=12, spaceAfter=2)
    meta = ParagraphStyle('meta', parent=cell, fontSize=8.5, leading=11, textColor=colors.HexColor('#495057'))
    section = ParagraphStyle('section', parent=styles['Heading3'], fontSize=10, textColor=BRAND, spaceBefore=10, spaceAfter=4)

    doc = SimpleDocTemplate(
        target, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=16 * mm, title='Project Cost Report',
    )

    costs = list(costs.select_related('project', 'cost_category', 'cost_category__parent_category', 'supplier', 'flat'))
    total = sum((c.amount for c in costs), 0)

    elements = [
        Paragraph(settings.COMPANY_NAME, company),
        Paragraph('Project Cost Report', subtitle),
        Paragraph(' &nbsp;|&nbsp; '.join(describe_filters(applied)), meta),
        Paragraph(f'Generated {timezone.localtime():%d %b %Y, %I:%M %p} by {user.get_full_name() or user.username}', meta),
        Spacer(1, 6),
    ]

    header = [Paragraph(h, head) for h in ('Date', 'Voucher', 'Project', 'Cost head', 'Supplier', 'Charged to', 'Description / Ref', 'Amount (BDT)')]
    rows = [header]
    for cost in costs:
        detail = cost.description or ''
        if cost.reference_no:
            detail = f'{detail} (Ref: {cost.reference_no})'.strip()
        rows.append([
            f'{cost.date:%d %b %Y}',
            cost.voucher_no,
            cost.project.project_code,
            Paragraph(str(cost.cost_category), cell),
            Paragraph(cost.supplier.name if cost.supplier else '-', cell),
            f'Flat {cost.flat.flat_no}' if cost.flat else 'Shared',
            Paragraph(detail or '-', cell),
            _money(cost.amount),
        ])
    if not costs:
        rows.append(['No cost entries for the selected filters', '', '', '', '', '', '', ''])
    rows.append(['', '', '', '', '', '', Paragraph(f'<b>TOTAL ({len(costs)} entries)</b>', cell), _money(total)])

    widths = [22, 22, 22, 46, 44, 24, 60, 27]
    table = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), BRAND),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#ced4da')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, ZEBRA]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e2ecea')),
        ('FONTNAME', (-1, -1), (-1, -1), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    if not costs:
        style.append(('SPAN', (0, 1), (-1, 1)))
        style.append(('ALIGN', (0, 1), (-1, 1), 'CENTER'))
    table.setStyle(TableStyle(style))
    elements.append(table)

    if costs:
        by_category = sorted(_group_by_category(costs).items(), key=lambda item: -item[1][1])
        summary = [[Paragraph(h, head) for h in ('Cost head', 'Entries', 'Amount (BDT)')]]
        for label, (count, amount) in by_category:
            summary.append([Paragraph(label, cell), str(count), _money(amount)])
        summary_table = Table(summary, colWidths=[90 * mm, 22 * mm, 34 * mm], repeatRows=1, hAlign='LEFT')
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND),
            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#ced4da')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ZEBRA]),
        ]))
        elements += [Paragraph('Summary by cost head', section), summary_table]

    doc.build(elements, onFirstPage=_draw_page_footer, onLaterPages=_draw_page_footer)


def _group_by_category(costs):
    grouped = {}
    for cost in costs:
        count, amount = grouped.get(str(cost.cost_category), (0, 0))
        grouped[str(cost.cost_category)] = (count + 1, amount + cost.amount)
    return grouped
