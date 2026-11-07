"""The invoice as a PDF file (portrait A4, with the company letterhead): the same content as the printable invoice page."""
from decimal import Decimal
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.letterhead import letterhead_flowables
from core.templatetags.core_tags import taka_words
from reports.tables import BRAND, ZEBRA, _draw_footer

ACCENT = colors.HexColor('#d97706')


def _money(value):
    return f'{value:,.2f}'


def build_invoice_pdf(target, sale, payments):
    styles = getSampleStyleSheet()
    text = ParagraphStyle('text', parent=styles['BodyText'], fontSize=9, leading=11.5)
    small = ParagraphStyle('small', parent=text, fontSize=8, leading=10, textColor=colors.HexColor('#495057'))
    right = ParagraphStyle('right', parent=text, alignment=2)
    label = ParagraphStyle('label', parent=small, textColor=colors.HexColor('#6c757d'), fontSize=7.5)
    company = ParagraphStyle('company', parent=styles['Title'], alignment=0, textColor=BRAND, fontSize=17, spaceAfter=0)
    heading = ParagraphStyle('heading', parent=styles['Title'], alignment=0, textColor=ACCENT, fontSize=18, spaceAfter=0)
    head = ParagraphStyle('head', parent=text, textColor=colors.white, fontName='Helvetica-Bold')

    doc = SimpleDocTemplate(
        target, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=16 * mm,
        title=f'Invoice {sale.sale_no}',
    )
    header, profile = letterhead_flowables(doc.width, company, small)
    doc.company_name = profile.display_name
    doc.report_title = f'Invoice {sale.sale_no}'

    customer, flat, building = sale.customer, sale.flat, sale.project
    if sale.status == sale.Status.CANCELLED:
        stamp = 'CANCELLED'
    elif sale.receivable_amount == 0 and sale.net_value > 0:
        stamp = 'PAID IN FULL'
    else:
        stamp = ''
    meta = f'<b>Invoice No:</b> {escape(sale.sale_no)}<br/><b>Date:</b> {sale.sale_date:%d %b %Y}'
    if stamp:
        meta += f'<br/><b>{stamp}</b>'
    bar = Table([[Paragraph('INVOICE', heading), Paragraph(meta, right)]], colWidths=[doc.width * 0.5, doc.width * 0.5])
    bar.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), 1.5, BRAND), ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#ced4da')),
                             ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    bill = [Paragraph('BILL TO', label), Paragraph(f'<b>{escape(customer.name)}</b>', text),
            Paragraph(f'Customer ID: {escape(customer.customer_code)}', small), Paragraph(f'Phone: {escape(customer.phone)}', small)]
    if customer.email:
        bill.append(Paragraph(escape(customer.email), small))
    if customer.identification_no:
        bill.append(Paragraph(f'NID / Passport: {escape(customer.identification_no)}', small))
    if customer.present_address:
        bill.append(Paragraph(escape(customer.present_address).replace('\n', '<br/>'), small))
    prop = [Paragraph('PROPERTY', label), Paragraph(f'<b>{escape(building.project_name)} - Flat {escape(flat.flat_no)}</b>', text),
            Paragraph(escape(building.project_code + (f' - {building.location}' if building.location else '')), small),
            Paragraph(f'Floor {flat.floor_no} - {escape(flat.get_flat_type_display())} - {flat.saleable_area} sqft', small)]
    if sale.with_parking:
        prop.append(Paragraph(f'Includes parking lot {escape(flat.parking_lot)}', small))
    parties = Table([[bill, prop]], colWidths=[doc.width * 0.5, doc.width * 0.5])
    parties.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))

    def grid(data, widths, header_row=True, total_rows=()):
        table = Table(data, colWidths=widths, repeatRows=1 if header_row else 0)
        style = [('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#ced4da')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                 ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]
        if header_row:
            style.append(('BACKGROUND', (0, 0), (-1, 0), BRAND))
        for row in total_rows:
            style += [('BACKGROUND', (0, row), (-1, row), colors.HexColor('#e2ecea'))]
        table.setStyle(TableStyle(style))
        return table

    def cell(value, bold=False, style=text):
        return Paragraph(f'<b>{escape(str(value))}</b>' if bold else escape(str(value)), style)

    items = [[Paragraph('Description', head), Paragraph('Amount (Tk)', ParagraphStyle('hr', parent=head, alignment=2))],
             [cell(f'Flat {flat.flat_no} - sale value'), cell(_money(sale.flat_sale_value), style=right)]]
    total_rows = []
    if sale.with_parking:
        items.append([cell(f'Parking lot {flat.parking_lot} - sale value'), cell(_money(sale.parking_sale_value), style=right)])
        items.append([cell('Sale value (flat + parking)', True), cell(_money(sale.sale_value), True, right)])
        total_rows.append(len(items) - 1)
    if sale.reg_value:
        items.append([cell('Registration cost'), cell(_money(sale.reg_value), style=right)])
    items.append([cell('Net value', True), cell(_money(sale.net_value), True, right)])
    total_rows.append(len(items) - 1)
    item_table = grid(items, [doc.width * 0.75, doc.width * 0.25], total_rows=total_rows)

    words = Table([[Paragraph(f'<font size="7.5" color="#6c757d">NET VALUE IN WORDS</font><br/><b>{escape(str(taka_words(sale.net_value)))}</b>', text)]],
                  colWidths=[doc.width])
    words.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#adb5bd')), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafafa')),
                               ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))

    rows = [[Paragraph(label_, head) for label_ in ('Receipt', 'Date', 'For', 'Paid into', 'Reference')]
            + [Paragraph('Amount (Tk)', ParagraphStyle('hr2', parent=head, alignment=2))]]
    for payment in payments:
        rows.append([cell(payment.receipt_no), cell(f'{payment.payment_date:%d %b %Y}'),
                     cell(payment.purpose_text), cell(payment.account or payment.get_payment_method_display()), cell(payment.reference_no or '-'),
                     cell(_money(payment.amount), style=right)])
    if len(rows) == 1:
        rows.append([cell('No payments received yet'), '', '', '', '', ''])
    rows.append(['', '', '', '', cell('Total received', True), cell(_money(sale.received_amount), True, right)])
    rows.append(['', '', '', '', cell('Balance due', True), cell(_money(sale.receivable_amount), True, right)])
    if sale.customer_balance > 0:
        rows.append(['', '', '', '', cell('Credit balance', True), cell(_money(sale.customer_balance), True, right)])
    w = doc.width
    pay_table = grid(rows, [w * 0.14, w * 0.14, w * 0.2, w * 0.18, w * 0.16, w * 0.18])

    sign = Table([[Paragraph('Customer signature', small), Paragraph(f'Authorized signatory<br/>{escape(profile.display_name)}', small)]],
                 colWidths=[doc.width * 0.5, doc.width * 0.5])
    sign.setStyle(TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.6, colors.black), ('LINEABOVE', (1, 0), (1, 0), 0.6, colors.black),
                              ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('LEFTPADDING', (0, 0), (-1, -1), 30), ('RIGHTPADDING', (0, 0), (-1, -1), 30)]))

    elements = [*header, Spacer(1, 6), bar, Spacer(1, 8), parties, Spacer(1, 10), item_table, Spacer(1, 6), words,
                Spacer(1, 10), Paragraph('PAYMENTS RECEIVED', label), Spacer(1, 2), pay_table, Spacer(1, 40), sign, Spacer(1, 10),
                Paragraph(f'Generated {timezone.localtime():%d %b %Y, %I:%M %p}. This is a computer-generated document.', small)]
    doc.build(elements, onFirstPage=_draw_footer, onLaterPages=_draw_footer)


def build_invoice_document_pdf(target, invoice, payments):
    """One invoice (the flat booking's, or an installment's) as a PDF: what it is for, the amount and the payments under it."""
    sale = invoice.sale
    customer, flat, building = sale.customer, sale.flat, sale.project
    styles = getSampleStyleSheet()
    text = ParagraphStyle('text', parent=styles['BodyText'], fontSize=9, leading=11.5)
    small = ParagraphStyle('small', parent=text, fontSize=8, leading=10, textColor=colors.HexColor('#495057'))
    right = ParagraphStyle('right', parent=text, alignment=2)
    label = ParagraphStyle('label', parent=small, textColor=colors.HexColor('#6c757d'), fontSize=7.5)
    company = ParagraphStyle('company', parent=styles['Title'], alignment=0, textColor=BRAND, fontSize=17, spaceAfter=0)
    heading = ParagraphStyle('heading', parent=styles['Title'], alignment=0, textColor=ACCENT, fontSize=18, spaceAfter=0)
    head = ParagraphStyle('head', parent=text, textColor=colors.white, fontName='Helvetica-Bold')

    doc = SimpleDocTemplate(target, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=16 * mm,
                            title=f'Invoice {invoice.number}')
    header, profile = letterhead_flowables(doc.width, company, small)
    doc.company_name = profile.display_name
    doc.report_title = f'Invoice {invoice.number}'

    meta = f'<b>Invoice No:</b> {invoice.number}<br/><b>Issued:</b> {invoice.issued_on:%d %b %Y}'
    if invoice.due_date:
        meta += f'<br/><b>Pay by:</b> {invoice.due_date:%d %b %Y}'
    meta += f'<br/><b>{invoice.status.upper()}</b>'
    bar = Table([[Paragraph('INVOICE', heading), Paragraph(meta, right)]], colWidths=[doc.width * 0.5, doc.width * 0.5])
    bar.setStyle(TableStyle([('LINEABOVE', (0, 0), (-1, 0), 1.5, BRAND), ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#ced4da')),
                             ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))

    bill = [Paragraph('BILL TO', label), Paragraph(f'<b>{escape(customer.name)}</b>', text),
            Paragraph(f'Customer ID: {escape(customer.customer_code)}', small), Paragraph(f'Phone: {escape(customer.phone)}', small)]
    prop = [Paragraph('PROPERTY', label), Paragraph(f'<b>{escape(building.project_name)} - Flat {escape(flat.flat_no)}</b>', text),
            Paragraph(f'Booking {escape(sale.sale_no)}', small)]
    parties = Table([[bill, prop]], colWidths=[doc.width * 0.5, doc.width * 0.5])
    parties.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))

    def grid(data, widths, total_rows=(), span_rows=()):
        table = Table(data, colWidths=widths, repeatRows=1)
        style = [('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#ced4da')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                 ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('BACKGROUND', (0, 0), (-1, 0), BRAND)]
        style += [('BACKGROUND', (0, row), (-1, row), colors.HexColor('#e2ecea')) for row in total_rows]
        style += [('SPAN', (0, row), (-1, row)) for row in span_rows]
        table.setStyle(TableStyle(style))
        return table

    def cell(value, bold=False, style=text):
        return Paragraph(f'<b>{escape(str(value))}</b>' if bold else escape(str(value)), style)

    what = f'{invoice.label}: flat {flat.flat_no}'
    if invoice.kind == invoice.Kind.BOOKING:
        what += ' (net value of the booking, less the installments issued)'
    paid = sum((p.amount for p in payments), Decimal('0'))
    items = [[Paragraph('Description', head), Paragraph('Amount (Tk)', ParagraphStyle('hr', parent=head, alignment=2))],
             [cell(what), cell(_money(invoice.total), style=right)]]
    item_table = grid(items, [doc.width * 0.75, doc.width * 0.25])
    words = Table([[Paragraph(f'<font size="7.5" color="#6c757d">AMOUNT IN WORDS</font><br/><b>{escape(str(taka_words(invoice.total)))}</b>', text)]],
                  colWidths=[doc.width])
    words.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#adb5bd')), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafafa')),
                               ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))

    rows = [[Paragraph(h, head) for h in ('Receipt', 'Date', 'Paid into', 'Reference')] + [Paragraph('Amount (Tk)', ParagraphStyle('hr2', parent=head, alignment=2))]]
    for payment in payments:
        rows.append([cell(payment.receipt_no), cell(f'{payment.payment_date:%d %b %Y}'), cell(payment.account or payment.get_payment_method_display()),
                     cell(payment.reference_no or '-'), cell(_money(payment.amount), style=right)])
    empty_rows = ()
    if len(rows) == 1:
        rows.append([cell('No payment received under this invoice yet'), '', '', '', ''])
        empty_rows = (1,)
    rows.append(['', '', '', cell('Total paid', True), cell(_money(paid), True, right)])
    rows.append(['', '', '', cell('Balance due', True), cell(_money(max(invoice.total - paid, Decimal('0'))), True, right)])
    w = doc.width
    pay_table = grid(rows, [w * 0.17, w * 0.18, w * 0.27, w * 0.2, w * 0.18], span_rows=empty_rows)

    sign = Table([[Paragraph('Customer signature', small), Paragraph(f'Authorized signatory<br/>{escape(profile.display_name)}', small)]],
                 colWidths=[doc.width * 0.5, doc.width * 0.5])
    sign.setStyle(TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.6, colors.black), ('LINEABOVE', (1, 0), (1, 0), 0.6, colors.black),
                              ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('LEFTPADDING', (0, 0), (-1, -1), 30), ('RIGHTPADDING', (0, 0), (-1, -1), 30)]))
    elements = [*header, Spacer(1, 6), bar, Spacer(1, 8), parties, Spacer(1, 10), item_table, Spacer(1, 6), words, Spacer(1, 10),
                Paragraph('PAYMENTS RECEIVED UNDER THIS INVOICE', label), Spacer(1, 2), pay_table, Spacer(1, 40), sign, Spacer(1, 10),
                Paragraph(f'Generated {timezone.localtime():%d %b %Y, %I:%M %p}. This is a computer-generated document.', small)]
    doc.build(elements, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
