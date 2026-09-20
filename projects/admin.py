from django.contrib import admin

from .models import Apartment, Project


class ApartmentInline(admin.TabularInline):
    model = Apartment
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('project_code', 'project_name', 'status', 'floor_no', 'total_saleable_area')
    search_fields = ('project_code', 'project_name', 'location')
    list_filter = ('status',)
    inlines = [ApartmentInline]


@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = ('project', 'apartment_no', 'floor_no', 'apartment_type', 'status', 'base_price')
    list_filter = ('status', 'apartment_type', 'project')
    search_fields = ('apartment_no', 'project__project_name')
