import re

from django.db import migrations, models


def recuperar_ciudad(apps, schema_editor):
    Tienda = apps.get_model("tickets", "Tienda")
    patron = re.compile(r"\b\d{5}\s*,?\s+([^,]+)", re.IGNORECASE)
    for tienda in Tienda.objects.exclude(direccion="").only("pk", "direccion").iterator():
        coincidencia = patron.search(tienda.direccion or "")
        if coincidencia:
            ciudad = coincidencia.group(1).strip(" .;-")[:140]
            if ciudad:
                Tienda.objects.filter(pk=tienda.pk).update(ciudad=ciudad)


class Migration(migrations.Migration):
    dependencies = [("tickets", "0010_sincronizar_tipo_tienda_desde_socio")]
    operations = [
        migrations.AddField(
            model_name="tienda",
            name="ciudad",
            field=models.CharField(blank=True, db_index=True, max_length=140, verbose_name="Ciudad o localidad"),
        ),
        migrations.RunPython(recuperar_ciudad, migrations.RunPython.noop),
    ]
