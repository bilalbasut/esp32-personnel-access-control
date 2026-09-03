"""
State-only migration: Employee, Device and Card used to live in `core`
(created there by 0001_initial) but the model *code* has since moved to the
`cards` and `devices` apps, with `managed = False` because these tables are
still owned by 0001_initial's CreateModel operations (or, for a database
that predates Django entirely, by the original Node.js schema) — nothing
here should ever re-create or drop them.

Before this migration, core/models.py no longer defined Employee/Device/Card
at all, but Django's recorded migration state (used by `makemigrations` to
diff against current models.py) still had them under app label "core". That
mismatch meant the *next* unrelated `makemigrations` run — for any app —
would see Employee/Device/Card as "deleted from core" and offer to
autogenerate migrations that DROP those tables, without anything to
recreate them (their new homes are unmanaged). If that offered migration
were ever applied, it would be real, unrecoverable data loss.

This migration closes that gap by moving just the *migration state* for
these three models out of `core`, using `SeparateDatabaseAndState` so
`database_operations` stays empty — no SQL runs, no table is touched.
`cards/migrations/0001_initial.py` and `devices/migrations/0001_initial.py`
(both depending on this migration) re-create the matching state on the
receiving side. Also brings Firmware/AccessEvent's recorded state in line
with their current `managed = False` (a state-only AlterModelOptions, again
with no DB effect) so a future `makemigrations` reports "No changes
detected" instead of proposing anything for those two either.

Safe to run against an already-provisioned production database: every
operation below is state-only.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="Employee"),
                migrations.DeleteModel(name="Device"),
                migrations.DeleteModel(name="Card"),
            ],
            database_operations=[],
        ),
        migrations.AlterModelOptions(
            name="firmware",
            options={"managed": False},
        ),
        migrations.AlterModelOptions(
            name="accessevent",
            options={"managed": False},
        ),
    ]
