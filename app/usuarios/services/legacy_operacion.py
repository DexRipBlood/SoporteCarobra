"""Traducción auditable de la operación legacy, sin persistencia.

Este módulo prepara decisiones para un futuro importador.  Sus consultas son
de sólo lectura: no crea usuarios, coberturas, membresías ni programaciones.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import Optional

from tickets.models import (
    AsignacionPersonal,
    Empresa,
    GrupoSoporte,
    GrupoTrabajo,
    MembresiaGrupo,
    SubgrupoSoporte,
    Tienda,
    Zona,
)
from usuarios.services.legacy import proponer_rol_legacy


class EstadoResolucionLegacy(StrEnum):
    RESUELTO = "RESUELTO"
    NO_ENCONTRADA = "NO_ENCONTRADA"
    AMBIGUA = "AMBIGUA"
    REQUIERE_REVISION = "REQUIERE_REVISION"


@dataclass(frozen=True)
class ReferenciaLegacy:
    """Resultado de vincular una referencia legacy con un catálogo Django."""

    tipo: str
    valor_legacy: str
    estado: EstadoResolucionLegacy
    django_id: Optional[int] = None
    etiqueta: str = ""
    campo: Optional[str] = None
    advertencias: tuple[str, ...] = ()

    @property
    def requiere_revision(self):
        return self.estado != EstadoResolucionLegacy.RESUELTO


@dataclass(frozen=True)
class CapacidadesLegacy:
    """Capacidades propuestas; ``None`` significa SIN_DETERMINAR."""

    puede_seguimiento: Optional[bool] = None
    puede_cerrar: Optional[bool] = None
    puede_reasignar: Optional[bool] = None
    puede_ver_todos: bool = False


@dataclass(frozen=True)
class PropuestaAsignacionPersonalLegacy:
    """Datos suficientes para evaluar una futura ``AsignacionPersonal``."""

    empresa: ReferenciaLegacy
    alcance: Optional[str]
    funcion: Optional[str]
    estado: str = ""
    zona: Optional[ReferenciaLegacy] = None
    tienda: Optional[ReferenciaLegacy] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    principal: Optional[bool] = None
    requiere_revision: bool = False
    advertencias: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropuestaGrupoSoporteLegacy:
    """Clasificación/enrutamiento, nunca una membresía de equipo."""

    grupo: ReferenciaLegacy
    subgrupo: Optional[ReferenciaLegacy] = None
    requiere_revision: bool = False
    advertencias: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropuestaMembresiaGrupoLegacy:
    """Propuesta independiente para ``MembresiaGrupo``."""

    grupo: ReferenciaLegacy
    nivel: Optional[str] = None
    principal: Optional[bool] = None
    activa: Optional[bool] = None
    requiere_revision: bool = False
    advertencias: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropuestaGuardiaLegacy:
    """Datos para una futura ``ProgramacionTrabajo`` de modalidad GUARDIA."""

    legacy_usuario_id: str
    django_user_id: Optional[int]
    grupo_trabajo: Optional[ReferenciaLegacy]
    prioridad: str = ""
    incidencia: str = ""
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None
    requiere_revision: bool = False
    advertencias: tuple[str, ...] = ()


@dataclass(frozen=True)
class PropuestaOperacionLegacy:
    """Resultado completo y no persistido de traducir una persona legacy.

    ``grupos_soporte`` describe clasificación/enrutamiento de tickets;
    ``grupos_trabajo`` describe personas/equipos operativos.  Se construyen
    por rutas de resolución distintas deliberadamente.
    """

    legacy_rol: str
    rol_destino: str
    capacidades: CapacidadesLegacy
    empresa: ReferenciaLegacy
    coberturas: tuple[PropuestaAsignacionPersonalLegacy, ...] = ()
    grupos_soporte: tuple[PropuestaGrupoSoporteLegacy, ...] = ()
    grupos_trabajo: tuple[PropuestaMembresiaGrupoLegacy, ...] = ()
    guardia: Optional[PropuestaGuardiaLegacy] = None
    requiere_revision: bool = False
    advertencias: tuple[str, ...] = ()

    @property
    def tiendas(self):
        return tuple(cobertura.tienda for cobertura in self.coberturas if cobertura.tienda)

    @property
    def zonas(self):
        return tuple(cobertura.zona for cobertura in self.coberturas if cobertura.zona)


def _valor(registro, campo, default=""):
    if isinstance(registro, Mapping):
        return registro.get(campo, default)
    return getattr(registro, campo, default)


def _texto(valor):
    return str(valor or "").strip()


def _clave_texto(valor):
    return _texto(valor).casefold()


def _referencia_resuelta(tipo, valor, objeto, *, campo=None):
    return ReferenciaLegacy(
        tipo=tipo,
        valor_legacy=_texto(valor),
        estado=EstadoResolucionLegacy.RESUELTO,
        django_id=objeto.pk,
        etiqueta=str(objeto),
        campo=campo,
    )


def _resolver_unico(tipo, valor, consulta, *, campo=None, faltante, no_encontrada, ambigua):
    valor = _texto(valor)
    if not valor:
        return ReferenciaLegacy(
            tipo, valor, EstadoResolucionLegacy.REQUIERE_REVISION,
            campo=campo, advertencias=(faltante,),
        )
    objetos = list(consulta.order_by("pk")[:2])
    if not objetos:
        return ReferenciaLegacy(
            tipo, valor, EstadoResolucionLegacy.NO_ENCONTRADA,
            campo=campo, advertencias=(no_encontrada,),
        )
    if len(objetos) > 1:
        return ReferenciaLegacy(
            tipo, valor, EstadoResolucionLegacy.AMBIGUA,
            campo=campo, advertencias=(ambigua,),
        )
    return _referencia_resuelta(tipo, valor, objetos[0], campo=campo)


def resolver_empresa_legacy(empresa_codigo):
    """Resuelve exclusivamente el código estable actual de la empresa."""
    return _resolver_unico(
        "EMPRESA", empresa_codigo, Empresa.objects.filter(codigo=_texto(empresa_codigo)),
        campo="codigo", faltante="EMPRESA_FALTANTE", no_encontrada="EMPRESA_NO_ENCONTRADA",
        ambigua="EMPRESA_AMBIGUA",
    )


def resolver_tienda_legacy(*, empresa, identificador, campo=None):
    """Resuelve una tienda por empresa e identificador exacto, nunca por nombre.

    El importador futuro debe indicar el campo de origen. Mientras no se
    conozca la semántica de una columna PHP, un valor no puede asociarse con
    seguridad aunque coincida de forma única en un catálogo Django.
    """
    if empresa.requiere_revision:
        return ReferenciaLegacy(
            "TIENDA", _texto(identificador), EstadoResolucionLegacy.REQUIERE_REVISION,
            campo=campo, advertencias=("TIENDA_SIN_EMPRESA_RESUELTA",),
    )
    identificador = _texto(identificador)
    campos = {"codigo", "id_externo", "clave", "numero"}
    campo = _texto(campo)
    if not campo:
        return ReferenciaLegacy(
            "TIENDA", identificador, EstadoResolucionLegacy.REQUIERE_REVISION,
            advertencias=("TIENDA_CAMPO_FALTANTE",),
        )
    if campo not in campos:
        return ReferenciaLegacy(
            "TIENDA", identificador, EstadoResolucionLegacy.REQUIERE_REVISION,
            campo=campo, advertencias=("TIENDA_CAMPO_NO_SOPORTADO",),
        )
    consulta = Tienda.objects.filter(empresa_id=empresa.django_id, **{campo: identificador})
    return _resolver_unico(
        "TIENDA", identificador, consulta, campo=campo,
        faltante="TIENDA_IDENTIFICADOR_FALTANTE", no_encontrada="TIENDA_NO_ENCONTRADA",
        ambigua="TIENDA_AMBIGUA",
    )


def resolver_zona_legacy(*, empresa, codigo):
    """Resuelve zona únicamente por ``empresa + codigo`` exactos."""
    if empresa.requiere_revision:
        return ReferenciaLegacy(
            "ZONA", _texto(codigo), EstadoResolucionLegacy.REQUIERE_REVISION,
            campo="codigo", advertencias=("ZONA_SIN_EMPRESA_RESUELTA",),
        )
    return _resolver_unico(
        "ZONA", codigo, Zona.objects.filter(empresa_id=empresa.django_id, codigo=_texto(codigo)),
        campo="codigo", faltante="ZONA_CODIGO_FALTANTE", no_encontrada="ZONA_NO_ENCONTRADA",
        ambigua="ZONA_AMBIGUA",
    )


def resolver_grupo_soporte_legacy(nombre):
    return _resolver_unico(
        "GRUPO_SOPORTE", nombre, GrupoSoporte.objects.filter(nombre=_texto(nombre)),
        campo="nombre", faltante="GRUPO_SOPORTE_FALTANTE",
        no_encontrada="GRUPO_SOPORTE_NO_ENCONTRADO", ambigua="GRUPO_SOPORTE_AMBIGUO",
    )


def resolver_subgrupo_soporte_legacy(*, grupo, nombre):
    if grupo.requiere_revision:
        return ReferenciaLegacy(
            "SUBGRUPO_SOPORTE", _texto(nombre), EstadoResolucionLegacy.REQUIERE_REVISION,
            campo="nombre", advertencias=("SUBGRUPO_SIN_GRUPO_SOPORTE_RESUELTO",),
        )
    return _resolver_unico(
        "SUBGRUPO_SOPORTE", nombre,
        SubgrupoSoporte.objects.filter(grupo_id=grupo.django_id, nombre=_texto(nombre)),
        campo="nombre", faltante="SUBGRUPO_SOPORTE_FALTANTE",
        no_encontrada="SUBGRUPO_SOPORTE_NO_ENCONTRADO", ambigua="SUBGRUPO_SOPORTE_AMBIGUO",
    )


def resolver_grupo_trabajo_legacy(*, empresa, nombre):
    """Resuelve equipos operativos; no consulta GrupoSoporte por diseño."""
    if empresa.requiere_revision:
        return ReferenciaLegacy(
            "GRUPO_TRABAJO", _texto(nombre), EstadoResolucionLegacy.REQUIERE_REVISION,
            campo="nombre", advertencias=("GRUPO_TRABAJO_SIN_EMPRESA_RESUELTA",),
        )
    return _resolver_unico(
        "GRUPO_TRABAJO", nombre,
        GrupoTrabajo.objects.filter(empresa_id=empresa.django_id, nombre=_texto(nombre)),
        campo="nombre", faltante="GRUPO_TRABAJO_FALTANTE",
        no_encontrada="GRUPO_TRABAJO_NO_ENCONTRADO", ambigua="GRUPO_TRABAJO_AMBIGUO",
    )


def _opcion_actual(valor, opciones, codigo_faltante, codigo_desconocido):
    opcion = _texto(valor).upper()
    if not opcion:
        return None, (codigo_faltante,)
    if opcion not in opciones:
        return None, (codigo_desconocido,)
    return opcion, ()


def _referencia_zona_de_tienda(tienda):
    return _referencia_resuelta("ZONA", tienda.zona.codigo, tienda.zona, campo="codigo")


def proponer_asignacion_personal_legacy(*, empresa, alcance, funcion, estado="", zona_codigo="",
                                        tienda_identificador="", tienda_campo=None,
                                        fecha_inicio=None, fecha_fin=None, principal=None):
    """Propone una cobertura sin crear ``Persona`` ni ``AsignacionPersonal``."""
    alcance, advertencias_alcance = _opcion_actual(
        alcance, set(AsignacionPersonal.Alcance.values),
        "COBERTURA_ALCANCE_FALTANTE", "COBERTURA_ALCANCE_DESCONOCIDO",
    )
    funcion, advertencias_funcion = _opcion_actual(
        funcion, set(AsignacionPersonal.Funcion.values),
        "COBERTURA_FUNCION_FALTANTE", "COBERTURA_FUNCION_DESCONOCIDA",
    )
    advertencias = list(advertencias_alcance + advertencias_funcion + empresa.advertencias)
    zona = tienda = None
    estado_legacy = _texto(estado)
    estado_resuelto = estado_legacy

    if zona_codigo:
        zona = resolver_zona_legacy(empresa=empresa, codigo=zona_codigo)
        advertencias.extend(zona.advertencias)
    if tienda_identificador:
        tienda = resolver_tienda_legacy(
            empresa=empresa, identificador=tienda_identificador, campo=tienda_campo,
        )
        advertencias.extend(tienda.advertencias)
        if tienda.estado == EstadoResolucionLegacy.RESUELTO:
            tienda_obj = Tienda.objects.select_related("zona").get(pk=tienda.django_id)
            tienda_zona = _referencia_zona_de_tienda(tienda_obj)
            if zona and zona.estado == EstadoResolucionLegacy.RESUELTO and zona.django_id != tienda_zona.django_id:
                advertencias.append("COBERTURA_CONTRADICTORIA")
            zona = zona or tienda_zona
            esperado = tienda_obj.estado
            if estado_resuelto and _clave_texto(estado_resuelto) != _clave_texto(esperado):
                advertencias.append("COBERTURA_CONTRADICTORIA")
            estado_resuelto = estado_resuelto or esperado
    if zona and zona.estado == EstadoResolucionLegacy.RESUELTO:
        zona_obj = Zona.objects.get(pk=zona.django_id)
        if estado_resuelto and _clave_texto(estado_resuelto) != _clave_texto(zona_obj.estado):
            advertencias.append("COBERTURA_CONTRADICTORIA")
        estado_resuelto = estado_resuelto or zona_obj.estado

    if alcance == AsignacionPersonal.Alcance.ESTADO and not estado_legacy:
        advertencias.append("COBERTURA_INCOMPLETA")
    if alcance == AsignacionPersonal.Alcance.ZONA and (
        not zona_codigo or not zona or zona.requiere_revision
    ):
        advertencias.append("COBERTURA_INCOMPLETA")
    if alcance == AsignacionPersonal.Alcance.TIENDA and (
        not tienda_identificador or not tienda or tienda.requiere_revision
    ):
        advertencias.append("COBERTURA_INCOMPLETA")
    if alcance == AsignacionPersonal.Alcance.ESTADO and (zona_codigo or tienda_identificador):
        advertencias.append("COBERTURA_DATOS_INCOMPATIBLES_CON_ALCANCE")
    if alcance == AsignacionPersonal.Alcance.ZONA and tienda_identificador:
        advertencias.append("COBERTURA_DATOS_INCOMPATIBLES_CON_ALCANCE")
    if fecha_inicio is not None and fecha_fin is not None and fecha_fin < fecha_inicio:
        advertencias.append("COBERTURA_PERIODO_INVALIDO")

    advertencias = tuple(dict.fromkeys(advertencias))
    return PropuestaAsignacionPersonalLegacy(
        empresa=empresa, alcance=alcance, funcion=funcion, estado=estado_resuelto,
        zona=zona, tienda=tienda, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        principal=principal, requiere_revision=bool(advertencias), advertencias=advertencias,
    )


def proponer_grupo_soporte_legacy(*, grupo_nombre, subgrupo_nombre=""):
    grupo = resolver_grupo_soporte_legacy(grupo_nombre)
    subgrupo = resolver_subgrupo_soporte_legacy(grupo=grupo, nombre=subgrupo_nombre) if subgrupo_nombre else None
    advertencias = grupo.advertencias + (subgrupo.advertencias if subgrupo else ())
    return PropuestaGrupoSoporteLegacy(
        grupo=grupo, subgrupo=subgrupo, requiere_revision=bool(advertencias), advertencias=advertencias,
    )


def proponer_membresia_grupo_legacy(*, empresa, grupo_nombre, nivel=None, principal=None, activa=None):
    grupo = resolver_grupo_trabajo_legacy(empresa=empresa, nombre=grupo_nombre)
    nivel_normalizado = _texto(nivel).upper() or None
    advertencias = list(grupo.advertencias)
    if nivel_normalizado and nivel_normalizado not in set(MembresiaGrupo.Nivel.values):
        nivel_normalizado = None
        advertencias.append("MEMBRESIA_NIVEL_DESCONOCIDO")
    return PropuestaMembresiaGrupoLegacy(
        grupo=grupo, nivel=nivel_normalizado, principal=principal, activa=activa,
        requiere_revision=bool(advertencias), advertencias=tuple(advertencias),
    )


def proponer_guardia_legacy(*, empresa, legacy_usuario_id="", django_user_id=None, grupo_nombre="",
                            prioridad="", incidencia="", fecha_inicio=None, fecha_fin=None,
                            hora_inicio=None, hora_fin=None):
    """Representa una guardia futura sin otorgar visibilidad global."""
    advertencias = []
    legacy_usuario_id = _texto(legacy_usuario_id)
    if not legacy_usuario_id and django_user_id is None:
        advertencias.append("GUARDIA_USUARIO_FALTANTE")
    grupo = resolver_grupo_trabajo_legacy(empresa=empresa, nombre=grupo_nombre) if grupo_nombre else None
    if grupo:
        advertencias.extend(grupo.advertencias)
    if None in (fecha_inicio, fecha_fin, hora_inicio, hora_fin):
        advertencias.append("GUARDIA_PERIODO_INCOMPLETO")
    if fecha_inicio is not None and fecha_fin is not None and fecha_fin < fecha_inicio:
        advertencias.append("GUARDIA_PERIODO_INVALIDO")
    if (
        fecha_inicio is not None and fecha_fin == fecha_inicio
        and hora_inicio is not None and hora_fin is not None and hora_fin <= hora_inicio
    ):
        advertencias.append("GUARDIA_HORARIO_INVALIDO")
    return PropuestaGuardiaLegacy(
        legacy_usuario_id=legacy_usuario_id, django_user_id=django_user_id, grupo_trabajo=grupo,
        prioridad=_texto(prioridad), incidencia=_texto(incidencia), fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin, hora_inicio=hora_inicio, hora_fin=hora_fin,
        requiere_revision=bool(advertencias), advertencias=tuple(dict.fromkeys(advertencias)),
    )


def proponer_operacion_legacy(*, legacy_rol, empresa_codigo="", coberturas=(), grupos_soporte=(),
                              grupos_trabajo=(), guardia=None):
    """Traduce un registro legacy en propuestas, sin ninguna escritura.

    Los roles sólo determinan ``PerfilUsuario.Rol``. Las capacidades quedan
    indeterminadas, salvo ``puede_ver_todos=False`` para no conceder acceso
    global por un nombre de rol, grupo o guardia.
    """
    propuesta_rol = proponer_rol_legacy(legacy_rol)
    empresa = resolver_empresa_legacy(empresa_codigo)
    propuestas_cobertura = tuple(
        proponer_asignacion_personal_legacy(
            empresa=empresa,
            alcance=_valor(cobertura, "alcance"),
            funcion=_valor(cobertura, "funcion"),
            estado=_valor(cobertura, "estado"),
            zona_codigo=_valor(cobertura, "zona_codigo"),
            tienda_identificador=_valor(cobertura, "tienda_identificador"),
            tienda_campo=_valor(cobertura, "tienda_campo") or None,
            fecha_inicio=_valor(cobertura, "fecha_inicio", None),
            fecha_fin=_valor(cobertura, "fecha_fin", None),
            principal=_valor(cobertura, "principal", None),
        )
        for cobertura in coberturas
    )
    propuestas_soporte = tuple(
        proponer_grupo_soporte_legacy(
            grupo_nombre=_valor(grupo, "grupo_nombre"),
            subgrupo_nombre=_valor(grupo, "subgrupo_nombre"),
        )
        for grupo in grupos_soporte
    )
    propuestas_trabajo = tuple(
        proponer_membresia_grupo_legacy(
            empresa=empresa, grupo_nombre=_valor(grupo, "grupo_nombre"),
            nivel=_valor(grupo, "nivel", None), principal=_valor(grupo, "principal", None),
            activa=_valor(grupo, "activa", None),
        )
        for grupo in grupos_trabajo
    )
    propuesta_guardia = None
    if guardia is not None:
        propuesta_guardia = proponer_guardia_legacy(
            empresa=empresa,
            legacy_usuario_id=_valor(guardia, "legacy_usuario_id"),
            django_user_id=_valor(guardia, "django_user_id", None),
            grupo_nombre=_valor(guardia, "grupo_nombre"),
            prioridad=_valor(guardia, "prioridad"), incidencia=_valor(guardia, "incidencia"),
            fecha_inicio=_valor(guardia, "fecha_inicio", None), fecha_fin=_valor(guardia, "fecha_fin", None),
            hora_inicio=_valor(guardia, "hora_inicio", None), hora_fin=_valor(guardia, "hora_fin", None),
        )

    advertencias = list(empresa.advertencias)
    if propuesta_rol.requiere_revision and propuesta_rol.razon:
        advertencias.append(propuesta_rol.razon)
    for propuesta in (*propuestas_cobertura, *propuestas_soporte, *propuestas_trabajo):
        advertencias.extend(propuesta.advertencias)
    if propuesta_guardia:
        advertencias.extend(propuesta_guardia.advertencias)
    advertencias = tuple(dict.fromkeys(advertencias))
    return PropuestaOperacionLegacy(
        legacy_rol=_texto(legacy_rol), rol_destino=propuesta_rol.rol_destino,
        capacidades=CapacidadesLegacy(), empresa=empresa, coberturas=propuestas_cobertura,
        grupos_soporte=propuestas_soporte, grupos_trabajo=propuestas_trabajo,
        guardia=propuesta_guardia, requiere_revision=bool(advertencias), advertencias=advertencias,
    )
