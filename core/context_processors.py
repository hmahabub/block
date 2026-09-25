from django.utils.functional import SimpleLazyObject

from .models import CompanyProfile


def company(request):
    # Lazy: the database is only queried on pages that actually use `company` (the printable documents).
    return {'company': SimpleLazyObject(CompanyProfile.current)}
