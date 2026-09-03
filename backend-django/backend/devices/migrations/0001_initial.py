from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Device",
            fields=[
                ("id", models.CharField(max_length=50, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(blank=True, max_length=100, null=True)),
                ("floor", models.IntegerField(blank=True, null=True)),
                ("last_seen_at", models.BigIntegerField(blank=True, null=True)),
                ("status", models.CharField(blank=True, max_length=50, null=True)),
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
    ]
