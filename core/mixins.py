from django.contrib import messages
from django.db.models import ProtectedError
from django.http import HttpResponseRedirect

class CreateAuditMixin:
    """Flashes a success message. (The audit trail line is written by the model signals, not here.)"""

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object} was created successfully.")
        return response


class UpdateAuditMixin:
    """Flashes a success message. (The audit trail line is written by the model signals, not here.)"""

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.object} was updated successfully.")
        return response


class DeleteAuditMixin:
    """Flashes a success message after a deletion. (The audit trail line is written by the model signals.)

    If the object is protected by related records, nothing is deleted and the user is told why.
    """

    def form_valid(self, form):
        obj = self.object
        obj_repr = str(obj)
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f"{obj_repr} cannot be deleted because other records depend on it (for example flats, sales or costs).",
            )
            return HttpResponseRedirect(obj.get_absolute_url())
        messages.success(self.request, f"{obj_repr} was deleted successfully.")
        return response
