from django.contrib import admin

from .models import PerfilUsuario


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "nombre_completo",
        "rol",
        "activo",
        "area",
        "cargo",
        "actualizado_at",
    )
    list_filter = ("rol", "activo", "area")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "numero_empleado",
        "area",
        "cargo",
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("creado_at", "actualizado_at")
    ordering = ("user__username",)
    fieldsets = (
        (
            "Acceso",
            {"fields": ("user", "rol", "activo")},
        ),
        (
            "Información corporativa",
            {
                "fields": (
                    "numero_empleado",
                    "telefono",
                    "area",
                    "cargo",
                )
            },
        ),
        (
            "Auditoría",
            {"fields": ("creado_at", "actualizado_at")},
        ),
    )

    @admin.display(description="Usuario", ordering="user__username")
    def usuario(self, obj):
        return obj.user.username

    @admin.display(description="Nombre", ordering="user__first_name")
    def nombre_completo(self, obj):
        return obj.user.get_full_name() or "—"
