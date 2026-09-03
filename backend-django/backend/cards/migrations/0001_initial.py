import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Employee",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("full_name", models.CharField(blank=True, max_length=255, null=True)),
                ("department", models.CharField(blank=True, max_length=100, null=True)),
                ("employee_no", models.CharField(blank=True, max_length=50, null=True, unique=True)),
                ("email", models.EmailField(blank=True, max_length=254, null=True)),
                ("phone", models.CharField(blank=True, max_length=30, null=True)),
            ],
            options={"db_table": "employees", "base_manager_name": "all_objects"},
            managers=[
                ("objects", django.db.models.manager.Manager()),
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name="Card",
            fields=[
                ("uid", models.CharField(max_length=50, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("floors", models.CharField(blank=True, max_length=100, null=True)),
                ("valid_from", models.BigIntegerField(blank=True, null=True)),
                ("valid_to", models.BigIntegerField(blank=True, null=True)),
                ("win_start_m", models.SmallIntegerField(default=0)),
                ("win_end_m", models.SmallIntegerField(default=1440)),
                (
                    "employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cards",
                        to="cards.employee",
                    ),
                ),
            ],
            options={"db_table": "cards", "base_manager_name": "all_objects"},
            managers=[
                ("objects", django.db.models.manager.Manager()),
                ("all_objects", django.db.models.manager.Manager()),
            ],
        ),
    ]
