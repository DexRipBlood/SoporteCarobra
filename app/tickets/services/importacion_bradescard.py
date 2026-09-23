import hashlib
from datetime import date, datetime, time
from pathlib import Path

from django.core.files import File
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tickets.models import (
    AccionImportacion,
    AsignacionPersonal,
    ConfiguracionSLA,
    ComentarioTicket,
    DetalleImportacion,
    EstadoImportacion,
    EstadoTicket,
    HistorialTicket,
    ImportacionTickets,
    OrigenTicket,
    PrioridadTicket,
    ProgramacionTrabajo,
    Ticket,
    Tienda,
    SegmentoSLA,
)

from .importador_excel import (
    calcular_hash_fila,
    normalizar_texto,
    obtener_filas_bradescard,
    valor_serializable,
    validar_excel_bradescard,
)


# =========================================================
# UTILIDADES
# =========================================================

def responsable_automatico(tienda, configuracion_sla=None):
    from .operacion import equipo_tienda
    return equipo_tienda(tienda)[0]


def partner_automatico(tienda):
    from .operacion import equipo_tienda
    return equipo_tienda(tienda)[1]

def texto_excel(valor):
    if valor is None:
        return ""

    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))

    return str(valor).strip()


def asignado_excel(valor):
    """
    Bradescard puede enviar 0 cuando no existe
    una asignación externa real.
    """

    texto = texto_excel(valor)

    if texto.lower() in {
        "",
        "0",
        "0.0",
        "none",
        "null",
        "nan",
    }:
        return ""

    return texto


def fecha_excel(valor):
    if valor is None:
        return None

    if isinstance(valor, datetime):
        return valor.date()

    if isinstance(valor, date):
        return valor

    return None


def hora_excel(valor):
    if valor is None:
        return None

    if isinstance(valor, datetime):
        return valor.time().replace(tzinfo=None)

    if isinstance(valor, time):
        return valor.replace(tzinfo=None)

    # Algunas hojas pueden traer una fracción de día Excel.
    if isinstance(valor, (int, float)):
        total_segundos = round(
            float(valor) * 24 * 60 * 60
        )

        total_segundos %= 24 * 60 * 60

        horas = total_segundos // 3600
        minutos = (total_segundos % 3600) // 60
        segundos = total_segundos % 60

        return time(
            horas,
            minutos,
            segundos,
        )

    return None


def datetime_excel(valor):
    """
    Convierte fechas de Excel en datetime con zona horaria
    de Django cuando sea necesario.
    """

    if valor is None:
        return None

    if isinstance(valor, datetime):
        resultado = valor

    elif isinstance(valor, date):
        resultado = datetime.combine(
            valor,
            time.min,
        )

    else:
        return None

    if timezone.is_naive(resultado):
        resultado = timezone.make_aware(
            resultado,
            timezone.get_current_timezone(),
        )

    return resultado


def hash_archivo(ruta_archivo):
    sha256 = hashlib.sha256()

    with open(ruta_archivo, "rb") as archivo:
        for bloque in iter(
            lambda: archivo.read(1024 * 1024),
            b"",
        ):
            sha256.update(bloque)

    return sha256.hexdigest()


# =========================================================
# ESTADO INICIAL
# =========================================================

def estado_interno_desde_externo(estatus):
    """
    Esto se usa SOLAMENTE al crear un ticket nuevo.

    Una importación posterior nunca sobreescribirá
    el estado interno administrado por CAROBRA.
    """

    valor = normalizar_texto(estatus)

    if "cerrad" in valor:
        return EstadoTicket.CERRADO

    if "resuelt" in valor:
        return EstadoTicket.RESUELTO

    if "espera" in valor:
        return EstadoTicket.EN_ESPERA

    if "curso" in valor:
        return EstadoTicket.EN_PROCESO

    if "asignad" in valor:
        return EstadoTicket.ASIGNADO

    return EstadoTicket.NUEVO


# =========================================================
# CONVERSIÓN EXCEL -> TICKET
# =========================================================

def datos_ticket_desde_fila(fila):
    datos_origen = {
        clave: valor_serializable(valor)
        for clave, valor in fila.items()
        if clave != "_fila_excel"
    }

    return {
        "tienda": texto_excel(
            fila.get("tienda")
        ),

        "estatus_externo": texto_excel(
            fila.get("estatus")
        ),

        "fecha_apertura_externa": datetime_excel(
            fila.get("fecha_apertura")
        ),

        "dias_transcurridos_externo": texto_excel(
            fila.get("dias_transcurridos")
        ),

        "categoria": texto_excel(
            fila.get("categoria")
        ),

        "incidencia_general": texto_excel(
            fila.get("incidencia_general")
        ),

        "incidencia_especifica": texto_excel(
            fila.get("incidencia_especifica")
        ),

        "seguimientos_externos": texto_excel(
            fila.get("seguimientos_descripcion")
        ),

        "fecha_reporte": fecha_excel(
            fila.get("fecha_reporte")
        ),

        "hora_reporte": hora_excel(
            fila.get("hora_reporte")
        ),

        "ultima_modificacion_externa": datetime_excel(
            fila.get("ultima_modificacion")
        ),

        "dias_sin_comentar_externo": texto_excel(
            fila.get("dias_sin_comentar")
        ),

        "tiempo_transcurrido_externo": texto_excel(
            fila.get("tiempo_transcurrido")
        ),

        "asignado_externo": asignado_excel(
            fila.get("asignado")
        ),

        "tipo_externo": texto_excel(
            fila.get("type")
        ),

        "usuario_externo": texto_excel(
            fila.get("usuario")
        ),

        "tiempo_total_externo": texto_excel(
            fila.get("tiempo_total")
        ),

        "soc_externo": texto_excel(
            fila.get("soc")
        ),

        "tablet_externo": texto_excel(
            fila.get("tablet")
        ),

        "cierre_por_falta_externo": texto_excel(
            fila.get("cierre_por_falta")
        ),

        "datos_origen": datos_origen,

        "hash_origen": calcular_hash_fila(
            fila
        ),
    }


# =========================================================
# COMPARAR CAMBIOS
# =========================================================

def detectar_cambios(ticket, datos_nuevos):
    cambios = {}

    # No mostramos estos campos técnicos como cambios.
    ignorar = {
        "datos_origen",
        "hash_origen",
    }

    for campo, nuevo in datos_nuevos.items():
        if campo in ignorar:
            continue

        anterior = getattr(
            ticket,
            campo,
            None,
        )

        anterior_comparable = valor_serializable(
            anterior
        )

        nuevo_comparable = valor_serializable(
            nuevo
        )

        if anterior_comparable != nuevo_comparable:
            cambios[campo] = {
                "antes": anterior_comparable,
                "despues": nuevo_comparable,
            }

    return cambios


# =========================================================
# IMPORTACIÓN REAL
# =========================================================

def importar_bradescard(
    ruta_archivo,
    usuario=None,
    empresa=None,
    categorias=None,
):
    """
    Importación real de la plantilla Bradescard.

    Reglas:
    - Nunca elimina tickets.
    - Nunca reemplaza la gestión interna de CAROBRA.
    - Actualiza únicamente datos provenientes del Excel.
    - Detecta archivos ya procesados mediante SHA-256.
    - Toda la operación de tickets ocurre en una transacción.
    """

    ruta = Path(ruta_archivo)

    validacion = validar_excel_bradescard(
        ruta
    )

    if not validacion["valido"]:
        return {
            "ok": False,
            "error": "La plantilla no pasó la validación.",
            "validacion": validacion,
        }

    archivo_hash = hash_archivo(
        ruta
    )
    if categorias is not None:
        firma = "|".join(sorted({c.strip().casefold() for c in categorias}))
        archivo_hash = hashlib.sha256((archivo_hash + "|" + firma).encode()).hexdigest()

    filas = None

    # -----------------------------------------------------
    # Evitar importar exactamente el mismo archivo, salvo
    # para reabrir un ticket que Bradescard aún reporta abierto.
    # -----------------------------------------------------

    importacion_anterior = (
        ImportacionTickets.objects
        .filter(
            hash_archivo=archivo_hash,
            empresa=empresa,
        )
        .first()
    )

    if importacion_anterior:
        from .filtros_importacion import filtrar_categorias

        filas = filtrar_categorias(
            obtener_filas_bradescard(ruta),
            categorias,
        )
        tickets_cerrados = {
            ticket.ticket_bradescard
            for ticket in Ticket.objects.filter(
                ticket_bradescard__in=[
                    fila["ticket_bradescard"]
                    for fila in filas
                ],
                empresa=empresa,
                estado_interno=EstadoTicket.CERRADO,
            )
        }
        permite_reapertura = any(
            fila["ticket_bradescard"] in tickets_cerrados
            and normalizar_texto(fila.get("estatus"))
            and estado_interno_desde_externo(fila.get("estatus"))
            != EstadoTicket.CERRADO
            for fila in filas
        )

        if not permite_reapertura:
            return {
                "ok": False,
                "duplicado": True,
                "error": (
                    "Este archivo ya fue importado anteriormente."
                ),
                "importacion_id": importacion_anterior.id,
                "fecha_importacion": (
                    importacion_anterior.iniciado_at
                ),
            }

        archivo_hash = hashlib.sha256(
            f"{archivo_hash}|reapertura|{timezone.now().isoformat()}".encode()
        ).hexdigest()

    # -----------------------------------------------------
    # Crear registro maestro de la importación
    # -----------------------------------------------------

    importacion = ImportacionTickets(
        empresa=empresa,
        nombre_archivo=ruta.name,
        hash_archivo=archivo_hash,
        estado=EstadoImportacion.PROCESANDO,
        usuario=usuario,
        total_filas=validacion["total_filas"],
    )

    # Guardamos una copia del Excel como evidencia.
    with open(ruta, "rb") as archivo:
        importacion.archivo.save(
            ruta.name,
            File(archivo),
            save=False,
        )

    importacion.save()

    try:
        from .filtros_importacion import filtrar_categorias
        if filas is None:
            filas = filtrar_categorias(
                obtener_filas_bradescard(ruta),
                categorias,
            )
        tiendas_indice = {}
        if empresa:
            for tienda in Tienda.objects.filter(empresa=empresa).select_related(
                "zona__responsable__perfil", "zona__partner__perfil", "encargado_soporte__usuario__perfil", "partner__usuario__perfil"
            ).order_by("pk"):
                for campo in ("codigo", "id_externo", "clave", "numero", "nombre"):
                    valor = str(getattr(tienda, campo) or "").strip().casefold()
                    if valor:
                        tiendas_indice.setdefault(valor, []).append(tienda)

        numeros = [
            fila["ticket_bradescard"]
            for fila in filas
        ]

        existentes = {
            ticket.ticket_bradescard: ticket
            for ticket in Ticket.objects.filter(
                ticket_bradescard__in=numeros,
                empresa=empresa,
            )
        }

        nuevos = []
        actualizados = []
        sin_cambios = []
        reabiertos = []

        cambios_por_ticket = {}

        fila_por_ticket = {}

        reglas_sla = list(ConfiguracionSLA.objects.filter(activo=True))
        reglas_sla_exactas = {
            (
                regla.categoria.strip().casefold(),
                regla.incidencia_general.strip().casefold(),
            ): regla
            for regla in reglas_sla
            if regla.incidencia_general.strip()
        }
        reglas_sla_categoria = {
            regla.categoria.strip().casefold(): regla
            for regla in reglas_sla
            if not regla.incidencia_general.strip()
        }

        def aplicar_reapertura_externa(ticket, datos_nuevos):
            estatus_externo = normalizar_texto(
                datos_nuevos["estatus_externo"]
            )
            estado_externo = estado_interno_desde_externo(
                datos_nuevos["estatus_externo"]
            )

            if (
                ticket.estado_interno != EstadoTicket.CERRADO
                or not estatus_externo
                or estado_externo == EstadoTicket.CERRADO
            ):
                return

            ticket.estado_interno = estado_externo
            ticket.cerrado_at = None
            ticket.ultima_reapertura_at = timezone.now()
            ticket.numero_reaperturas += 1
            reabiertos.append(ticket)

        # =================================================
        # PREPARACIÓN
        # =================================================

        for fila in filas:
            numero = fila[
                "ticket_bradescard"
            ]

            fila_por_ticket[numero] = fila[
                "_fila_excel"
            ]

            datos_nuevos = datos_ticket_desde_fila(
                fila
            )

            clave_sla = (
                datos_nuevos["categoria"].strip().casefold(),
                datos_nuevos["incidencia_general"].strip().casefold(),
            )
            configuracion_sla = (
                reglas_sla_exactas.get(clave_sla)
                or reglas_sla_categoria.get(clave_sla[0])
            )

            texto_tienda = datos_nuevos["tienda"]
            coincidencias = {t.pk: t for t in tiendas_indice.get(texto_tienda.strip().casefold(), [])}
            tienda_registrada = next(iter(coincidencias.values())) if len(coincidencias) == 1 else None

            existente = existentes.get(
                numero
            )
            if existente and existente.clasificacion_manual:
                datos_nuevos["categoria"] = existente.categoria
                datos_nuevos["incidencia_general"] = existente.incidencia_general

            # ---------------------------------------------
            # NUEVO
            # ---------------------------------------------

            if existente is None:
                responsable_asignado = responsable_automatico(
                    tienda_registrada, configuracion_sla
                )
                partner_asignado = partner_automatico(tienda_registrada)
                estado_inicial = estado_interno_desde_externo(
                    datos_nuevos["estatus_externo"]
                )
                if responsable_asignado and estado_inicial == EstadoTicket.NUEVO:
                    estado_inicial = EstadoTicket.ASIGNADO

                cerrado_at = None
                if estado_inicial == EstadoTicket.CERRADO:
                    cerrado_at = (
                        datos_nuevos["ultima_modificacion_externa"]
                        or timezone.now()
                    )

                ticket = Ticket(
                    ticket_bradescard=numero,

                    origen=OrigenTicket.BRADESCARD,

                    empresa=empresa,
                    tienda_registrada=tienda_registrada,
                    responsable=responsable_asignado,
                    partner=partner_asignado,
                    asignado_at=(timezone.now() if responsable_asignado else None),
                    configuracion_sla=configuracion_sla,
                    prioridad=(
                        configuracion_sla.prioridad
                        if configuracion_sla
                        else PrioridadTicket.MEDIA
                    ),
                    sla_limite_minutos=(
                        configuracion_sla.limite_minutos
                        if configuracion_sla
                        else None
                    ),

                    estado_interno=estado_inicial,
                    cerrado_at=cerrado_at,

                    primera_importacion=importacion,
                    ultima_importacion=importacion,

                    **datos_nuevos,
                )

                nuevos.append(
                    ticket
                )

                continue

            # ---------------------------------------------
            # EXISTENTE SIN CAMBIOS
            # ---------------------------------------------

            if (
                existente.hash_origen
                == datos_nuevos["hash_origen"]
            ):
                existente.empresa = empresa
                existente.tienda_registrada = tienda_registrada
                if not existente.responsable_id:
                    existente.responsable = responsable_automatico(
                        tienda_registrada, configuracion_sla
                    )
                    if existente.responsable_id:
                        existente.asignado_at = timezone.now()
                        if existente.estado_interno == EstadoTicket.NUEVO:
                            existente.estado_interno = EstadoTicket.ASIGNADO
                if not existente.partner_id:
                    existente.partner = partner_automatico(tienda_registrada)
                if not existente.configuracion_sla_id and configuracion_sla:
                    existente.configuracion_sla = configuracion_sla
                    existente.prioridad = configuracion_sla.prioridad
                    existente.sla_limite_minutos = configuracion_sla.limite_minutos
                existente.origen = OrigenTicket.BRADESCARD
                existente.ultima_importacion = (
                    importacion
                )
                aplicar_reapertura_externa(existente, datos_nuevos)

                sin_cambios.append(
                    existente
                )

                continue

            # ---------------------------------------------
            # EXISTENTE ACTUALIZADO
            # ---------------------------------------------

            cambios = detectar_cambios(
                existente,
                datos_nuevos,
            )

            cambios_por_ticket[
                numero
            ] = cambios

            for campo, valor in datos_nuevos.items():
                setattr(
                    existente,
                    campo,
                    valor,
                )

            existente.empresa = empresa
            existente.tienda_registrada = tienda_registrada
            existente.origen = OrigenTicket.BRADESCARD
            if not existente.responsable_id:
                existente.responsable = responsable_automatico(
                    tienda_registrada, configuracion_sla
                )
                if existente.responsable_id:
                    existente.asignado_at = timezone.now()
                    if existente.estado_interno == EstadoTicket.NUEVO:
                        existente.estado_interno = EstadoTicket.ASIGNADO
            if not existente.partner_id:
                existente.partner = partner_automatico(tienda_registrada)
            if not existente.configuracion_sla_id and configuracion_sla:
                existente.configuracion_sla = configuracion_sla
                existente.prioridad = configuracion_sla.prioridad
                existente.sla_limite_minutos = configuracion_sla.limite_minutos

            existente.ultima_importacion = (
                importacion
            )
            aplicar_reapertura_externa(existente, datos_nuevos)

            actualizados.append(
                existente
            )

        # =================================================
        # TRANSACCIÓN
        # =================================================

        with transaction.atomic():

            # ---------------------------------------------
            # CREAR NUEVOS
            # ---------------------------------------------

            if nuevos:
                Ticket.objects.bulk_create(
                    nuevos,
                    batch_size=500,
                )

                # bulk_create no ejecuta Ticket.save(),
                # por eso generamos aquí nuestro folio.
                anio = timezone.localdate().year

                for ticket in nuevos:
                    ticket.folio = (
                        f"TK-{anio}-{ticket.pk:06d}"
                    )

                Ticket.objects.bulk_update(
                    nuevos,
                    [
                        "folio",
                    ],
                    batch_size=500,
                )

            # ---------------------------------------------
            # ACTUALIZAR EXISTENTES
            # ---------------------------------------------

            if actualizados:
                Ticket.objects.bulk_update(
                    actualizados,
                    [
                        "tienda",
                        "estatus_externo",
                        "fecha_apertura_externa",
                        "dias_transcurridos_externo",
                        "categoria",
                        "incidencia_general",
                        "incidencia_especifica",
                        "seguimientos_externos",
                        "fecha_reporte",
                        "hora_reporte",
                        "ultima_modificacion_externa",
                        "dias_sin_comentar_externo",
                        "tiempo_transcurrido_externo",
                        "asignado_externo",
                        "tipo_externo",
                        "usuario_externo",
                        "tiempo_total_externo",
                        "soc_externo",
                        "tablet_externo",
                        "cierre_por_falta_externo",
                        "datos_origen",
                        "hash_origen",
                        "ultima_importacion",
                        "empresa",
                        "tienda_registrada",
                        "origen",
                        "partner",
                        "responsable",
                        "asignado_at",
                        "estado_interno",
                        "cerrado_at",
                        "ultima_reapertura_at",
                        "numero_reaperturas",
                        "configuracion_sla",
                        "prioridad",
                        "sla_limite_minutos",
                    ],
                    batch_size=500,
                )

            # ---------------------------------------------
            # REGISTRAR ÚLTIMA IMPORTACIÓN AUNQUE
            # EL TICKET NO HAYA CAMBIADO
            # ---------------------------------------------

            if sin_cambios:
                Ticket.objects.bulk_update(
                    sin_cambios,
                    [
                        "ultima_importacion",
                        "empresa",
                        "tienda_registrada",
                        "responsable",
                        "origen",
                        "partner",
                        "configuracion_sla",
                        "prioridad",
                        "sla_limite_minutos",
                        "asignado_at",
                        "estado_interno",
                        "cerrado_at",
                        "ultima_reapertura_at",
                        "numero_reaperturas",
                    ],
                    batch_size=500,
                )

            # ---------------------------------------------
            # Recuperar mapa completo de tickets
            # ---------------------------------------------

            tickets_bd = {
                ticket.ticket_bradescard: ticket
                for ticket in Ticket.objects.filter(
                    ticket_bradescard__in=numeros,
                    empresa=empresa,
                ).only(
                    "id",
                    "folio",
                    "ticket_bradescard",
                )
            }
            from .operacion import seguimiento_actual
            disponibilidad_cache = {}
            instante_importacion = timezone.now()
            for registrado in nuevos:
                cobertura = seguimiento_actual(registrado, instante_importacion, disponibilidad_cache)
                if cobertura["requiere_admin"]:
                    registrado.solicitud_admin = True
                    registrado.motivo_admin = "Revisar tienda / equipo / horario: " + cobertura["detalle"]
            if nuevos:
                Ticket.objects.bulk_update(nuevos, ["solicitud_admin", "motivo_admin"], batch_size=1000)
                SegmentoSLA.objects.bulk_create(
                    [
                        SegmentoSLA(
                            ticket=t,
                            responsable=t.responsable,
                            inicio=t.creado_at,
                            fin=t.cerrado_at,
                            cuenta_sla=True,
                        )
                        for t in nuevos
                    ],
                    batch_size=1000,
                )

            if reabiertos:
                SegmentoSLA.objects.filter(
                    ticket__in=reabiertos,
                    fin__isnull=True,
                ).update(fin=instante_importacion)
                SegmentoSLA.objects.bulk_create(
                    [
                        SegmentoSLA(
                            ticket=ticket,
                            responsable=ticket.responsable,
                            inicio=ticket.ultima_reapertura_at,
                            cuenta_sla=True,
                        )
                        for ticket in reabiertos
                    ],
                    batch_size=1000,
                )

            # ---------------------------------------------
            # DETALLE DE IMPORTACIÓN
            # ---------------------------------------------

            detalles = []

            for ticket in nuevos:
                numero = ticket.ticket_bradescard

                detalles.append(
                    DetalleImportacion(
                        importacion=importacion,
                        ticket=tickets_bd[numero],
                        fila_excel=fila_por_ticket[
                            numero
                        ],
                        ticket_bradescard=numero,
                        accion=AccionImportacion.NUEVO,
                    )
                )

            for ticket in actualizados:
                numero = ticket.ticket_bradescard

                detalles.append(
                    DetalleImportacion(
                        importacion=importacion,
                        ticket=tickets_bd[numero],
                        fila_excel=fila_por_ticket[
                            numero
                        ],
                        ticket_bradescard=numero,
                        accion=(
                            AccionImportacion.ACTUALIZADO
                        ),
                        cambios=cambios_por_ticket.get(
                            numero,
                            {},
                        ),
                    )
                )

            for ticket in sin_cambios:
                numero = ticket.ticket_bradescard

                detalles.append(
                    DetalleImportacion(
                        importacion=importacion,
                        ticket=tickets_bd[numero],
                        fila_excel=fila_por_ticket[
                            numero
                        ],
                        ticket_bradescard=numero,
                        accion=(
                            AccionImportacion.SIN_CAMBIOS
                        ),
                    )
                )

            DetalleImportacion.objects.bulk_create(
                detalles,
                batch_size=1000,
            )

            # ---------------------------------------------
            # HISTORIAL
            # Solo nuevos y tickets realmente modificados.
            # ---------------------------------------------

            historial = []

            for ticket in nuevos:
                numero = ticket.ticket_bradescard

                historial.append(
                    HistorialTicket(
                        ticket=tickets_bd[numero],
                        usuario=usuario,
                        evento=(
                            HistorialTicket.Evento.IMPORTADO
                        ),
                        origen=(
                            HistorialTicket.Origen.IMPORTACION
                        ),
                        descripcion=(
                            "Ticket creado durante la "
                            "importación inicial de Bradescard."
                        ),
                        valor_nuevo={
                            "ticket_bradescard": numero,
                            "archivo": ruta.name,
                        },
                    )
                )

            for ticket in actualizados:
                numero = ticket.ticket_bradescard

                historial.append(
                    HistorialTicket(
                        ticket=tickets_bd[numero],
                        usuario=usuario,
                        evento=(
                            HistorialTicket.Evento
                            .ACTUALIZADO_IMPORTACION
                        ),
                        origen=(
                            HistorialTicket.Origen.IMPORTACION
                        ),
                        descripcion=(
                            "Datos externos actualizados "
                            "desde archivo Bradescard."
                        ),
                        valor_nuevo={
                            "campos_actualizados": list(
                                cambios_por_ticket.get(
                                    numero,
                                    {}
                                ).keys()
                            ),
                            "archivo": ruta.name,
                        },
                    )
                )

            for ticket in reabiertos:
                numero = ticket.ticket_bradescard

                historial.append(
                    HistorialTicket(
                        ticket=tickets_bd[numero],
                        usuario=usuario,
                        evento=HistorialTicket.Evento.REABIERTO,
                        origen=HistorialTicket.Origen.IMPORTACION,
                        descripcion=(
                            "Bradescard reporta que el ticket continúa abierto; "
                            "se reabrió durante la importación."
                        ),
                        valor_anterior={"estado": EstadoTicket.CERRADO},
                        valor_nuevo={
                            "estado": ticket.estado_interno,
                            "estatus_externo": ticket.estatus_externo,
                            "archivo": ruta.name,
                        },
                    )
                )

            if historial:
                HistorialTicket.objects.bulk_create(
                    historial,
                    batch_size=1000,
                )

            # La reapertura externa debe ser visible en la conversación del
            # ticket, no únicamente en el historial de auditoría.
            if reabiertos:
                ComentarioTicket.objects.bulk_create([
                    ComentarioTicket(
                        ticket=tickets_bd[ticket.ticket_bradescard],
                        usuario=None,
                        tipo=ComentarioTicket.Tipo.SISTEMA,
                        comentario=(
                            "Bradescard reporta que el ticket continúa abierto; "
                            "el sistema lo reabrió automáticamente."
                        ),
                    )
                    for ticket in reabiertos
                ], batch_size=1000)

            # ---------------------------------------------
            # FINALIZAR IMPORTACIÓN
            # ---------------------------------------------

            importacion.nuevos = len(
                nuevos
            )

            importacion.actualizados = len(
                actualizados
            )

            importacion.sin_cambios = len(
                sin_cambios
            )

            importacion.errores = 0

            importacion.estado = (
                EstadoImportacion.COMPLETADA
            )

            importacion.finalizado_at = (
                timezone.now()
            )

            importacion.save(
                update_fields=[
                    "nuevos",
                    "actualizados",
                    "sin_cambios",
                    "errores",
                    "estado",
                    "finalizado_at",
                ]
            )

        return {
            "ok": True,
            "importacion_id": importacion.id,
            "archivo": ruta.name,
            "total": len(filas),
            "nuevos": len(nuevos),
            "actualizados": len(actualizados),
            "sin_cambios": len(sin_cambios),
            "errores": 0,
        }

    except Exception as error:
        importacion.estado = (
            EstadoImportacion.ERROR
        )

        importacion.errores = 1

        importacion.mensaje_error = str(
            error
        )

        importacion.finalizado_at = (
            timezone.now()
        )

        importacion.save(
            update_fields=[
                "estado",
                "errores",
                "mensaje_error",
                "finalizado_at",
            ]
        )

        return {
            "ok": False,
            "importacion_id": importacion.id,
            "error": str(error),
        }
