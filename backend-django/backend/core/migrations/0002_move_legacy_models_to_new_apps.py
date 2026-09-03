"""
No longer needed - superseded by the clean managed=True rewrite of
core/migrations/0001_initial.py, cards/migrations/0001_initial.py and
devices/migrations/0001_initial.py (Employee/Device/Card now live in their
final apps from the start, so there's no cross-app "move" left to record).

Left as an empty no-op (rather than deleted) because this tool can't delete
files on your machine right now - safe to delete this file by hand, it does
nothing.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = []
