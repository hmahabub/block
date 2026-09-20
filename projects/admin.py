from django.contrib import admin

from .models import Flat, Project


class FlatInline(admin.TabularInline):
    model = Flat
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('project_code', 'project_name', 'status', 'floor_no', 'total_saleable_area')
    search_fields = ('project_code', 'project_name', 'location')
    list_filter = ('status',)
    inlines = [FlatInline]


@admin.register(Flat)
class FlatAdmin(admin.ModelAdmin):
    list_display = ('project', 'flat_no', 'floor_no', 'flat_type', 'facing', 'status', 'base_price')
    list_filter = ('status', 'flat_type', 'project')
    search_fields = ('flat_no', 'project__project_name')
