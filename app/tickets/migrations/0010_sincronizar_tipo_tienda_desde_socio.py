import unicodedata

from django.db import migrations


def sincronizar(apps, schema_editor):
    Tienda = apps.get_model("tickets", "Tienda")
    for tienda in Tienda.objects.only("pk", "socio", "cadena").iterator():
        texto = unicodedata.normalize("NFKD", str(tienda.socio or ""))
        texto = "".join(c for c in texto if not unicodedata.combining(c)).upper()
        cadena = next((valor for valor in ("BODEGA", "PROMODA", "GCC") if valor in texto), "OTRA")
        if tienda.cadena != cadena:
            Tienda.objects.filter(pk=tienda.pk).update(cadena=cadena)


class Migration(migrations.Migration):
    dependencies = [("tickets", "0009_conectar_distritos_y_sla")]
    operations = [migrations.RunPython(sincronizar, migrations.RunPython.noop)]
