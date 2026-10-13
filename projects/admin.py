from django.contrib import admin

from .models import Flat, FlatDeletionRequest, Project


class FlatInline(admin.TabularInline):
    model = Flat
    extra = 0
    fields = ('unit', 'floor_no', 'flat_no', 'parking_lot', 'facing', 'status')
    readonly_fields = ('flat_no', 'status')
    can_delete = False  # flats are removed only through the two-admin approval flow


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('project_code', 'project_name', 'status', 'floor_no', 'flat_type', 'base_price', 'quoted_price')
    search_fields = ('project_code', 'project_name', 'location')
    list_filter = ('status',)
    inlines = [FlatInline]


@admin.register(Flat)
class FlatAdmin(admin.ModelAdmin):
    list_display = ('project', 'flat_no', 'floor_no', 'unit', 'parking_lot', 'facing', 'status')
    list_filter = ('status', 'project')
    search_fields = ('flat_no', 'project__project_name')
    readonly_fields = ('flat_no', 'status')

    def has_delete_permission(self, request, obj=None):
        return False  # use the deletion request screens so a second admin must approve


@admin.register(FlatDeletionRequest)
class FlatDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ('flat_label', 'status', 'requested_by', 'requested_at', 'decided_by')
    list_filter = ('status',)
    readonly_fields = ('flat', 'flat_label', 'status', 'requested_by', 'requested_at', 'decided_by', 'decided_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
