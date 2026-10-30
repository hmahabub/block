from django.contrib import messages


def report_sms(request, log, what):
    """Tell the person at the screen what happened to the customer's SMS (`what`: 'Payment', 'Booking' ...).

    `log` is the SmsLog from sms.services, or None when the customer is excluded from SMS.
    """
    if log is None:
        messages.info(request, 'No SMS sent: this customer is excluded from SMS.')
    elif log.status == log.Status.SENT:
        messages.success(request, f'{what} SMS sent to {log.phone}.')
    elif log.status == log.Status.LOGGED:
        messages.warning(
            request,
            f'{what} saved, but the SMS to {log.phone} was NOT delivered: no SMS gateway is set up yet, '
            'so it was only recorded in the SMS log.',
        )
    else:
        messages.warning(request, f'{what} saved, but the SMS could not be sent: {log.error}')
