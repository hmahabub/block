import csv
import datetime

from django.conf import settings
from django.db import migrations


def archive_manual_entries(apps, schema_editor):
    """The old cash/bank books were typed by hand; the merged book is collected from the source
    modules instead, so those rows have nowhere to live. Write them to a CSV beside the project
    before the tables are dropped, so no record is ever lost silently."""
    CashBook = apps.get_model('books', 'CashBook')
    BankBook = apps.get_model('books', 'BankBook')
    if not (CashBook.objects.exists() or BankBook.objects.exists()):
        return
    backups = settings.BASE_DIR / 'backups'
    backups.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    path = backups / f'old_cash_and_bank_book_{stamp}.csv'
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['book', 'bank_account', 'date', 'type', 'amount', 'particulars', 'cheque_no', 'cheque_date', 'balance'])
        for row in CashBook.objects.order_by('date', 'id'):
            writer.writerow(['cash', '', row.date, row.transaction_type, row.amount, row.particulars, '', '', row.current_balance])
        for row in BankBook.objects.select_related('bank_account').order_by('date', 'id'):
            writer.writerow(['bank', str(row.bank_account), row.date, row.transaction_type, row.amount,
                             row.particulars, row.cheque_no, row.cheque_date or '', row.current_balance])


class Migration(migrations.Migration):
    """Dropped in its own migration: Django cannot rename BankAccount in the same step that deletes
    the models pointing at it."""

    dependencies = [
        ('books', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(archive_manual_entries, migrations.RunPython.noop),
        migrations.DeleteModel(name='BankBook'),
        migrations.DeleteModel(name='CashBook'),
    ]
