from django.contrib import admin

from usuarios.permisos import es_administrador

from .models import Pendiente, PendienteHistorial


class SoloLecturaAdmin(admin.ModelAdmin):
    actions = None

    def has_view_permission(self, request, obj=None):
        return es_administrador(request.user)

    def has_module_permission(self, request):
        return es_administrador(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Pendiente)
class PendienteAdmin(SoloLecturaAdmin):
    list_display = ("folio", "titulo", "estado", "prioridad", "responsable", "fecha_compromiso")
    list_filter = ("estado", "prioridad", "area")
    search_fields = ("folio", "titulo")
    list_select_related = ("responsable",)


@admin.register(PendienteHistorial)
class PendienteHistorialAdmin(SoloLecturaAdmin):
    list_display = ("pendiente", "tipo_evento", "usuario", "fecha")
    list_select_related = ("pendiente", "usuario")
    search_fields = ("pendiente__folio", "pendiente__titulo")
