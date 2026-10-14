"""Fix for running Django 4.2 on Python 3.14.

Django 4.2 copies a template context with `copy(super())`, which Python 3.14 no longer allows. That
crashed every page that copies a context, for example the admin user list ("'super' object has no
attribute 'dicts'"). This is the same copy Django 5 does, written without the `super()` trick, and it
behaves identically on every Python version.
"""
from copy import copy

from django.template.context import BaseContext


def _copy(self):
    duplicate = BaseContext()
    duplicate.__class__ = self.__class__
    duplicate.__dict__ = copy(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate


def patch_template_context_copy():
    BaseContext.__copy__ = _copy
