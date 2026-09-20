from django.db import models


class Sequence(models.Model):
    """Backing counter for atomic, gap-free document/code numbering.

    One row per numbering series (e.g. "project:26AB", "sale:AB/2026").
    next_number() below locks the row so concurrent requests can't hand
    out the same number — the bug inspcta's count()+1 approach has.
    """
    key = models.CharField(max_length=64, unique=True)
    last_number = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.key} -> {self.last_number}"
