import re

COUNTRY_PREFIX = '+88'


def normalize_phone(value):
    """Return a phone number in +88 form.

    Local Bangladeshi numbers (01711000000) and numbers typed with 88 but no plus get the +88 prefix.
    Numbers that already start with + are kept as they are, so foreign numbers still work.
    """
    if not value:
        return value
    number = re.sub(r'[\s\-().]', '', str(value))
    if number.startswith('+'):
        return number
    if number.startswith('0088'):
        return '+' + number[2:]
    if number.startswith('88') and len(number) >= 13:
        return '+' + number
    return COUNTRY_PREFIX + number
