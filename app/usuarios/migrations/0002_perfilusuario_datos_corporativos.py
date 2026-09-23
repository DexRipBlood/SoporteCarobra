from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilusuario",
            name="area",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="área o departamento",
            ),
        ),
        migrations.AddField(
            model_name="perfilusuario",
            name="cargo",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="perfilusuario",
            name="numero_empleado",
            field=models.CharField(
                blank=True,
                max_length=40,
                verbose_name="número de empleado",
            ),
        ),
        migrations.AddField(
            model_name="perfilusuario",
            name="telefono",
            field=models.CharField(
                blank=True,
                max_length=30,
                verbose_name="teléfono",
            ),
        ),
    ]
