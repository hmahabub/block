"""SMS gateways.

`log`      (default) sends nothing; the message is only recorded in the SMS log. Safe for development.
`zendsms`  sends through ZendSMS (https://api.zendsms.com):

    POST /api/v1/send-sms   Authorization: Bearer <API key>
         JSON {"recipient": "8801711000000", "sender_id": "...", "message": "...", "client_ref": "..."}
    GET  /api/v1/balance    Authorization: Bearer <API key>

    Answers look like {"success": true, "code": ..., "message": ..., "data": {"message_id": ..., "status": "QUEUED"}}
    and, on failure, {"success": false, "code": 2001, "message": "Invalid API key"}.

The request format follows ZendSMS's own Laravel package, because their HTTP documentation is not public. Verify a
real send once after setting the API key (Sales > SMS log shows the gateway's answer for every message).
"""
import json
import urllib.error
import urllib.request

from django.conf import settings

DEFAULT_SEND_URL = 'https://api.zendsms.com/api/v1/send-sms'
DEFAULT_BALANCE_URL = 'https://api.zendsms.com/api/v1/balance'
TIMEOUT = 20


class SmsError(Exception):
    pass


class LogBackend:
    name = 'log'
    delivers = False

    def send(self, phone, message, reference=''):
        return ''

    def balance(self):
        raise SmsError('No SMS gateway is set up (SMS_BACKEND=log), so there is no balance to check.')


class ZendSmsBackend:
    name = 'zendsms'
    delivers = True

    @staticmethod
    def _recipient(phone):
        """ZendSMS takes the number with the country code and no plus sign: +8801711000000 -> 8801711000000."""
        return ''.join(ch for ch in phone if ch.isdigit())

    @staticmethod
    def _need_key():
        if not settings.SMS_API_KEY:
            raise SmsError('SMS_API_KEY is not set.')

    def _call(self, request):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                body = response.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as error:
            # The gateway explains its refusals in the body, e.g. {"success": false, "message": "Invalid API key"}.
            body = error.read().decode('utf-8', 'replace')
            raise SmsError(self._reason(body) or f'Gateway answered HTTP {error.code}') from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise SmsError(f'Gateway not reachable: {error}') from error
        try:
            data = json.loads(body)
        except ValueError as error:
            raise SmsError(f'Unreadable answer from the gateway: {body[:150]}') from error
        if not isinstance(data, dict) or not data.get('success'):
            raise SmsError(self._reason(body) or 'The gateway did not accept the request.')
        return data

    @staticmethod
    def _reason(body):
        try:
            data = json.loads(body)
        except ValueError:
            return body[:200].strip()
        if isinstance(data, dict):
            return str(data.get('message') or '')[:250]
        return ''

    def _headers(self):
        return {'Authorization': f'Bearer {settings.SMS_API_KEY}', 'Accept': 'application/json',
                'Content-Type': 'application/json'}

    def send(self, phone, message, reference=''):
        """Send one message; returns the gateway's message id."""
        self._need_key()
        if not settings.SMS_SENDER_ID:
            raise SmsError('SMS_SENDER_ID is not set.')
        payload = {'recipient': self._recipient(phone), 'sender_id': settings.SMS_SENDER_ID, 'message': message}
        if reference:
            payload['client_ref'] = reference[:60]
        request = urllib.request.Request(
            settings.SMS_API_URL or DEFAULT_SEND_URL, data=json.dumps(payload).encode(), headers=self._headers(), method='POST',
        )
        data = self._call(request).get('data') or {}
        return str(data.get('message_id') or '')

    def balance(self):
        """The account's SMS balance, as the gateway reports it (the `data` part of the answer)."""
        self._need_key()
        request = urllib.request.Request(
            settings.SMS_BALANCE_URL or DEFAULT_BALANCE_URL, headers=self._headers(), method='GET',
        )
        return self._call(request).get('data')


BACKENDS = {'log': LogBackend, 'zendsms': ZendSmsBackend}


def get_backend():
    return BACKENDS.get(settings.SMS_BACKEND, LogBackend)()
