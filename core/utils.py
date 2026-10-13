def int_or_none(value):
    """A query-string id as an int, or None when it is missing or not a whole number.

    Filters read ids straight from the URL, so a mistyped ?project=abc must mean "no filter", not a crash.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
