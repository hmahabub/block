from django.contrib import messages

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
    """Logs the deletion to the activity feed and flashes a success message."""

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        obj_repr = str(obj)
        model_name = obj.__class__.__name__
        response = super().delete(request, *args, **kwargs)
        log_activity(request.user, 'deleted', None, model_name=model_name, object_repr=obj_repr)
        messages.success(request, f"{obj_repr} was deleted successfully.")
        return response
