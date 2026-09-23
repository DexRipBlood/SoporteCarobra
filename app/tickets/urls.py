from django.urls import path
from . import operacion_views as operacion

from .views import (
    actualizar_coordenadas_tienda,
    confirmar_importacion_bradescard,
    crear_ticket_carobra,
    descargar_archivo_ticket,
    descargar_plantilla_coordenadas,
    descargar_plantilla_tiendas,
    detalle_ticket,
    directorio_activos,
    centro_importaciones,
    estructura_operativa,
    importar_catalogos_view,
    importar_bradescard_view,
    inventario,
    lista_tickets,
    mapa_vectorial_mexico,
    geometria_mexico,
    mapa_tiendas,
    reportería_incidencias,
    panel_configuracion,
    panel_equipos,
)


app_name = "tickets"


urlpatterns = [
    path("inventario/", inventario, name="inventario"),
    path("activos/", directorio_activos, name="directorio_activos"),
    path("reporteria/incidencias/", reportería_incidencias, name="reporteria_incidencias"),
    path("configuracion/tiendas/", operacion.territorio, name="territorio"),
    path("configuracion/calendario/", operacion.calendario, name="calendario"),
    path("configuracion/incidencias/", operacion.incidencias, name="incidencias"),
    path("configuracion/permisos/", operacion.permisos, name="permisos"),
    path("configuracion/<slug:tipo>/nuevo/", operacion.editar_catalogo, name="catalogo_nuevo"),
    path("configuracion/<slug:tipo>/<int:pk>/", operacion.editar_catalogo, name="catalogo_editar"),
    path("<str:folio>/seguimiento/", operacion.seguimiento, name="seguimiento"),
    path("<str:folio>/escalar/", operacion.escalar, name="escalar"),
    path("<str:folio>/suplencia/", operacion.suplencia, name="suplencia"),
    path("<str:folio>/clasificar/", operacion.clasificar, name="clasificar"),
    path("<str:folio>/tiempos/", operacion.tiempos, name="tiempos"),
    path("estructura/", estructura_operativa, name="estructura"),
    path("estructura/panel/equipos/", panel_equipos, name="equipos"),
    path("estructura/panel/<slug:seccion>/", panel_configuracion, name="panel_configuracion"),
    path("estructura/importar/", importar_catalogos_view, name="importar_catalogos"),
    path("estructura/plantilla-tiendas/", descargar_plantilla_tiendas, name="plantilla_tiendas"),
    path("estructura/plantilla-coordenadas/", descargar_plantilla_coordenadas, name="plantilla_coordenadas"),
    path("estructura/mapa/", mapa_tiendas, name="mapa_tiendas"),
    path("estructura/mapa/base-mexico.pmtiles", mapa_vectorial_mexico, name="mapa_vectorial_mexico"),
    path("estructura/mapa/mexico-<str:archivo>.geojson", geometria_mexico, name="geometria_mexico"),
    path("estructura/mapa/coordenadas/", actualizar_coordenadas_tienda, name="actualizar_coordenadas"),
    path(
        "",
        lista_tickets,
        name="lista",
    ),

    path(
        "nuevo/",
        crear_ticket_carobra,
        name="crear",
    ),

    path(
        "importar/",
        importar_bradescard_view,
        name="importar_bradescard",
    ),

    path(
        "importaciones/",
        centro_importaciones,
        name="importaciones",
    ),

    path(
        "importar/confirmar/",
        confirmar_importacion_bradescard,
        name="confirmar_importacion_bradescard",
    ),

    path(
        "archivos/<int:archivo_id>/",
        descargar_archivo_ticket,
        name="descargar_archivo",
    ),

    path(
        "<str:folio>/",
        detalle_ticket,
        name="detalle",
    ),
]
