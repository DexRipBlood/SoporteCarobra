from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def clasificar_y_asignar_partner(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")

    Ticket.objects.exclude(ticket_bradescard__isnull=True).exclude(
        ticket_bradescard=""
    ).update(origen="BRADESCARD")

    for ticket in Ticket.objects.filter(
        partner__isnull=True,
        tienda_registrada__partner__usuario__isnull=False,
    ).select_related("tienda_registrada__partner"):
        ticket.partner_id = ticket.tienda_registrada.partner.usuario_id
        ticket.save(update_fields=["partner"])


def revertir_clasificacion(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    Ticket.objects.update(origen="CAROBRA", partner=None)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0005_tienda_agencia_tienda_clave_tienda_coordinador_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="origen",
            field=models.CharField(
                choices=[("CAROBRA", "CAROBRA"), ("BRADESCARD", "Bradescard")],
                db_index=True,
                default="CAROBRA",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="partner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tickets_como_partner",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(
            clasificar_y_asignar_partner,
            revertir_clasificacion,
        ),
        migrations.AlterField(
            model_name="historialticket",
            name="evento",
            field=models.CharField(
                choices=[
                    ("CREADO", "Ticket creado"),
                    ("IMPORTADO", "Ticket importado"),
                    ("ACTUALIZADO_IMPORTACION", "Actualizado por importación"),
                    ("ASIGNADO", "Asignado"),
                    ("PRIMER_COMENTARIO", "Primer comentario"),
                    ("COMENTARIO", "Comentario"),
                    ("ARCHIVO", "Archivo agregado"),
                    ("ESTADO", "Cambio de estado"),
                    ("PRIORIDAD", "Cambio de prioridad"),
                    ("PARTNER", "Cambio de partner"),
                    ("GRUPO", "Cambio de grupo"),
                    ("SUBGRUPO", "Cambio de subgrupo"),
                    ("DEPENDENCIA", "Cambio de dependencia"),
                    ("ESTATUS_OPERATIVO", "Cambio de estatus operativo"),
                    ("PAUSA_SLA", "Pausa SLA"),
                    ("REANUDACION_SLA", "Reanudación SLA"),
                    ("SLA_EXCEDIDO", "SLA excedido"),
                    ("RESUELTO", "Resuelto"),
                    ("CERRADO", "Cerrado"),
                    ("REABIERTO", "Reabierto"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]
