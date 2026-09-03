"""
State-only counterpart to core/migrations/0002_move_legacy_models_to_new_apps.py.

Recreates Device in this app's recorded migration state, matching
devices/models.py (`managed = False`, same `db_table` as before).
`database_operations=[]` — the table already exists (created by core's
0001_initial) and is not owned by this app's migrations.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("core", "0002_move_legacy_models_to_new_apps"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Device",
                    fields=[
                        ("id", models.CharField(max_length=50, primary_key=True, serialize=False)),
                        ("ad", models.CharField(blank=True, max_length=100, null=True)),
                        ("kat", models.IntegerField(blank=True, null=True)),
                        ("son_gorulme", models.BigIntegerField(blank=True, null=True)),
                        ("durum", models.CharField(blank=True, max_length=50, null=True)),
                        ("fw", models.CharField(blank=True, max_length=50, null=True)),
                        ("queue_depth", models.IntegerField(blank=True, null=True)),
                        ("heap_free", models.IntegerField(blank=True, null=True)),
                        ("queue_overflow", models.IntegerField(blank=True, null=True)),
                        ("uptime_s", models.BigIntegerField(blank=True, null=True)),
                        ("ota_status", models.CharField(blank=True, max_length=50, null=True)),
                        ("ota_updated_at", models.BigIntegerField(blank=True, null=True)),
                    ],
                    options={"db_table": "devices", "managed": False},
                ),
            ],
            database_operations=[],
        ),
    ]
