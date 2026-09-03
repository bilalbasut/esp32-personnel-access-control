from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
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
            name="AccessEvent",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device_id", models.CharField(blank=True, db_index=True, max_length=50, null=True)),
                ("seq", models.IntegerField(blank=True, null=True)),
                ("uid", models.CharField(blank=True, max_length=50, null=True)),
                ("employee_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("ts_utc", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("ts_source", models.SmallIntegerField(blank=True, null=True)),
                ("dir", models.SmallIntegerField(blank=True, null=True)),
                ("result", models.SmallIntegerField(blank=True, null=True)),
                ("mode", models.SmallIntegerField(blank=True, null=True)),
                ("ingested_at", models.BigIntegerField(blank=True, null=True)),
                ("raw_payload", models.JSONField(blank=True, null=True)),
            ],
            options={"db_table": "access_events"},
        ),
        migrations.AddConstraint(
            model_name="accessevent",
            constraint=models.UniqueConstraint(fields=("device_id", "seq"), name="uniq_device_seq"),
        ),
        # Sequences used by core/acl.py (ACL version) and core/views.py
        # (in-process command seq falls back to this on restart).
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS acl_version_seq START 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS acl_version_seq;",
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS cmd_sequence START 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS cmd_sequence;",
        ),
    ]
