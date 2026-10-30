from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from core.models import ConfirmableModel
from core.numbering import generate_dashed_code
from core.phone import normalize_phone

ZERO = Decimal('0')


class Director(models.Model):
    """A director who puts money into a project and takes it back as the flats sell."""

    director_code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=17, blank=True, help_text='+88 is added automatically to local numbers.')
    email = models.EmailField(blank=True)
    identification_no = models.CharField('NID / Passport No.', max_length=50, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['identification_no'], condition=~models.Q(identification_no=''), name='director_nid_unique_when_given',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.director_code})'

    def save(self, *args, **kwargs):
        if not self.director_code:
            self.director_code = generate_dashed_code('director', 'DIR')
        self.identification_no = (self.identification_no or '').strip()
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('directors:detail', kwargs={'pk': self.pk})

    def totals(self, development=None):
        """invested, capital withdrawn, profit paid and capital still outstanding, for one project or all of them."""
        return totals_for(self, development)

    def project_rows(self):
        """One row of totals per project this director has any money in."""
        ids = self.transactions.values_list('development_id', flat=True).distinct()
        from projects.models import Development

        rows = []
        for development in Development.objects.filter(pk__in=ids):
            row = totals_for(self, development)
            row['development'] = development
            rows.append(row)
        return rows


class DirectorTransaction(ConfirmableModel):
    """Money between a director and the company for one project.

    Investment: the director puts money in. Capital withdrawal: part of that investment is paid back (never more
    than is still outstanding). Profit share paid: profit given to the director, on top of the capital.
    Each one moves money through a bank/cash account, so it reaches the book like every other payment: it waits for
    confirmation first.
    """

    class Kind(models.TextChoices):
        INVESTMENT = 'INVESTMENT', 'Investment'
        WITHDRAWAL = 'WITHDRAWAL', 'Capital withdrawal'
        PROFIT = 'PROFIT', 'Profit share paid'

    director = models.ForeignKey(Director, on_delete=models.PROTECT, related_name='transactions')
    development = models.ForeignKey(
        'projects.Development', on_delete=models.PROTECT, related_name='director_transactions', verbose_name='Project',
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.INVESTMENT)
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    account = models.ForeignKey(
        'books.Account', on_delete=models.PROTECT, related_name='director_transactions', verbose_name='Bank / cash account',
        help_text='Where the money went in, or came out of.',
    )
    reference_note = models.CharField('Cheque / transaction ref.', max_length=100, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']
        verbose_name = 'Director transaction'

    def __str__(self):
        return f'{self.reference_no}: {self.get_kind_display()} {self.amount} ({self.director.name})'

    @property
    def reference_no(self):
        return f'DT-{self.pk:05d}' if self.pk else 'DT-new'

    @property
    def money_in(self):
        return self.kind == self.Kind.INVESTMENT

    def get_absolute_url(self):
        return reverse('directors:detail', kwargs={'pk': self.director_id})

    def clean(self):
        """Capital paid back can never exceed what the director invested in that project."""
        if not (self.director_id and self.development_id and self.amount is not None):
            return
        invested, withdrawn = capital_figures(self.director_id, self.development_id, exclude=self.pk)
        if self.kind == self.Kind.INVESTMENT:
            invested += self.amount
            if withdrawn > invested:
                raise ValidationError({'amount': f'{withdrawn:,.2f} has already been withdrawn, so the investment cannot be '
                                                  f'lower than that ({invested:,.2f} would remain).'})
        elif self.kind == self.Kind.WITHDRAWAL:
            outstanding = invested - withdrawn
            if self.amount > outstanding:
                raise ValidationError({'amount': f'Only {outstanding:,.2f} of capital is still outstanding for this '
                                                  'director in this project.'})


def capital_figures(director_id, development_id, exclude=None):
    """(invested, capital withdrawn) for one director in one project, optionally leaving one transaction out."""
    rows = DirectorTransaction.objects.filter(director_id=director_id, development_id=development_id)
    if exclude:
        rows = rows.exclude(pk=exclude)

    def total(kind):
        return rows.filter(kind=kind).aggregate(t=models.Sum('amount'))['t'] or ZERO

    return total(DirectorTransaction.Kind.INVESTMENT), total(DirectorTransaction.Kind.WITHDRAWAL)


def totals_for(director=None, development=None):
    """Money figures across the matching transactions. Leave an argument out to cover all of them."""
    rows = DirectorTransaction.objects.all()
    if director is not None:
        rows = rows.filter(director=director)
    if development is not None:
        rows = rows.filter(development=development)

    def total(kind):
        return rows.filter(kind=kind).aggregate(t=models.Sum('amount'))['t'] or ZERO

    invested, withdrawn = total(DirectorTransaction.Kind.INVESTMENT), total(DirectorTransaction.Kind.WITHDRAWAL)
    return {
        'invested': invested, 'withdrawn': withdrawn, 'profit_paid': total(DirectorTransaction.Kind.PROFIT),
        'outstanding': invested - withdrawn,
        'returned_percent': (withdrawn / invested * 100) if invested else None,
    }
