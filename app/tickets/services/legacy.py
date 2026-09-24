"""Reglas puras y explícitas para recibir tickets del sistema legacy."""
from dataclasses import dataclass
import re
import unicodedata
from typing import Optional

from tickets.models import EstadoTicket, SegmentoSLA


@dataclass(frozen=True)
class TraduccionEstadoLegacy:
    """Resultado auditable de traducir un estado del sistema anterior."""

    estado: Optional[EstadoTicket]
    requiere_revision: bool = False
    advertencia: Optional[str] = None


@dataclass(frozen=True)
class InicioSLALegacy:
    """Configuración del primer segmento posterior al corte."""

    tipo: SegmentoSLA.Tipo
    cuenta_sla: bool


def _normalizar_estado(valor):
    texto = "" if valor is None else str(valor)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = texto.casefold().strip()
    texto = re.sub(r"[()\[\]{}]", " ", texto)
    return " ".join(texto.split())


def traducir_estado_legacy(estado_original, *, tiene_responsable=False, tiene_actividad=False):
    """Traduce un estado legacy sin adivinar los valores desconocidos.

    Para ``Abierto`` y ``Pendiente`` se usa el contexto operativo disponible.
    Los estados no reconocidos devuelven ``estado=None`` para que el futuro
    importador los marque para revisión en vez de abrir un SLA por accidente.
    """
    estado = _normalizar_estado(estado_original)
    directos = {
        "nuevo": EstadoTicket.NUEVO,
        "asignado": EstadoTicket.ASIGNADO,
        "en curso": EstadoTicket.EN_PROCESO,
        "en curso asignada": EstadoTicket.EN_PROCESO,
        "en proceso": EstadoTicket.EN_PROCESO,
        "en seguimiento": EstadoTicket.EN_PROCESO,
        "seguimiento": EstadoTicket.EN_PROCESO,
        "en espera": EstadoTicket.EN_ESPERA,
        "en observacion": EstadoTicket.RESUELTO,
        "resuelto": EstadoTicket.RESUELTO,
        "cerrado": EstadoTicket.CERRADO,
    }
    if estado in directos:
        return TraduccionEstadoLegacy(estado=directos[estado])

    if estado in {"abierto", "pendiente"}:
        if tiene_actividad:
            return TraduccionEstadoLegacy(estado=EstadoTicket.EN_PROCESO)
        if tiene_responsable:
            return TraduccionEstadoLegacy(estado=EstadoTicket.ASIGNADO)
        return TraduccionEstadoLegacy(estado=EstadoTicket.NUEVO)

    mostrado = str(estado_original or "").strip() or "(vacío)"
    return TraduccionEstadoLegacy(
        estado=None,
        requiere_revision=True,
        advertencia=f"Estado legacy no reconocido: {mostrado}",
    )


def configuracion_inicio_sla_legacy(estado):
    """Indica el único tipo de segmento permitido al iniciar tras el corte."""
    try:
        estado = EstadoTicket(estado)
    except ValueError:
        return None

    if estado in {EstadoTicket.NUEVO, EstadoTicket.ASIGNADO, EstadoTicket.EN_PROCESO}:
        return InicioSLALegacy(tipo=SegmentoSLA.Tipo.ATENCION, cuenta_sla=True)
    if estado == EstadoTicket.EN_ESPERA:
        return InicioSLALegacy(tipo=SegmentoSLA.Tipo.PAUSA, cuenta_sla=False)
    return None


def inicializar_sla_legacy(ticket):
    """Crea, de forma idempotente, el primer segmento posterior al corte.

    Esta ruta no usa las validaciones interactivas de seguimiento: un ticket
    legacy en espera puede no traer todavía el detalle de la espera.
    """
    if ticket.legacy_cutover_at is None:
        raise ValueError("Un ticket legacy requiere legacy_cutover_at.")

    configuracion = configuracion_inicio_sla_legacy(ticket.estado_interno)
    abierto = ticket.segmentos_sla.filter(fin__isnull=True).first()
    if configuracion is None:
        if abierto:
            abierto.fin = ticket.legacy_cutover_at
            abierto.save(update_fields=["fin"])
        return None
    if abierto:
        return abierto
    if ticket.segmentos_sla.exists():
        return None

    inicio = ticket.legacy_cutover_at
    if ticket.ultima_reapertura_at and ticket.ultima_reapertura_at > inicio:
        inicio = ticket.ultima_reapertura_at

    return SegmentoSLA.objects.create(
        ticket=ticket,
        responsable=ticket.responsable,
        tipo=configuracion.tipo,
        inicio=inicio,
        cuenta_sla=configuracion.cuenta_sla,
        motivo="Inicio posterior al corte legacy.",
    )
