"""Punto único de escritura del módulo: permisos, transacciones y auditoría."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from usuarios.permisos import es_administrador

from .models import Pendiente, PendienteHistorial


CAMPOS_EDITABLES = (
    "titulo", "detalle", "area", "tda", "categoria", "tipo_trabajo", "prioridad",
    "responsable", "solicitante", "canal", "estado", "bloqueo", "bloqueado_por",
    "siguiente_accion", "fecha_compromiso", "frecuencia",
)
EVENTOS = {
    "estado": "ESTADO", "responsable": "RESPONSABLE", "fecha_compromiso": "COMPROMISO",
    "prioridad": "PRIORIDAD", "bloqueo": "BLOQUEO", "bloqueado_por": "BLOQUEO",
    "siguiente_accion": "SIGUIENTE_ACCION",
}


def _exigir_admin(usuario):
    if not es_administrador(usuario):
        raise PermissionDenied


def _valor(pendiente, campo):
    valor = getattr(pendiente, campo)
    if valor is None or valor == "":
        return "Sin definir"
    if campo == "responsable":
        return f"{valor.pk} · {valor.get_full_name() or valor.username}"
    if campo == "tda":
        return valor.nombre
    display = getattr(pendiente, f"get_{campo}_display", None)
    return str(display() if display else valor)


@transaction.atomic
def crear_pendiente(*, usuario, datos):
    _exigir_admin(usuario)
    valores = {campo: datos[campo] for campo in CAMPOS_EDITABLES if campo in datos}
    valores.update(estado=Pendiente.Estado.PENDIENTE, bloqueo=Pendiente.Bloqueo.SIN_BLOQUEO,
                   bloqueado_por="", frecuencia=Pendiente.Frecuencia.UNICA)
    pendiente = Pendiente(creado_por=usuario, **valores)
    pendiente.full_clean(exclude=["folio"])
    pendiente.save()
    PendienteHistorial.objects.create(
        pendiente=pendiente, usuario=usuario, tipo_evento="CREACION",
        valor_nuevo=pendiente.titulo, comentario="Pendiente registrado.",
    )
    return pendiente


@transaction.atomic
def actualizar_pendiente(*, pendiente_id, usuario, datos, comentario="", version=None):
    _exigir_admin(usuario)
    pendiente = Pendiente.objects.select_for_update().get(pk=pendiente_id)
    if version is not None and version != pendiente.ultima_actualizacion:
        raise ValidationError("Otro administrador actualizó este pendiente. Recarga la página antes de guardar.")
    estado_anterior = pendiente.estado
    cambios = []
    for campo in CAMPOS_EDITABLES:
        if campo in datos and getattr(pendiente, campo) != datos[campo]:
            anterior = _valor(pendiente, campo)
            setattr(pendiente, campo, datos[campo])
            cambios.append((campo, anterior, _valor(pendiente, campo)))
    pendiente.full_clean()
    ahora = timezone.now()
    cambio_estado = estado_anterior != pendiente.estado
    if cambio_estado:
        if estado_anterior == Pendiente.Estado.PENDIENTE and pendiente.estado in (
            Pendiente.Estado.EN_CURSO, Pendiente.Estado.EN_ESPERA
        ) and pendiente.fecha_atencion_inicial is None:
            pendiente.fecha_atencion_inicial = ahora
        if pendiente.estado == Pendiente.Estado.COMPLETADO:
            pendiente.fecha_cierre = ahora
        elif estado_anterior == Pendiente.Estado.COMPLETADO:
            # Cada cierre previo permanece en el historial; las métricas vuelven a correr.
            pendiente.fecha_cierre = None
    if not cambios and not comentario.strip():
        return pendiente
    pendiente.save()
    for campo, anterior, nuevo in cambios:
        PendienteHistorial.objects.create(
            pendiente=pendiente, usuario=usuario, tipo_evento=EVENTOS.get(campo, "EDICION"),
            valor_anterior=anterior, valor_nuevo=nuevo,
            comentario=f"{Pendiente._meta.get_field(campo).verbose_name}: {comentario.strip()}".strip(),
            fecha=ahora,
        )
    evento = None
    if cambio_estado:
        if pendiente.estado == Pendiente.Estado.COMPLETADO:
            evento = "CIERRE"
        elif pendiente.estado == Pendiente.Estado.CANCELADO:
            evento = "CANCELACION"
        elif estado_anterior in Pendiente.ESTADOS_TERMINALES:
            evento = "REAPERTURA"
    if evento:
        PendienteHistorial.objects.create(
            pendiente=pendiente, usuario=usuario, tipo_evento=evento,
            valor_anterior=estado_anterior, valor_nuevo=pendiente.estado,
            comentario=comentario.strip(), fecha=ahora,
        )
    elif not cambios and comentario.strip():
        PendienteHistorial.objects.create(
            pendiente=pendiente, usuario=usuario, tipo_evento="COMENTARIO",
            comentario=comentario.strip(), fecha=ahora,
        )
    return pendiente
