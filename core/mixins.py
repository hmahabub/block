from django.contrib import messages
from django.db.models import ProtectedError
from django.http import HttpResponseRedirect

from activity_log.services import log_activity


class CreateAuditMixin:
    """Logs the create to the activity feed and flashes a success message."""

    def form_valid(self, form):
        response = super().form_valid(form)
        log_activity(self.request.user, 'created', self.object)
        messages.success(self.request, f"{self.object} was created successfully.")
        return response


class UpdateAuditMixin:
    """Logs the update to the activity feed and flashes a success message."""

    def form_valid(self, form):
        response = super().form_valid(form)
        log_activity(self.request.user, 'updated', self.object)
        messages.success(self.request, f"{self.object} was updated successfully.")
        return response


class DeleteAuditMixin:
    """Logs the deletion to the activity feed and flashes a success message.

    If the object is protected by related records, nothing is deleted and the user is told why.
    """

    def form_valid(self, form):
        obj = self.object
        obj_repr = str(obj)
        model_name = obj.__class__.__name__
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f"{obj_repr} cannot be deleted because other records depend on it (for example flats, sales or costs).",
            )
            return HttpResponseRedirect(obj.get_absolute_url())
        log_activity(self.request.user, 'deleted', None, model_name=model_name, object_repr=obj_repr)
        messages.success(self.request, f"{obj_repr} was deleted successfully.")
        return response
