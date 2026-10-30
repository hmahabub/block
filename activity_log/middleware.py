from . import context


class AuditContextMiddleware:
    """Remembers the request while it is handled, so every create/update/delete can be attributed to the user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = context.set_request(request)
        try:
            return self.get_response(request)
        finally:
            context.reset_request(token)
