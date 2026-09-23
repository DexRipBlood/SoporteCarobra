from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("tickets", "0011_tienda_ciudad")]
    operations = [
        migrations.CreateModel(
            name="SegmentoOperacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("inicio", models.DateTimeField(db_index=True)),
                ("fin", models.DateTimeField(blank=True, null=True)),
                ("creado_at", models.DateTimeField(auto_now_add=True)),
                ("dependencia", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="segmentos_operacion", to="tickets.dependencia")),
                ("estatus_operativo", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="segmentos_operacion", to="tickets.estatusoperativo")),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="segmentos_operacion", to="tickets.ticket")),
            ],
            options={"ordering": ["inicio"]},
        ),
        migrations.AddConstraint(model_name="segmentooperacion", constraint=models.UniqueConstraint(condition=models.Q(("fin__isnull", True)), fields=("ticket",), name="uq_operacion_segmento_abierto")),
    ]
