from django.conf import settings
from django.db import models
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
