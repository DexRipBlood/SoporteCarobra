from django.db import migrations


def conectar(apps, schema_editor):
    Zona = apps.get_model("tickets", "Zona")
    Tienda = apps.get_model("tickets", "Tienda")
    Ticket = apps.get_model("tickets", "Ticket")
    Segmento = apps.get_model("tickets", "SegmentoSLA")
    Grupo = apps.get_model("tickets", "GrupoTrabajo")
    for zona in Zona.objects.select_related("encargado_zonal").iterator():
        if zona.encargado_zonal_id:
            persona = zona.encargado_zonal
            if persona.usuario_id:
                zona.responsable_id = persona.usuario_id
            else:
                zona.distrital_nombre = persona.nombre
                zona.distrital_telefono = persona.telefono
        if not zona.distrital_nombre:
            zona.distrital_nombre = Tienda.objects.filter(zona=zona).exclude(gerente_distrital="").values_list("gerente_distrital", flat=True).first() or ""
        zona.save(update_fields=["responsable", "distrital_nombre", "distrital_telefono"])
    agrupadas = {}
    for zona in Zona.objects.filter(activa=True).order_by("pk"):
        agrupadas.setdefault((zona.empresa_id, zona.nombre.strip().casefold()), []).append(zona)
    for zonas in agrupadas.values():
        if len(zonas) < 2:
            continue
        principal = zonas[0]
        nombres = {z.distrital_nombre.strip() for z in zonas if z.distrital_nombre.strip()}
        # Si el catálogo tiene contactos distintos, deben confirmarse manualmente.
        # Los nombres originales se conservan en tiendas y distritos históricos.
        principal.distrital_nombre = next(iter(nombres)) if len(nombres) == 1 else ""
        usuarios = {z.responsable_id for z in zonas if z.responsable_id}
        principal.responsable_id = next(iter(usuarios)) if len(usuarios) == 1 else None
        principal.estado = "Varios estados" if len({z.estado for z in zonas}) > 1 else principal.estado
        principal.save(update_fields=["distrital_nombre", "responsable", "estado"])
        enlace = Grupo.zonas.through
        for anterior in zonas[1:]:
            Tienda.objects.filter(zona_id=anterior.pk).update(zona_id=principal.pk)
            for grupo_id in enlace.objects.filter(zona_id=anterior.pk).values_list("grupotrabajo_id", flat=True):
                enlace.objects.get_or_create(grupotrabajo_id=grupo_id, zona_id=principal.pk)
            enlace.objects.filter(zona_id=anterior.pk).delete()
            anterior.activa = False
            anterior.save(update_fields=["activa"])
    for tienda in Tienda.objects.all().iterator():
        texto = f"{tienda.tipo} {tienda.nombre}".upper()
        for cadena in ("BODEGA", "PROMODA", "GCC"):
            if cadena in texto:
                tienda.cadena = cadena
                tienda.save(update_fields=["cadena"])
                break
    # En registros históricos sin segmentos solo conocemos entrada y cierre.
    # No se inventan pausas ni responsables retroactivos.
    for ticket in Ticket.objects.filter(segmentos_sla__isnull=True).iterator():
        fin = (ticket.cerrado_at or ticket.actualizado_at) if ticket.estado_interno == "CERRADO" else None
        Segmento.objects.create(ticket_id=ticket.pk, responsable_id=ticket.responsable_id,
            inicio=ticket.creado_at, fin=fin, cuenta_sla=True, tipo="ATENCION",
            motivo="Base histórica: no había periodos de pausa registrados.")


class Migration(migrations.Migration):
    dependencies = [("tickets", "0008_empresa_ubicacion_grupotrabajo_actividades_and_more")]
    operations = [migrations.RunPython(conectar, migrations.RunPython.noop)]
