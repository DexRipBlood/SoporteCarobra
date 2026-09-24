from django.conf import settings
from django.db import models
from django.utils import timezone
from pathlib import Path
from uuid import uuid4


def ruta_foto_perfil(instance, filename):
    extension = Path(filename).suffix.lower() or ".webp"
    return f"usuarios/avatares/{instance.user_id}/{uuid4().hex}{extension}"


class PerfilUsuario(models.Model):

    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        USUARIO = "USUARIO", "Usuario"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
    )

    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.USUARIO,
    )

    activo = models.BooleanField(
        default=True,
    )
    puede_seguimiento = models.BooleanField("Actualizar seguimiento de sus tickets", default=True)
    puede_cerrar = models.BooleanField("Cerrar sus tickets con evidencia", default=True)
    puede_reasignar = models.BooleanField("Reasignar equipo de sus tickets", default=False)
    puede_ver_todos = models.BooleanField("Consultar todos los tickets", default=False)

    numero_empleado = models.CharField(
        "número de empleado",
        max_length=40,
        blank=True,
    )

    telefono = models.CharField(
        "teléfono",
        max_length=30,
        blank=True,
    )

    area = models.CharField(
        "área o departamento",
        max_length=100,
        blank=True,
    )

    cargo = models.CharField(
        max_length=100,
        blank=True,
    )

    foto = models.ImageField(
        "foto de perfil",
        upload_to=ruta_foto_perfil,
        blank=True,
        null=True,
    )

    creado_at = models.DateTimeField(
        auto_now_add=True,
    )

    actualizado_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"{self.user.username} · {self.get_rol_display()}"


class IdentidadLegacyUsuario(models.Model):
    """Vínculo auditable entre una identidad legacy y una cuenta Django."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="identidades_legacy",
    )
    legacy_source = models.CharField(max_length=100)
    legacy_id = models.CharField(max_length=120)
    legacy_username = models.CharField(max_length=150, blank=True)
    legacy_email = models.CharField(max_length=254, blank=True)
    legacy_rol = models.CharField(max_length=100, blank=True)
    legacy_activo = models.BooleanField(null=True, blank=True)
    datos_origen = models.JSONField(default=dict, blank=True)
    migrado_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["legacy_source", "legacy_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_source", "legacy_id"],
                name="uq_identidad_legacy_source_id",
            ),
        ]

    def __str__(self):
        return f"{self.legacy_source}:{self.legacy_id} → {self.user_id}"

    def save(self, *args, **kwargs):
        # La futura importación debe usar el saneador explícitamente; esta
        # segunda capa protege además las persistencias normales del modelo.
        from usuarios.services.legacy import sanear_datos_origen_legacy

        self.datos_origen = sanear_datos_origen_legacy(self.datos_origen)
        return super().save(*args, **kwargs)
