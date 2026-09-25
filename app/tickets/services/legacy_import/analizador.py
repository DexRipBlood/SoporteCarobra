"""Análisis determinista de datos legacy; todas sus operaciones son de lectura."""
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from usuarios.services.legacy import (
    AccionIdentidadLegacy,
    proponer_rol_legacy,
    resolver_identidad_legacy,
    sanear_datos_origen_legacy,
)
from usuarios.services.legacy_operacion import (
    EstadoResolucionLegacy,
    proponer_operacion_legacy,
    resolver_empresa_legacy,
    resolver_tienda_legacy,
)
from tickets.services.legacy import traducir_estado_legacy

from .esquema import (
    DisponibilidadSLALegacy,
    EstadoAnalisisLegacy,
    HallazgoLegacy,
    ReporteAnalisisLegacy,
    ResultadoArchivoLegacy,
    ResultadoRelacionadoLegacy,
    ResultadoTicketLegacy,
    ResultadoUsuarioLegacy,
    ResumenAnalisisLegacy,
)
from .lector import SECCIONES_OPCIONALES, SECCIONES_REQUERIDAS


@dataclass(frozen=True)
class _RegistroEntrada:
    """Metadato interno que conserva el índice de la fila JSON original."""

    indice: int
    datos: dict


def _texto(valor):
    return str(valor or "").strip()


def _valor(registro, *campos, default=""):
    for campo in campos:
        if campo in registro:
            return registro[campo]
    return default


def _legacy_id(registro):
    return _texto(_valor(registro, "legacy_id", "id"))


def _referencia_id(registro, *campos):
    return _texto(_valor(registro, *campos))


def _timestamp_valido(valor):
    if isinstance(valor, datetime):
        return True
    if not isinstance(valor, str) or not valor.strip():
        return False
    try:
        datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _campos_timestamp_invalidos(registro):
    campos = []
    for campo, valor in registro.items():
        if campo.endswith("_at") or campo in {
            "timestamp", "fecha", "fecha_evento", "fecha_apertura", "fecha_cierre",
        }:
            if valor not in (None, "") and not _timestamp_valido(valor):
                campos.append(campo)
    return campos


def _agregar_problema(problemas, seccion, indice, codigo):
    problemas[(seccion, indice)].append(codigo)


def normalizar_y_validar_entrada(datos):
    """Valida estructura antes de cualquier resolución contra Django."""
    secciones = {}
    estructurales = []
    problemas = defaultdict(list)
    for seccion in SECCIONES_REQUERIDAS:
        if seccion not in datos:
            estructurales.append(HallazgoLegacy("ESTRUCTURA_SECCION_FALTANTE", seccion))
            secciones[seccion] = []
            continue
        secciones[seccion] = datos[seccion]
    for seccion in SECCIONES_OPCIONALES:
        secciones[seccion] = datos.get(seccion, [])

    for seccion, registros in tuple(secciones.items()):
        if not isinstance(registros, list):
            estructurales.append(HallazgoLegacy("ESTRUCTURA_SECCION_TIPO_INVALIDO", seccion))
            secciones[seccion] = []
            continue
        normalizados = []
        vistos = defaultdict(list)
        for indice, registro in enumerate(registros):
            if not isinstance(registro, Mapping):
                estructurales.append(HallazgoLegacy("REGISTRO_TIPO_INVALIDO", seccion, indice=indice))
                continue
            registro = dict(registro)
            normalizados.append(_RegistroEntrada(indice=indice, datos=registro))
            legacy_id = _legacy_id(registro)
            requiere_id = seccion in {"usuarios", "tickets"}
            if requiere_id and not legacy_id:
                _agregar_problema(problemas, seccion, indice, "LEGACY_ID_FALTANTE")
            elif ("legacy_id" in registro or "id" in registro) and not legacy_id:
                _agregar_problema(problemas, seccion, indice, "LEGACY_ID_FALTANTE")
            elif legacy_id:
                vistos[legacy_id].append(indice)
            for _campo in _campos_timestamp_invalidos(registro):
                _agregar_problema(problemas, seccion, indice, "TIMESTAMP_INVALIDO")
        for legacy_id, indices in vistos.items():
            if len(indices) > 1:
                for indice in indices:
                    _agregar_problema(problemas, seccion, indice, "LEGACY_ID_DUPLICADO")
        secciones[seccion] = normalizados

    ids_por_seccion = {
        seccion: {
            _legacy_id(registro.datos)
            for registro in registros if _legacy_id(registro.datos)
        }
        for seccion, registros in secciones.items()
    }
    for entrada in secciones["tickets"]:
        indice, ticket = entrada.indice, entrada.datos
        usuario = _referencia_id(ticket, "responsable_legacy_id", "responsable_id")
        partner = _referencia_id(ticket, "partner_legacy_id", "partner_id")
        grupo = _referencia_id(ticket, "grupo_legacy_id", "grupo_id")
        tienda = _referencia_id(ticket, "tienda_legacy_id")
        if usuario and usuario not in ids_por_seccion["usuarios"]:
            _agregar_problema(problemas, "tickets", indice, "RESPONSABLE_LEGACY_NO_EXISTENTE")
        if partner and partner not in ids_por_seccion["usuarios"]:
            _agregar_problema(problemas, "tickets", indice, "PARTNER_LEGACY_NO_EXISTENTE")
        if grupo and grupo not in ids_por_seccion["grupos"]:
            _agregar_problema(problemas, "tickets", indice, "GRUPO_LEGACY_NO_EXISTENTE_EN_ARCHIVO")
        if tienda and secciones["tiendas"] and tienda not in ids_por_seccion["tiendas"]:
            _agregar_problema(problemas, "tickets", indice, "TIENDA_LEGACY_NO_EXISTENTE_EN_ARCHIVO")
    for seccion in ("comentarios", "historial", "archivos"):
        for entrada in secciones[seccion]:
            indice, registro = entrada.indice, entrada.datos
            ticket_id = _referencia_id(registro, "ticket_legacy_id", "ticket_id")
            usuario_id = _referencia_id(registro, "usuario_legacy_id", "usuario_id")
            if not ticket_id or ticket_id not in ids_por_seccion["tickets"]:
                _agregar_problema(problemas, seccion, indice, "TICKET_LEGACY_NO_EXISTENTE")
            if usuario_id and usuario_id not in ids_por_seccion["usuarios"]:
                _agregar_problema(problemas, seccion, indice, "USUARIO_LEGACY_NO_EXISTENTE")
    return secciones, tuple(estructurales), problemas


def _estado_desde_codigos(codigos):
    if codigos:
        return EstadoAnalisisLegacy.BLOQUEADO
    return EstadoAnalisisLegacy.LISTO_PARA_MIGRAR


def _resultado_usuario(source, registro, indice, problemas):
    # El saneador se ejecuta aunque el resultado no exponga datos originales.
    sanear_datos_origen_legacy(registro)
    legacy_id = _legacy_id(registro)
    errores = list(problemas[("usuarios", indice)])
    propuesta_rol = proponer_rol_legacy(_valor(registro, "rol", "legacy_rol"))
    resolucion = resolver_identidad_legacy(
        legacy_source=source,
        legacy_id=legacy_id,
        legacy_username=_valor(registro, "username", "legacy_username"),
        legacy_email=_valor(registro, "email", "legacy_email"),
        legacy_rol=_valor(registro, "rol", "legacy_rol"),
        legacy_activo=registro.get("activo"),
    )
    operacion = proponer_operacion_legacy(
        legacy_rol=_valor(registro, "rol", "legacy_rol"),
        empresa_codigo=_valor(registro, "empresa_codigo", "empresa"),
        coberturas=tuple(registro.get("coberturas", ()) if isinstance(registro.get("coberturas", ()), list) else ()),
        grupos_soporte=tuple(registro.get("grupos_soporte", ()) if isinstance(registro.get("grupos_soporte", ()), list) else ()),
        grupos_trabajo=tuple(registro.get("grupos_trabajo", ()) if isinstance(registro.get("grupos_trabajo", ()), list) else ()),
        guardia=registro.get("guardia") if isinstance(registro.get("guardia"), Mapping) else None,
    )
    advertencias = list(operacion.advertencias)
    if propuesta_rol.requiere_revision and propuesta_rol.razon:
        advertencias.append(propuesta_rol.razon)
    if resolucion.razon:
        advertencias.append(resolucion.razon)
    if resolucion.accion == AccionIdentidadLegacy.CONFLICTO:
        errores.append("IDENTIDAD_LEGACY_EN_CONFLICTO")
    elif resolucion.accion == AccionIdentidadLegacy.REQUIERE_REVISION:
        advertencias.append("IDENTIDAD_LEGACY_REQUIERE_REVISION")
    estado = _estado_desde_codigos(errores)
    if estado != EstadoAnalisisLegacy.BLOQUEADO and (
        resolucion.requiere_revision or operacion.requiere_revision
    ):
        estado = EstadoAnalisisLegacy.REQUIERE_REVISION
    return ResultadoUsuarioLegacy(
        legacy_id=legacy_id, accion=str(resolucion.accion), estado=estado,
        django_user_id=resolucion.django_user_id,
        advertencias=tuple(dict.fromkeys(advertencias)),
        errores=tuple(dict.fromkeys(errores)),
    )


def _sla_ticket(registro, *, tiene_historial=False):
    if "sla_legacy_segundos" in registro:
        valor = registro["sla_legacy_segundos"]
        if isinstance(valor, bool):
            return DisponibilidadSLALegacy.NO_DISPONIBLE, None, ("SLA_LEGACY_INVALIDO",)
        if isinstance(valor, int) and valor >= 0:
            return DisponibilidadSLALegacy.EXACTO, valor, ()
        if isinstance(valor, str) and valor.strip().isdigit():
            return DisponibilidadSLALegacy.EXACTO, int(valor.strip()), ()
        return DisponibilidadSLALegacy.NO_DISPONIBLE, None, ("SLA_LEGACY_INVALIDO",)
    tiene_timestamps = any(
        campo in registro for campo in ("fecha_apertura", "created_at", "legacy_cutover_at")
    )
    if tiene_historial or tiene_timestamps:
        return DisponibilidadSLALegacy.NO_DISPONIBLE, None, ("SLA_RECONSTRUCCION_NO_IMPLEMENTADA",)
    return DisponibilidadSLALegacy.NO_DISPONIBLE, None, ("SLA_LEGACY_NO_DISPONIBLE",)


def _dependencia_usuario(resultados, *, prefijo, legacy_id, errores, advertencias):
    """Clasifica una relación a usuario para la futura escritura por lotes."""
    if not legacy_id:
        return None, None
    if not resultados:
        errores.append(f"{prefijo}_LEGACY_NO_EXISTENTE")
        return None, None
    if len(resultados) != 1:
        errores.append(f"{prefijo}_LEGACY_BLOQUEADO")
        return None, None
    resultado = resultados[0]
    if resultado.estado == EstadoAnalisisLegacy.BLOQUEADO or resultado.accion == "CONFLICTO":
        errores.append(f"{prefijo}_LEGACY_BLOQUEADO")
        return resultado.django_user_id, resultado.accion
    if resultado.estado == EstadoAnalisisLegacy.REQUIERE_REVISION or resultado.accion == "REQUIERE_REVISION":
        advertencias.append(f"{prefijo}_LEGACY_REQUIERE_REVISION")
        return resultado.django_user_id, resultado.accion
    if resultado.accion == "MATCH_EXISTENTE" and resultado.django_user_id is not None:
        return resultado.django_user_id, resultado.accion
    if resultado.accion == "CREAR_NUEVO" and resultado.estado == EstadoAnalisisLegacy.LISTO_PARA_MIGRAR:
        # En escritura se creará primero la cuenta y después se enlazará el ticket.
        return None, resultado.accion
    errores.append(f"{prefijo}_SIN_USUARIO_DJANGO")
    return resultado.django_user_id, resultado.accion


def _resultado_ticket(registro, indice, problemas, usuarios, tickets_con_historial):
    legacy_id = _legacy_id(registro)
    errores = list(problemas[("tickets", indice)])
    advertencias = []
    estado_original = _texto(_valor(registro, "legacy_estado", "estado"))
    responsable_id = _referencia_id(registro, "responsable_legacy_id", "responsable_id")
    partner_id = _referencia_id(registro, "partner_legacy_id", "partner_id")
    responsable = usuarios.get(responsable_id, ())
    partner = usuarios.get(partner_id, ())
    responsable_django_id, responsable_accion = _dependencia_usuario(
        responsable, prefijo="RESPONSABLE", legacy_id=responsable_id,
        errores=errores, advertencias=advertencias,
    )
    partner_django_id, partner_accion = _dependencia_usuario(
        partner, prefijo="PARTNER", legacy_id=partner_id,
        errores=errores, advertencias=advertencias,
    )

    estado = traducir_estado_legacy(
        estado_original, tiene_responsable=bool(responsable_id),
        tiene_actividad=bool(registro.get("tiene_actividad")),
    )
    if estado.requiere_revision or estado.estado is None:
        errores.append("ESTADO_LEGACY_DESCONOCIDO")

    empresa = resolver_empresa_legacy(_valor(registro, "empresa_codigo", "empresa"))
    if empresa.estado != EstadoResolucionLegacy.RESUELTO:
        advertencias.extend(empresa.advertencias)
        if empresa.estado == EstadoResolucionLegacy.NO_ENCONTRADA:
            errores.append("EMPRESA_LEGACY_NO_ENCONTRADA")

    tienda = None
    tienda_identificador = _texto(_valor(registro, "tienda_identificador", "tienda_codigo"))
    if tienda_identificador:
        tienda = resolver_tienda_legacy(
            empresa=empresa, identificador=tienda_identificador,
            campo=_valor(registro, "tienda_campo") or None,
        )
        advertencias.extend(tienda.advertencias)
        if tienda.estado in {EstadoResolucionLegacy.NO_ENCONTRADA, EstadoResolucionLegacy.AMBIGUA}:
            if registro.get("tienda_obligatoria"):
                errores.extend(tienda.advertencias)
        elif tienda.requiere_revision and registro.get("tienda_obligatoria"):
            errores.extend(tienda.advertencias)

    sla_disponibilidad, sla_segundos, advertencias_sla = _sla_ticket(
        registro, tiene_historial=legacy_id in tickets_con_historial,
    )
    advertencias.extend(advertencias_sla)
    estado_resultado = _estado_desde_codigos(errores)
    if estado_resultado != EstadoAnalisisLegacy.BLOQUEADO and advertencias:
        estado_resultado = EstadoAnalisisLegacy.REQUIERE_REVISION
    return ResultadoTicketLegacy(
        legacy_id=legacy_id, estado=estado_resultado, estado_original=estado_original,
        estado_destino=str(estado.estado) if estado.estado else None,
        responsable_legacy_id=responsable_id,
        responsable_django_user_id=responsable_django_id,
        responsable_accion=responsable_accion,
        partner_legacy_id=partner_id,
        partner_django_user_id=partner_django_id,
        partner_accion=partner_accion,
        empresa_django_id=empresa.django_id if empresa.estado == EstadoResolucionLegacy.RESUELTO else None,
        tienda_django_id=tienda.django_id if tienda and tienda.estado == EstadoResolucionLegacy.RESUELTO else None,
        sla_disponibilidad=sla_disponibilidad, sla_legacy_segundos=sla_segundos,
        advertencias=tuple(dict.fromkeys(advertencias)), errores=tuple(dict.fromkeys(errores)),
    )


def _resultado_relacionado(seccion, registro, indice, problemas, tickets, usuarios):
    legacy_id = _legacy_id(registro)
    ticket_id = _referencia_id(registro, "ticket_legacy_id", "ticket_id")
    usuario_id = _referencia_id(registro, "usuario_legacy_id", "usuario_id")
    errores = list(problemas[(seccion, indice)])
    advertencias = []
    if seccion == "comentarios" and not _texto(_valor(registro, "texto", "comentario")):
        errores.append("COMENTARIO_TEXTO_FALTANTE")
    if seccion == "historial" and not _texto(_valor(registro, "evento", "tipo_evento")):
        errores.append("HISTORIAL_EVENTO_FALTANTE")
    tickets_padre = tickets.get(ticket_id, ())
    if len(tickets_padre) != 1 or tickets_padre[0].estado == EstadoAnalisisLegacy.BLOQUEADO:
        errores.append("TICKET_LEGACY_BLOQUEADO")
    elif tickets_padre[0].estado == EstadoAnalisisLegacy.REQUIERE_REVISION:
        advertencias.append("TICKET_LEGACY_REQUIERE_REVISION")
    if usuario_id:
        usuarios_padre = usuarios.get(usuario_id, ())
        if len(usuarios_padre) != 1 or usuarios_padre[0].estado == EstadoAnalisisLegacy.BLOQUEADO:
            errores.append("USUARIO_LEGACY_BLOQUEADO")
        elif usuarios_padre[0].estado == EstadoAnalisisLegacy.REQUIERE_REVISION:
            advertencias.append("USUARIO_LEGACY_REQUIERE_REVISION")
    estado = _estado_desde_codigos(errores)
    if estado != EstadoAnalisisLegacy.BLOQUEADO and advertencias:
        estado = EstadoAnalisisLegacy.REQUIERE_REVISION
    return ResultadoRelacionadoLegacy(
        seccion=seccion, legacy_id=legacy_id, ticket_legacy_id=ticket_id, estado=estado,
        advertencias=tuple(dict.fromkeys(advertencias)), errores=tuple(dict.fromkeys(errores)),
    )


def _resultado_archivo(registro, indice, problemas, tickets):
    legacy_id = _legacy_id(registro)
    ticket_id = _referencia_id(registro, "ticket_legacy_id", "ticket_id")
    errores = list(problemas[("archivos", indice)])
    advertencias = []
    tickets_padre = tickets.get(ticket_id, ())
    if len(tickets_padre) != 1 or tickets_padre[0].estado == EstadoAnalisisLegacy.BLOQUEADO:
        errores.append("TICKET_LEGACY_BLOQUEADO")
    elif tickets_padre[0].estado == EstadoAnalisisLegacy.REQUIERE_REVISION:
        advertencias.append("TICKET_LEGACY_REQUIERE_REVISION")
    estado = _estado_desde_codigos(errores)
    if estado != EstadoAnalisisLegacy.BLOQUEADO and advertencias:
        estado = EstadoAnalisisLegacy.REQUIERE_REVISION
    # Sólo se conserva metadato declarado: ninguna ruta del JSON se abre.
    return ResultadoArchivoLegacy(
        legacy_id=legacy_id, ticket_legacy_id=ticket_id, estado=estado,
        origen_declarado=_texto(_valor(registro, "ruta", "origen")),
        existencia_declarada=registro.get("existe"), tipo_declarado=_texto(registro.get("tipo")),
        tamano_declarado=registro.get("tamano"), advertencias=tuple(dict.fromkeys(advertencias)),
        errores=tuple(dict.fromkeys(errores)),
    )


def _hallazgos_desde_resultados(resultados, *, seccion):
    errores = []
    advertencias = []
    for indice, resultado in resultados:
        legacy_id = getattr(resultado, "legacy_id", "")
        for codigo in resultado.errores:
            errores.append(HallazgoLegacy(codigo, seccion, legacy_id, indice))
        for codigo in resultado.advertencias:
            advertencias.append(HallazgoLegacy(codigo, seccion, legacy_id, indice))
    return tuple(errores), tuple(advertencias)


def _sin_duplicados(hallazgos):
    vistos = set()
    resultado = []
    for hallazgo in hallazgos:
        clave = (hallazgo.codigo, hallazgo.seccion, hallazgo.legacy_id, hallazgo.indice)
        if clave not in vistos:
            vistos.add(clave)
            resultado.append(hallazgo)
    return tuple(resultado)


def analizar_legacy(datos, *, source):
    """Analiza el JSON usando el estado actual de Django, sin persistir nada."""
    source = _texto(source)
    if not source:
        raise ValueError("LEGACY_SOURCE_FALTANTE")
    secciones, errores_estructura, problemas = normalizar_y_validar_entrada(datos)
    usuarios_con_indices = tuple(
        (entrada.indice, _resultado_usuario(source, entrada.datos, entrada.indice, problemas))
        for entrada in secciones["usuarios"]
    )
    usuarios = tuple(resultado for _, resultado in usuarios_con_indices)
    usuarios_por_id = defaultdict(list)
    for _, resultado in usuarios_con_indices:
        if resultado.legacy_id:
            usuarios_por_id[resultado.legacy_id].append(resultado)
    tickets_con_historial = {
        _referencia_id(entrada.datos, "ticket_legacy_id", "ticket_id")
        for entrada in secciones["historial"]
    }
    tickets_con_indices = tuple(
        (
            entrada.indice,
            _resultado_ticket(
                entrada.datos, entrada.indice, problemas,
                usuarios_por_id,
                tickets_con_historial,
            ),
        )
        for entrada in secciones["tickets"]
    )
    tickets = tuple(resultado for _, resultado in tickets_con_indices)
    tickets_por_id = defaultdict(list)
    for _, resultado in tickets_con_indices:
        if resultado.legacy_id:
            tickets_por_id[resultado.legacy_id].append(resultado)
    comentarios_con_indices = tuple(
        (
            entrada.indice,
            _resultado_relacionado(
                "comentarios", entrada.datos, entrada.indice, problemas,
                tickets_por_id, usuarios_por_id,
            ),
        )
        for entrada in secciones["comentarios"]
    )
    comentarios = tuple(resultado for _, resultado in comentarios_con_indices)
    historial_con_indices = tuple(
        (
            entrada.indice,
            _resultado_relacionado(
                "historial", entrada.datos, entrada.indice, problemas,
                tickets_por_id, usuarios_por_id,
            ),
        )
        for entrada in secciones["historial"]
    )
    historial = tuple(resultado for _, resultado in historial_con_indices)
    archivos_con_indices = tuple(
        (
            entrada.indice,
            _resultado_archivo(entrada.datos, entrada.indice, problemas, tickets_por_id),
        )
        for entrada in secciones["archivos"]
    )
    archivos = tuple(resultado for _, resultado in archivos_con_indices)
    hallazgos = list(errores_estructura)
    advertencias = []
    for resultados, seccion in (
        (usuarios_con_indices, "usuarios"), (tickets_con_indices, "tickets"),
        (comentarios_con_indices, "comentarios"), (historial_con_indices, "historial"),
        (archivos_con_indices, "archivos"),
    ):
        errores_resultados, advertencias_resultados = _hallazgos_desde_resultados(
            resultados, seccion=seccion,
        )
        hallazgos.extend(errores_resultados)
        advertencias.extend(advertencias_resultados)
    hallazgos = _sin_duplicados(hallazgos)
    advertencias = _sin_duplicados(advertencias)
    resumen = ResumenAnalisisLegacy(
        usuarios_analizados=len(usuarios),
        usuarios_match_existente=sum(resultado.accion == "MATCH_EXISTENTE" for resultado in usuarios),
        usuarios_nuevos_propuestos=sum(resultado.accion == "CREAR_NUEVO" for resultado in usuarios),
        usuarios_revision=sum(resultado.estado == EstadoAnalisisLegacy.REQUIERE_REVISION for resultado in usuarios),
        usuarios_conflicto=sum(resultado.accion == "CONFLICTO" for resultado in usuarios),
        tickets_analizados=len(tickets),
        tickets_listos=sum(resultado.estado == EstadoAnalisisLegacy.LISTO_PARA_MIGRAR for resultado in tickets),
        tickets_revision=sum(resultado.estado == EstadoAnalisisLegacy.REQUIERE_REVISION for resultado in tickets),
        tickets_bloqueados=sum(resultado.estado == EstadoAnalisisLegacy.BLOQUEADO for resultado in tickets),
        comentarios_analizados=len(comentarios), historial_analizado=len(historial),
        archivos_analizados=len(archivos), errores=len(hallazgos), advertencias=len(advertencias),
    )
    return ReporteAnalisisLegacy(
        source=source, dry_run=True, base_datos_modificada=False, resumen=resumen,
        usuarios=usuarios, tickets=tickets, comentarios=comentarios, historial=historial,
        archivos=archivos, errores=hallazgos, advertencias=advertencias,
    )
