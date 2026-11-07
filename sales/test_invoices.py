"""Invoices: one for every flat booking and one for every installment; customers pay under an invoice, from one page."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.testing import enter_project, make_account, make_project, unlock_client
from customers.models import Customer
from installments import services
from projects.models import Development
from sms.services import payment_message

from .forms import CustomerPaymentForm
from .models import CustomerPayment, FlatSale, Invoice

D = Decimal
TODAY = datetime.date.today()
LATER = TODAY + datetime.timedelta(days=20)


class InvoiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        self.building, self.flats = make_project('Tower', floors=1, units=3, development=self.development)
        self.bank = make_account('Bank 1')
        self.customer = Customer.objects.create(name='Rahim', phone='01711000001')
        self.sale = FlatSale.objects.create(flat=self.flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=2000)
        self.other = FlatSale.objects.create(
            flat=self.flats[1], customer=Customer.objects.create(name='Karim', phone='01711000002'), sale_date='2026-01-01', sale_value=2000)

    def issue(self, value=500, title='Installment 1', due=LATER):
        return services.issue(self.development, self.user, title, due, 'FIXED', D(value))

    def form(self, invoice, amount='300', **extra):
        return CustomerPaymentForm(data={'invoice': invoice.pk, 'payment_date': '2026-02-01', 'amount': amount, 'account': self.bank.pk, **extra})


class InvoiceIssuingTests(InvoiceTestCase):
    def test_every_flat_booking_has_one_invoice(self):
        self.assertEqual([i.kind for i in self.sale.invoices.all()], ['BOOKING'])
        self.assertEqual(Invoice.objects.filter(kind='BOOKING').count(), 2)
        self.sale.save()
        self.assertEqual(self.sale.invoices.count(), 1)             # saving again never issues another

    def test_the_invoice_numbers_are_unique_and_readable(self):
        numbers = {i.number for i in Invoice.objects.all()}
        self.assertEqual(len(numbers), 2)
        self.assertTrue(all(n.startswith('INV-') for n in numbers))

    def test_the_booking_invoice_is_the_net_value(self):
        invoice = self.sale.booking_invoice
        self.assertEqual((invoice.total, invoice.paid, invoice.due, invoice.status, invoice.label), (2000, 0, 2000, 'Due', 'Flat booking'))

    def test_every_installment_issues_an_invoice_to_each_booking(self):
        installment = self.issue(500)
        invoices = Invoice.objects.filter(kind='INSTALLMENT')
        self.assertEqual(invoices.count(), 2)
        invoice = invoices.get(sale=self.sale)
        self.assertEqual((invoice.total, invoice.label, invoice.due_date, invoice.status), (500, 'Installment 1', LATER, 'Due'))
        self.assertEqual(invoice.charge.installment, installment)

    def test_the_invoices_of_a_booking_add_up_to_its_net_value(self):
        self.issue(500)
        self.issue(300, title='Installment 2')
        self.assertEqual(sum(i.total for i in self.sale.invoices.all()), 2000)
        self.assertEqual(self.sale.booking_invoice.total, 1200)         # the booking invoice shrinks as installments are carved out

    def test_withdrawing_an_installment_withdraws_its_invoices(self):
        installment = self.issue(500)
        services.withdraw(installment)
        self.assertFalse(Invoice.objects.filter(kind='INSTALLMENT').exists())
        self.assertEqual(self.sale.booking_invoice.total, 2000)

    def test_an_invoice_with_payments_cannot_be_deleted(self):
        invoice = self.sale.booking_invoice
        CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=10, account=self.bank, invoice=invoice)
        from django.db.models import RestrictedError

        with self.assertRaises(RestrictedError):
            invoice.delete()

    def test_status_follows_the_payments_and_the_deadline(self):
        installment = self.issue(500, due=TODAY - datetime.timedelta(days=2))
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        self.assertEqual(invoice.status, 'Overdue')
        CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=200, account=self.bank, invoice=invoice)
        self.assertEqual((invoice.paid, invoice.due), (200, 300))
        CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=300, account=self.bank, invoice=invoice)
        self.assertEqual(invoice.status, 'Paid')
        self.assertEqual(installment.charges.count(), 2)

    def test_a_cancelled_booking_shows_its_invoices_as_cancelled(self):
        self.sale.cancel(100)
        self.sale.save()
        self.assertEqual(self.sale.booking_invoice.status, 'Cancelled')


class PaymentFormTests(InvoiceTestCase):
    def test_a_payment_is_made_under_an_invoice(self):
        form = self.form(self.sale.booking_invoice)
        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save()
        self.assertEqual((payment.invoice, payment.sale, payment.customer, payment.purpose_text), (self.sale.booking_invoice, self.sale, self.customer, 'Flat booking'))

    def test_the_invoice_is_required(self):
        form = CustomerPaymentForm(data={'payment_date': '2026-02-01', 'amount': '10', 'account': self.bank.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('invoice', form.errors)

    def test_an_installment_invoice_is_paid_like_any_other(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        self.assertTrue(self.form(invoice, '500').save())
        row = services.allocate(FlatSale.objects.get(pk=self.sale.pk))[0]
        self.assertEqual((row.paid, row.due, row.status), (500, 0, services.PAID))

    def test_a_payment_cannot_be_more_than_the_invoice_has_due(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        too_much = self.form(invoice, '501')
        self.assertFalse(too_much.is_valid())
        self.assertIn('amount', too_much.errors)
        self.assertTrue(self.form(invoice, '500').is_valid())
        self.assertFalse(self.form(self.sale.booking_invoice, '1501').is_valid())       # 2000 - 500 installment

    def test_an_invoice_already_paid_in_full_is_refused(self):
        invoice = self.sale.booking_invoice
        CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=2000, account=self.bank, invoice=invoice)
        form = self.form(invoice, '10')
        self.assertFalse(form.is_valid())
        self.assertIn('invoice', form.errors)

    def test_a_cancelled_bookings_invoices_are_not_offered(self):
        invoice = self.sale.booking_invoice
        self.sale.cancel(100)
        self.sale.save()
        self.assertNotIn(invoice, list(CustomerPaymentForm().fields['invoice'].queryset))

    def test_only_the_open_projects_invoices_are_offered(self):
        far, flats = make_project('Villa', floors=1, units=1, development=Development.objects.create(name='Other'))
        far_sale = FlatSale.objects.create(flat=flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=900)
        offered = list(CustomerPaymentForm(development=self.development).fields['invoice'].queryset)
        self.assertIn(self.sale.booking_invoice, offered)
        self.assertNotIn(far_sale.booking_invoice, offered)

    def test_a_payment_made_without_naming_an_invoice_settles_the_booking(self):
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=50, account=self.bank)
        self.assertEqual(payment.invoice, self.sale.booking_invoice)

    def test_a_booking_payment_reduces_what_can_still_be_charged_as_installments(self):
        self.form(self.sale.booking_invoice, '700').save()
        installment = self.issue(2000)
        self.assertEqual(installment.charges.get(sale=self.sale).amount, 1300)

    def test_a_payment_under_the_booking_invoice_never_pays_an_installment(self):
        self.issue(500)
        self.form(self.sale.booking_invoice, '700').save()
        self.assertEqual(services.allocate(FlatSale.objects.get(pk=self.sale.pk))[0].paid, 0)


class ScreenTests(InvoiceTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)

    def data(self, invoice, **extra):
        return {'invoice': invoice.pk, 'payment_date': '2026-03-01', 'amount': '200', 'account': self.bank.pk, 'reference_no': '', 'notes': '', **extra}

    def test_the_payment_page_is_for_the_invoice_it_was_opened_from(self):
        invoice = self.sale.booking_invoice
        page = self.client.get(reverse('sales:payment-create'), {'invoice': invoice.pk}).content.decode()
        for text in (f'Record payment under {invoice.number}', 'Rahim', 'Still due', '2,000.00'):
            self.assertIn(text, page, text)

    def test_without_an_invoice_the_page_sends_you_to_choose_one(self):
        response = self.client.get(reverse('sales:payment-create'))
        self.assertRedirects(response, reverse('sales:invoice-list'))
        response = self.client.post(reverse('sales:payment-create'), {'amount': '10'})
        self.assertRedirects(response, reverse('sales:invoice-list'))
        self.assertFalse(CustomerPayment.objects.exists())

    def test_the_payment_cannot_be_moved_to_another_invoice(self):
        mine, theirs = self.sale.booking_invoice, self.other.booking_invoice
        self.client.post(f"{reverse('sales:payment-create')}?invoice={mine.pk}", self.data(theirs))
        self.assertEqual(CustomerPayment.objects.get().invoice, mine)            # the invoice in the address is the one paid

    def test_a_payment_is_recorded_from_the_invoice_pages_only(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        pay = reverse('sales:payment-create')
        # an invoice's own pages offer it ...
        self.assertIn(f'{pay}?invoice={invoice.pk}', self.client.get(reverse('sales:invoice-list')).content.decode())
        self.assertIn(f'{pay}?invoice={invoice.pk}', self.client.get(invoice.get_absolute_url()).content.decode())
        # ... and no other page does
        others = (reverse('sales:payment-list'), reverse('sales:detail', args=[self.sale.pk]), reverse('sales:list'),
                  reverse('installments:detail', args=[invoice.charge.installment.pk]), reverse('installments:list'),
                  reverse('customers:detail', args=[self.customer.pk]), reverse('home'))
        for url in others:
            self.assertNotIn(pay, self.client.get(url).content.decode(), url)

    def test_the_invoice_list_has_no_general_record_payment_button(self):
        page = self.client.get(reverse('sales:invoice-list')).content.decode()
        self.assertNotIn('Record a payment', page)

    def test_saving_a_payment_through_the_page(self):
        invoice = self.sale.booking_invoice
        response = self.client.post(f"{reverse('sales:payment-create')}?invoice={invoice.pk}", self.data(invoice))
        self.assertRedirects(response, invoice.get_absolute_url())
        self.assertEqual(CustomerPayment.objects.get().invoice, invoice)

    def test_the_page_refuses_more_than_the_invoice_has_due(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        response = self.client.post(reverse('sales:payment-create'), self.data(invoice, amount='600'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CustomerPayment.objects.exists())

    def test_the_link_from_an_invoice_opens_the_page_on_that_invoice(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        form = self.client.get(reverse('sales:payment-create'), {'invoice': invoice.pk}).context['form']
        self.assertEqual((form.initial['invoice'], form.fields['amount'].initial), (invoice.pk, D('500.00')))
        self.assertTrue(form.fields['invoice'].disabled)

    def test_the_invoice_list(self):
        self.issue(500)
        response = self.client.get(reverse('sales:invoice-list'))
        self.assertEqual(response.context['count'], 4)                          # two booking invoices, two installment invoices
        page = response.content.decode()
        self.assertIn('INV-', page)
        self.assertIn('Installment 1', page)
        self.assertEqual(self.client.get(reverse('sales:invoice-list'), {'kind': 'INSTALLMENT'}).context['count'], 2)
        self.assertEqual(self.client.get(reverse('sales:invoice-list'), {'q': 'Karim'}).context['count'], 2)

    def test_the_invoice_list_filters_by_what_is_due(self):
        self.issue(500, due=TODAY - datetime.timedelta(days=1))
        CustomerPayment.objects.create(sale=self.other, payment_date=TODAY, amount=1500, account=self.bank, invoice=self.other.booking_invoice)
        self.assertEqual(self.client.get(reverse('sales:invoice-list'), {'show': 'paid'}).context['count'], 1)
        self.assertEqual(self.client.get(reverse('sales:invoice-list'), {'show': 'overdue'}).context['count'], 2)
        self.assertEqual(self.client.get(reverse('sales:invoice-list'), {'show': 'open'}).context['count'], 3)

    def test_the_invoice_can_be_searched_by_its_number(self):
        invoice = self.sale.booking_invoice
        self.assertEqual(self.client.get(reverse('sales:invoice-list'), {'q': invoice.number}).context['count'], 1)

    def test_the_invoice_document_and_its_pdf(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=200, account=self.bank, invoice=invoice)
        page = self.client.get(invoice.get_absolute_url()).content.decode()
        for text in (invoice.number, 'Installment 1', 'Rahim', 'Pay by', '300.00', 'MR-'):
            self.assertIn(text, page, text)
        pdf = self.client.get(invoice.get_absolute_url(), {'format': 'pdf'})
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        booking = self.client.get(self.sale.booking_invoice.get_absolute_url(), {'format': 'pdf'})
        self.assertTrue(booking.content.startswith(b'%PDF'))

    def test_another_projects_invoice_is_not_found(self):
        invoice = self.sale.booking_invoice
        enter_project(self.client, Development.objects.create(name='Other'))
        self.assertEqual(self.client.get(invoice.get_absolute_url()).status_code, 404)

    def test_invoices_need_a_project_to_be_open(self):
        self.client.post(reverse('exit-project'))
        self.assertRedirects(self.client.get(reverse('sales:invoice-list')), reverse('home'))

    def test_the_sale_page_lists_its_invoices(self):
        self.issue(500)
        page = self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode()
        for invoice in self.sale.invoices.all():
            self.assertIn(invoice.number, page)
        self.assertIn('the customer pays under an invoice', page)

    def test_the_payment_shows_its_invoice_everywhere(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=50, account=self.bank, invoice=invoice)
        for url in (reverse('sales:payment-list'), reverse('sales:payment-receipt', args=[payment.pk]), reverse('sales:detail', args=[self.sale.pk])):
            self.assertIn(invoice.number, self.client.get(url).content.decode(), url)
        statement = self.client.get(reverse('sales:invoice', args=[self.sale.pk])).content.decode()
        self.assertIn('Installment 1', statement)

    def test_the_menu_links_to_the_invoices(self):
        self.assertIn(reverse('sales:invoice-list'), self.client.get(reverse('home')).content.decode())

    def test_the_payment_sms_can_say_which_invoice_it_paid(self):
        self.issue(500)
        invoice = self.sale.invoices.get(kind='INSTALLMENT')
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date=TODAY, amount=50, account=self.bank, invoice=invoice)
        with override_settings(SMS_TEMPLATE_PAYMENT='Received {amount} for {purpose}'):
            self.assertEqual(payment_message(payment), 'Received Tk 50.00 for Installment 1')
