from django.contrib import admin

from .models import (
    AsignacionPersonal,
    ArchivoTicket,
    ComentarioTicket,
    ConfiguracionSLA,
    Dependencia,
    DetalleImportacion,
    Empresa,
    EstatusOperativo,
    GrupoSoporte,
    GrupoTrabajo,
    HistorialTicket,
    ImportacionTickets,
    MembresiaGrupo,
    Persona,
    ProgramacionTrabajo,
    SegmentoSLA,
    SubgrupoSoporte,
    Ticket,
    Tienda,
    Zona,
)


admin.site.register(Empresa)
admin.site.register(Zona)
admin.site.register(Persona)
admin.site.register(GrupoTrabajo)
admin.site.register(MembresiaGrupo)
admin.site.register(ProgramacionTrabajo)


@admin.register(Tienda)
class TiendaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo", "id_externo", "numero", "nombre", "estado", "zona",
        "encargado_soporte_nombre", "partner_nombre", "piloto", "retiro",
        "estado_geocodificacion",
    )
    list_filter = (
        "empresa", "estado", "piloto", "retiro", "estado_geocodificacion",
    )
    search_fields = (
        "codigo", "id_externo", "clave", "numero", "nombre", "direccion",
        "encargado_soporte_nombre", "partner_nombre", "coordinador",
    )
    readonly_fields = ("codigo", "geocodificada_at", "creado_at", "actualizado_at")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "folio",
        "origen",
        "ticket_bradescard",
        "tienda",
        "categoria",
        "estado_interno",
        "prioridad",
        "responsable",
        "partner",
        "sla_excedido",
        "actualizado_at",
    )

    list_filter = (
        "origen",
        "estado_interno",
        "prioridad",
        "categoria",
        "sla_excedido",
        "grupo",
        "subgrupo",
    )

    search_fields = (
        "folio",
        "ticket_bradescard",
        "tienda",
        "categoria",
        "incidencia_general",
        "incidencia_especifica",
        "asignado_externo",
    )

    autocomplete_fields = (
        "responsable",
        "partner",
        "creado_por",
        "grupo",
        "subgrupo",
        "dependencia_actual",
        "estatus_operativo_actual",
        "configuracion_sla",
    )

    readonly_fields = (
        "folio",
        "creado_at",
        "actualizado_at",
        "sla_excedido_at",
        "asignado_at",
        "primer_comentario_at",
        "resuelto_at",
        "cerrado_at",
        "ultima_reapertura_at",
    )


@admin.register(ImportacionTickets)
class ImportacionTicketsAdmin(admin.ModelAdmin):
    list_display = (
        "nombre_archivo",
        "estado",
        "total_filas",
        "nuevos",
        "actualizados",
        "sin_cambios",
        "errores",
        "iniciado_at",
    )

    list_filter = (
        "estado",
        "iniciado_at",
    )

    search_fields = (
        "nombre_archivo",
        "hash_archivo",
    )

    readonly_fields = (
        "iniciado_at",
        "finalizado_at",
    )


@admin.register(DetalleImportacion)
class DetalleImportacionAdmin(admin.ModelAdmin):
    list_display = (
        "importacion",
        "fila_excel",
        "ticket_bradescard",
        "accion",
        "creado_at",
    )

    list_filter = (
        "accion",
    )

    search_fields = (
        "ticket_bradescard",
        "error",
    )


@admin.register(ComentarioTicket)
class ComentarioTicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket",
        "usuario",
        "tipo",
        "creado_at",
    )

    list_filter = (
        "tipo",
        "creado_at",
    )

    search_fields = (
        "ticket__folio",
        "ticket__ticket_bradescard",
        "comentario",
    )


@admin.register(ArchivoTicket)
class ArchivoTicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket",
        "nombre_original",
        "tipo",
        "usuario",
        "creado_at",
    )

    list_filter = (
        "tipo",
        "creado_at",
    )

    search_fields = (
        "ticket__folio",
        "ticket__ticket_bradescard",
        "nombre_original",
    )


@admin.register(HistorialTicket)
class HistorialTicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket",
        "evento",
        "origen",
        "usuario",
        "creado_at",
    )

    list_filter = (
        "evento",
        "origen",
        "creado_at",
    )

    search_fields = (
        "ticket__folio",
        "ticket__ticket_bradescard",
        "descripcion",
    )


@admin.register(SegmentoSLA)
class SegmentoSLAAdmin(admin.ModelAdmin):
    list_display = (
        "ticket",
        "tipo",
        "responsable",
        "inicio",
        "fin",
        "cuenta_sla",
    )

    list_filter = (
        "tipo",
        "cuenta_sla",
    )

    search_fields = (
        "ticket__folio",
        "ticket__ticket_bradescard",
        "motivo",
    )


@admin.register(GrupoSoporte)
class GrupoSoporteAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "activo",
        "actualizado_at",
    )

    list_filter = (
        "activo",
    )

    search_fields = (
        "nombre",
        "descripcion",
    )


@admin.register(SubgrupoSoporte)
class SubgrupoSoporteAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "grupo",
        "activo",
    )

    list_filter = (
        "grupo",
        "activo",
    )

    search_fields = (
        "nombre",
        "descripcion",
    )


@admin.register(Dependencia)
class DependenciaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "pausa_sla_por_defecto",
        "activo",
    )

    list_filter = (
        "pausa_sla_por_defecto",
        "activo",
    )

    search_fields = (
        "nombre",
        "descripcion",
    )


@admin.register(EstatusOperativo)
class EstatusOperativoAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "cuenta_como_afectacion",
        "activo",
    )

    list_filter = (
        "cuenta_como_afectacion",
        "activo",
    )

    search_fields = (
        "nombre",
        "descripcion",
    )


@admin.register(ConfiguracionSLA)
class ConfiguracionSLAAdmin(admin.ModelAdmin):
    list_display = (
        "categoria",
        "incidencia_general",
        "limite_minutos",
        "prioridad",
        "activo",
    )

    list_filter = (
        "prioridad",
        "activo",
    )

    search_fields = (
        "categoria",
        "incidencia_general",
    )
    Empresa,
    GrupoTrabajo,
    MembresiaGrupo,
    Persona,
    ProgramacionTrabajo,
