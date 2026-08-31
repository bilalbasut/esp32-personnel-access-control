from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Employee",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ad_soyad", models.CharField(blank=True, max_length=255, null=True)),
                ("departman", models.CharField(blank=True, max_length=100, null=True)),
                ("aktif", models.SmallIntegerField(default=1)),
            ],
            options={"db_table": "employees"},
        ),
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
            options={"db_table": "devices"},
        ),
        migrations.CreateModel(
            name="Firmware",
            fields=[
                ("version", models.CharField(max_length=50, primary_key=True, serialize=False)),
                ("filename", models.CharField(max_length=255)),
                ("md5", models.CharField(max_length=32)),
                ("size", models.IntegerField()),
                ("uploaded_at", models.BigIntegerField(blank=True, null=True)),
            ],
            options={"db_table": "firmware"},
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
                        to="core.employee",
                    ),
                ),
            ],
            options={"db_table": "cards"},
        ),
        migrations.CreateModel(
            name="AccessEvent",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device_id", models.CharField(blank=True, max_length=50, null=True)),
                ("seq", models.IntegerField(blank=True, null=True)),
                ("uid", models.CharField(blank=True, max_length=50, null=True)),
                ("employee_id", models.IntegerField(blank=True, null=True)),
                ("ts_utc", models.BigIntegerField(blank=True, null=True)),
                ("ts_source", models.SmallIntegerField(blank=True, null=True)),
                ("dir", models.SmallIntegerField(blank=True, null=True)),
                ("result", models.SmallIntegerField(blank=True, null=True)),
                ("mode", models.SmallIntegerField(blank=True, null=True)),
                ("alindi_at", models.BigIntegerField(blank=True, null=True)),
            ],
            options={"db_table": "access_events"},
        ),
        migrations.AddConstraint(
            model_name="accessevent",
            constraint=models.UniqueConstraint(fields=("device_id", "seq"), name="uniq_device_seq"),
        ),
        # Sequences used by core/acl.py (ACL version) and core/views.py
        # (in-process command seq falls back to this on restart) - mirrors
        # db.js's CREATE SEQUENCE IF NOT EXISTS acl_version_seq / cmd_sequence.
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS acl_version_seq START 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS acl_version_seq;",
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS cmd_sequence START 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS cmd_sequence;",
        ),
    ]
