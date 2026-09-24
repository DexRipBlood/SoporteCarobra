"""Reglas compartidas por configuración, importación y seguimiento."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, F, Value, Sum, Subquery, DurationField, ExpressionWrapper, BooleanField, Case, When
from django.db.models.functions import Coalesce
from datetime import timedelta
from django.utils import timezone

from usuarios.permisos import es_administrador
from tickets.models import EstadoTicket, HistorialTicket, ProgramacionTrabajo, SegmentoSLA, SegmentoOperacion, Ticket


def usuario_activo(usuario):
    return bool(usuario and usuario.is_active and (usuario.is_superuser or getattr(getattr(usuario, "perfil", None), "activo", False)))


def equipo_tienda(tienda):
    if not tienda:
        return None, None
    # Las excepciones de tienda prevalecen sobre el equipo del distrito.
    responsable = tienda.encargado_soporte.usuario if tienda.encargado_soporte_id and tienda.encargado_soporte.activa else None
    partner = tienda.partner.usuario if tienda.partner_id and tienda.partner.activa else None
    responsable = responsable or tienda.zona.responsable
    partner = partner or tienda.zona.partner
    return responsable if usuario_activo(responsable) else None, partner if usuario_activo(partner) and partner != responsable else None


def disponibilidad(usuario, ticket=None, ahora=None):
    if not usuario_activo(usuario):
        return False, "Sin usuario activo"
    ahora = timezone.localtime(ahora or timezone.now())
    turnos = list(ProgramacionTrabajo.objects.filter(
        usuario=usuario, fecha_inicio__lte=ahora.date(), fecha_fin__gte=ahora.date(),
    ).select_related("grupo").prefetch_related("grupo__miembros", "grupo__incidencias"))
    if not turnos:
        return False, "Sin horario registrado hoy"
    for turno in turnos:
        if turno.modalidad in ("AUSENTE", "DESCANSO"):
            if turno.hora_inicio <= ahora.time() < turno.hora_fin:
                return False, turno.get_modalidad_display()
    for turno in turnos:
        if not turno.hora_inicio <= ahora.time() < turno.hora_fin or turno.modalidad in ("AUSENTE", "DESCANSO"):
            continue
        grupo = turno.grupo
        if grupo:
            if not grupo.activo or not grupo.atiende_tickets:
                continue
            if not any(m.usuario_id == usuario.pk and m.activa for m in grupo.miembros.all()):
                continue
            if ticket and ticket.empresa_id and grupo.empresa_id != ticket.empresa_id:
                continue
            reglas = list(grupo.incidencias.all())
            if ticket and reglas and not any(r.activo and r.categoria.casefold() == ticket.categoria.casefold() and (
                not r.incidencia_general or r.incidencia_general.casefold() == ticket.incidencia_general.casefold()
            ) for r in reglas):
                continue
        return True, turno.get_modalidad_display()
    return False, "Fuera de horario o asignado a otra actividad"


def seguimiento_actual(ticket, ahora=None, cache=None):
    ahora = ahora or timezone.now()
    if ticket.estado_interno == EstadoTicket.CERRADO:
        return {"atiende": None, "requiere_admin": False, "detalle": "Ticket cerrado"}
    if ticket.suplente_id and ticket.suplente_hasta and ticket.suplente_hasta > ahora and usuario_activo(ticket.suplente):
        return {"atiende": ticket.suplente, "requiere_admin": ticket.solicitud_admin, "detalle": "Suplencia asignada por administración"}
    motivos = []
    for usuario in (ticket.responsable, ticket.partner):
        clave = (usuario.pk if usuario else None, ticket.empresa_id, ticket.categoria, ticket.incidencia_general)
        if cache is not None and clave in cache:
            disponible, motivo = cache[clave]
        else:
            disponible, motivo = disponibilidad(usuario, ticket, ahora)
            if cache is not None:
                cache[clave] = disponible, motivo
        if disponible:
            return {"atiende": usuario, "requiere_admin": ticket.solicitud_admin, "detalle": motivo}
        motivos.append(motivo)
    return {"atiende": None, "requiere_admin": True, "detalle": " / ".join(motivos)}


def requieren_administracion(queryset, ahora=None):
    """Bandeja viva: descansos y suplencias vencidas se reflejan sin tarea programada."""
    ahora = timezone.localtime(ahora or timezone.now())
    def turnos(campo):
        return ProgramacionTrabajo.objects.filter(
            usuario_id=OuterRef(campo), usuario__is_active=True,
            fecha_inicio__lte=ahora.date(), fecha_fin__gte=ahora.date(),
            hora_inicio__lte=ahora.time(), hora_fin__gt=ahora.time(),
        ).filter(Q(usuario__is_superuser=True) | Q(usuario__perfil__activo=True)).exclude(
            modalidad__in=["AUSENTE", "DESCANSO"]
        ).filter(Q(grupo__isnull=True) | (
            Q(grupo__activo=True, grupo__atiende_tickets=True,
              grupo__empresa_id=OuterRef("empresa_id"), grupo__miembros__usuario_id=OuterRef(campo), grupo__miembros__activa=True)
            & (Q(grupo__incidencias__isnull=True) | (Q(grupo__incidencias__activo=True, grupo__incidencias__categoria__iexact=OuterRef("categoria"))
                & (Q(grupo__incidencias__incidencia_general="") | Q(grupo__incidencias__incidencia_general__iexact=OuterRef("incidencia_general")))))
        ))
    return queryset.exclude(estado_interno=EstadoTicket.CERRADO).annotate(
        encargado_disponible=Exists(turnos("responsable_id")),
        partner_disponible=Exists(turnos("partner_id")),
    ).filter(Q(solicitud_admin=True) | (Q(encargado_disponible=False, partner_disponible=False) & (
        Q(suplente__isnull=True) | Q(suplente_hasta__isnull=True) | Q(suplente_hasta__lte=ahora) | Q(suplente__is_active=False)
    )))


def evento(ticket, usuario, tipo, descripcion, antes=None, despues=None, ahora=None):
    return HistorialTicket.objects.create(ticket=ticket, usuario=usuario, evento=tipo,
        origen="USUARIO" if usuario else "SISTEMA", descripcion=descripcion,
        valor_anterior=antes or {}, valor_nuevo=despues or {}, creado_at=ahora or timezone.now())


def iniciar_sla(ticket):
    if ticket.legacy_cutover_at is not None:
        from tickets.services.legacy import inicializar_sla_legacy
        return inicializar_sla_legacy(ticket)
    if not ticket.segmentos_sla.exists():
        SegmentoSLA.objects.create(ticket=ticket, responsable=ticket.responsable,
            inicio=ticket.creado_at, fin=ticket.cerrado_at if ticket.estado_interno == EstadoTicket.CERRADO else None,
            cuenta_sla=True)


def registrar_segmento_operativo(ticket, ahora=None):
    """Cierra/abre el periodo cuando cambia la condición de operación."""
    ahora = ahora or timezone.now()
    actual = ticket.segmentos_operacion.filter(fin__isnull=True).first()
    if actual and actual.estatus_operativo_id == ticket.estatus_operativo_actual_id and actual.dependencia_id == ticket.dependencia_actual_id:
        return actual
    if actual:
        actual.fin = ahora
        actual.save(update_fields=["fin"])
    return SegmentoOperacion.objects.create(ticket=ticket, estatus_operativo=ticket.estatus_operativo_actual, dependencia=ticket.dependencia_actual, inicio=ahora)


def resumen_sla(ticket, ahora=None):
    ahora = ahora or timezone.now()
    segmentos = list(ticket.segmentos_sla.all())
    efectivo_segmentos = pausa = 0
    for segmento in segmentos:
        segundos = max(0, int(((segmento.fin or ahora) - segmento.inicio).total_seconds()))
        if segmento.cuenta_sla:
            efectivo_segmentos += segundos
        else:
            pausa += segundos
    if not segmentos and ticket.legacy_cutover_at is None:
        efectivo_segmentos = max(0, int(((ticket.cerrado_at or ahora) - ticket.creado_at).total_seconds()))
    # El saldo legacy se incorpora sólo aquí, al calcular el total efectivo;
    # nunca se materializa como un SegmentoSLA ficticio.
    efectivo = ticket.sla_legacy_segundos + efectivo_segmentos
    limite = ticket.sla_limite_minutos * 60 if ticket.sla_limite_minutos is not None else None
    restante = max(0, limite - efectivo) if limite is not None else None
    excedido_por = max(0, efectivo - limite) if limite is not None else 0
    excedido = ticket.sla_excedido or (limite is not None and efectivo > limite)
    return {"cerrado": ticket.estado_interno == EstadoTicket.CERRADO, "efectivo": efectivo, "pausa": pausa, "total": max(0, int(((ticket.cerrado_at or ahora) - ticket.creado_at).total_seconds())),
        "primera_atencion": max(0, int((ticket.primer_comentario_at - ticket.creado_at).total_seconds())) if ticket.primer_comentario_at else None,
        "restante": restante, "limite": limite, "excedido": excedido,
        "excedido_por": excedido_por,
        "pausado": any(not s.cuenta_sla and s.fin is None for s in segmentos),
        "corriendo": ticket.estado_interno != EstadoTicket.CERRADO and not any(not s.cuenta_sla and s.fin is None for s in segmentos)}


def con_sla_actual(queryset):
    duracion = ExpressionWrapper(Coalesce(F("fin"), Value(timezone.now())) - F("inicio"), output_field=DurationField())
    segmentos = SegmentoSLA.objects.filter(ticket_id=OuterRef("pk"), cuenta_sla=True).order_by().values("ticket_id").annotate(total=Sum(duracion)).values("total")
    saldo_legacy = ExpressionWrapper(
        F("sla_legacy_segundos") * Value(timedelta(seconds=1)),
        output_field=DurationField(),
    )
    return queryset.annotate(
        duracion_sla_actual=ExpressionWrapper(
            Coalesce(Subquery(segmentos, output_field=DurationField()), Value(timedelta()))
            + saldo_legacy,
            output_field=DurationField(),
        ),
        limite_sla_actual=ExpressionWrapper(F("sla_limite_minutos") * Value(timedelta(minutes=1)), output_field=DurationField()),
    ).annotate(sla_vencido_actual=Case(When(Q(sla_excedido=True) | Q(duracion_sla_actual__gt=F("limite_sla_actual")), then=Value(True)), default=Value(False), output_field=BooleanField()))


def sincronizar_sla(ticket, usuario=None, ahora=None):
    """Invocar dentro de la transacción que ya bloqueó el ticket."""
    ahora = ahora or timezone.now()
    iniciar_sla(ticket)
    actual = ticket.segmentos_sla.filter(fin__isnull=True).first()
    pausa = ticket.estado_interno == EstadoTicket.EN_ESPERA and (
        ticket.legacy_cutover_at is not None
        or bool(ticket.motivo_espera.strip() and ticket.esperando_a.strip() and ticket.siguiente_accion.strip())
    )
    cerrar = ticket.estado_interno == EstadoTicket.CERRADO or (
        ticket.legacy_cutover_at is not None
        and ticket.estado_interno == EstadoTicket.RESUELTO
    )
    if actual and (cerrar or actual.cuenta_sla == pausa):
        actual.fin = ahora
        actual.save(update_fields=["fin"])
        actual = None
    if actual is None and not cerrar:
        SegmentoSLA.objects.create(ticket=ticket, responsable=ticket.responsable,
            inicio=ahora, cuenta_sla=not pausa, tipo="PAUSA" if pausa else "ATENCION",
            motivo=ticket.motivo_espera if pausa else "Seguimiento interno")
        evento(ticket, usuario, "PAUSA_SLA" if pausa else "REANUDACION_SLA",
               "Pausa justificada por tercero." if pausa else "El SLA continúa contabilizando atención.", ahora=ahora)
    resumen = resumen_sla(ticket, ahora)
    if resumen["excedido"] and not ticket.sla_excedido:
        ticket.sla_excedido = True
        ticket.sla_excedido_at = ahora
        evento(
            ticket,
            usuario,
            "SLA_EXCEDIDO",
            "Se superó el tiempo configurado.",
            despues={
                "tiempo_excedido": resumen["excedido_por"],
                "tiempo_efectivo": resumen["efectivo"],
                "tiempo_permitido": resumen["limite"],
            },
            ahora=ahora,
        )
    ticket.sla_segundos_acumulados = resumen["efectivo"]
    ticket.save(update_fields=["sla_segundos_acumulados", "sla_excedido", "sla_excedido_at"])


def permiso_ticket(usuario, nombre):
    return es_administrador(usuario) or (usuario_activo(usuario) and getattr(usuario.perfil, nombre, False))


@transaction.atomic
def cambiar_seguimiento(ticket_id, usuario, datos):
    from tickets.permisos import tickets_visibles_para, participa_en_ticket
    if not tickets_visibles_para(usuario).filter(pk=ticket_id).exists() or not permiso_ticket(usuario, "puede_seguimiento"):
        raise PermissionDenied
    ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    if not participa_en_ticket(usuario, ticket):
        raise PermissionDenied
    if ticket.estado_interno == EstadoTicket.CERRADO:
        raise ValidationError("El ticket está cerrado; un administrador debe reabrirlo primero.")
    estado = datos["estado"]
    if estado not in (EstadoTicket.ASIGNADO, EstadoTicket.EN_PROCESO, EstadoTicket.EN_ESPERA, EstadoTicket.RESUELTO):
        raise ValidationError("Usa el cierre documentado para cerrar el ticket.")
    if estado == EstadoTicket.EN_ESPERA and not all(datos.get(k, "").strip() for k in ("motivo_espera", "esperando_a", "siguiente_accion")):
        raise ValidationError("Para esperar a un tercero indica el motivo, a quién esperas y la siguiente acción.")
    antes = {k: getattr(ticket, k) for k in ("estado_interno", "motivo_espera", "esperando_a", "siguiente_accion")}
    ticket.estado_interno = estado
    for campo in ("motivo_espera", "esperando_a", "siguiente_accion"):
        setattr(ticket, campo, datos.get(campo, "").strip())
    ahora = timezone.now()
    if ticket.primer_comentario_at is None and estado in (EstadoTicket.EN_PROCESO, EstadoTicket.EN_ESPERA, EstadoTicket.RESUELTO):
        ticket.primer_comentario_at = ahora
    if estado == EstadoTicket.RESUELTO:
        ticket.resuelto_at = ahora
    ticket.save()
    sincronizar_sla(ticket, usuario, ahora)
    evento(ticket, usuario, "ESTADO", "Seguimiento actualizado.", antes, {
        k: getattr(ticket, k) for k in antes}, ahora)
    return ticket
