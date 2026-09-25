from django.conf import settings


def company(request):
    return {
        'company_name': settings.COMPANY_NAME,
        'company_address': settings.COMPANY_ADDRESS,
        'company_phone': settings.COMPANY_PHONE,
    }
