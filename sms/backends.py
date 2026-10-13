"""SMS gateways.

`log`  (default) sends nothing; the message is only recorded in the SMS log. Safe for development.
`http` posts the message to a gateway over HTTPS as form fields:

    api_key, senderid, number, message

which is the style used by most Bangladeshi bulk-SMS providers. Gateways differ in small ways
(field names, response format), so confirm these against your provider's documentation and adjust
HttpBackend if needed. It has not been tested against a live gateway.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class SmsError(Exception):
    pass


class LogBackend:
    name = 'log'
    delivers = False

    def send(self, phone, message):
        return 'logged'


class HttpBackend:
    name = 'http'
    delivers = True

    def send(self, phone, message):
        url = settings.SMS_API_URL
        if not url:
            raise SmsError('SMS_API_URL is not set.')
        payload = urllib.parse.urlencode({
            'api_key': settings.SMS_API_KEY,
            'senderid': settings.SMS_SENDER_ID,
            'number': phone.lstrip('+'),
            'message': message,
        }).encode()
        request = urllib.request.Request(url, data=payload, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode('utf-8', 'replace')
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise SmsError(f'Gateway not reachable: {error}') from error
        # Many gateways answer {"response_code": 202, ...}; treat explicit failure codes as errors.
        try:
            data = json.loads(body)
        except ValueError:
            return body[:200]
        code = data.get('response_code', data.get('status_code', 202))
        if str(code) not in ('202', '200', 'OK', 'ok', 'success'):
            raise SmsError(str(data.get('error_message') or data.get('message') or body)[:250])
        return body[:200]


BACKENDS = {'log': LogBackend, 'http': HttpBackend}


def get_backend():
    return BACKENDS.get(settings.SMS_BACKEND, LogBackend)()
