"""Datos reales y consistentes para los paneles de resumen."""

from django.db.models import Q

from tickets.models import EstadoTicket, HistorialTicket
from tickets.services.operacion import resumen_sla


def resumen_dashboard(tickets, limite_actividad=6):
    """Calcula el resumen sobre el queryset que el usuario puede consultar.

    El SLA se evalúa con la misma regla que usa el detalle del ticket, para que
    el dashboard no presente un estado distinto al de la operación diaria.
    """
    tickets = tickets.select_related("responsable")
    activos = tickets.exclude(estado_interno=EstadoTicket.CERRADO)
    activos_lista = list(activos)

    en_tiempo = en_riesgo = excedidos = 0
    for ticket in activos_lista:
        sla = resumen_sla(ticket)
        if sla["excedido"]:
            excedidos += 1
        elif sla["limite"] and sla["efectivo"] >= sla["limite"] * 0.8:
            en_riesgo += 1
        else:
            en_tiempo += 1

    actividad = HistorialTicket.objects.filter(ticket__in=tickets).select_related(
        "ticket", "usuario"
    ).order_by("-creado_at")[:limite_actividad]

    return {
        "activos": len(activos_lista),
        "en_proceso": sum(
            ticket.estado_interno == EstadoTicket.EN_PROCESO
            for ticket in activos_lista
        ),
        "sin_asignar": sum(ticket.responsable_id is None for ticket in activos_lista),
        "en_tiempo": en_tiempo,
        "en_riesgo": en_riesgo,
        "excedidos": excedidos,
        "actividad": actividad,
    }
