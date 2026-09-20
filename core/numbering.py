from django.db import transaction
from django.utils import timezone
from django.conf import settings

from .models import Sequence


def next_number(key):
    """Atomically return the next integer in the named sequence, starting at 1."""
    with transaction.atomic():
        seq, _ = Sequence.objects.select_for_update().get_or_create(key=key)
        seq.last_number += 1
        seq.save(update_fields=['last_number'])
        return seq.last_number


def generate_year_code(series, infix, width=4):
    """e.g. generate_year_code('project', 'P') -> '26ABP0001' for the year 2026.

    `infix` disambiguates entity types that would otherwise collide —
    without it a customer and a project minted in the same year could both
    read "26AB0001", which is genuinely confusing in a printed document.
    """
    year_prefix = f"{timezone.now().year % 100:02d}{settings.COMPANY_CODE_PREFIX}{infix}"
    n = next_number(f"{series}:{year_prefix}")
    return f"{year_prefix}{n:0{width}d}"


def generate_slash_code(series, width=5):
    """e.g. generate_slash_code('sale') -> 'AB/2026/00001'."""
    year = timezone.now().year
    prefix = f"{settings.COMPANY_CODE_PREFIX}/{year}/"
    n = next_number(f"{series}:{prefix}")
    return f"{prefix}{n:0{width}d}"
