import os

from django.conf import settings
from django.db import models
from django.utils import timezone


class Sequence(models.Model):
    """Backing counter for atomic, gap-free document/code numbering.

    One row per numbering series (e.g. "project:26AB", "sale:AB/2026").
    next_number() below locks the row so concurrent requests can't hand
    out the same number — the bug inspcta's count()+1 approach has.
    """
    key = models.CharField(max_length=64, unique=True)
    last_number = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.key} -> {self.last_number}"


class CompanyProfile(models.Model):
    """The company's identity for printed documents. One row is used; blank fields fall back to settings."""

    name = models.CharField(
        max_length=150, blank=True,
        help_text='Shown when no letterhead image is uploaded. Leave blank to use the default company name.',
    )
    address = models.TextField(blank=True, help_text='Shown under the name when there is no letterhead image.')
    phone = models.CharField(max_length=50, blank=True)
    letterhead = models.ImageField(
        upload_to='letterhead/', blank=True,
        help_text='Header banner printed at the top of every document (PNG or JPG, max 5 MB). '
                  'Best as a wide image, e.g. 2480 x 400 px, which prints at full A4 width.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Company Profile'
        verbose_name_plural = 'Company Profile'

    def __str__(self):
        return self.display_name

    @classmethod
    def current(cls):
        """The saved profile, or an unsaved blank one so callers can always use the display_* values."""
        return cls.objects.first() or cls()

    @property
    def display_name(self):
        return self.name or settings.COMPANY_NAME

    @property
    def display_address(self):
        return self.address or settings.COMPANY_ADDRESS

    @property
    def display_phone(self):
        return self.phone or settings.COMPANY_PHONE

    @property
    def letterhead_path(self):
        """Filesystem path of the letterhead, or None if there isn't one (or the file has gone missing)."""
        if self.letterhead and os.path.exists(self.letterhead.path):
            return self.letterhead.path
        return None

    @property
    def letterhead_url(self):
        return self.letterhead.url if self.letterhead_path else None


class ConfirmableModel(models.Model):
    """Adds the "verified by" layer used by the books: every entry collected from a source
    module can be confirmed by a user before it counts as verified."""

    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
        on_delete=models.SET_NULL, related_name='+',
    )

    class Meta:
        abstract = True

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None

    def confirm(self, user):
        # Queryset update on purpose: models like CustomerPayment recalculate sale totals in save().
        self.confirmed_at, self.confirmed_by = timezone.now(), user
        type(self).objects.filter(pk=self.pk).update(confirmed_at=self.confirmed_at, confirmed_by=user)

    def unconfirm(self):
        self.confirmed_at = self.confirmed_by = None
        type(self).objects.filter(pk=self.pk).update(confirmed_at=None, confirmed_by=None)
