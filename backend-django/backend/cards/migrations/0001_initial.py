"""
State-only counterpart to core/migrations/0002_move_legacy_models_to_new_apps.py.

Recreates Employee and Card in this app's recorded migration state, matching
where cards/models.py has actually put them (both `managed = False`, same
`db_table` names as before). `database_operations=[]` — the tables already
exist (created by core's 0001_initial, or by the original Node.js schema)
and are not owned by this app's migrations.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("core", "0002_move_legacy_models_to_new_apps"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Employee",
                    fields=[
                        ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("ad_soyad", models.CharField(blank=True, max_length=255, null=True)),
                        ("departman", models.CharField(blank=True, max_length=100, null=True)),
                        ("aktif", models.SmallIntegerField(default=1)),
                    ],
                    options={"db_table": "employees", "managed": False},
                ),
                migrations.CreateModel(
                    name="Card",
                    fields=[
                        ("uid", models.CharField(max_length=50, primary_key=True, serialize=False)),
                        ("floors", models.CharField(blank=True, max_length=100, null=True)),
                        ("valid_from", models.BigIntegerField(blank=True, null=True)),
                        ("valid_to", models.BigIntegerField(blank=True, null=True)),
                        ("win_start_m", models.SmallIntegerField(default=0)),
                        ("win_end_m", models.SmallIntegerField(default=1440)),
                        ("aktif", models.SmallIntegerField(default=1)),
                        (
                            "employee",
                            models.ForeignKey(
                                blank=True,
                                db_column="employee_id",
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="cards",
                                to="cards.employee",
                            ),
                        ),
                    ],
                    options={"db_table": "cards", "managed": False},
                ),
            ],
            database_operations=[],
        ),
    ]
