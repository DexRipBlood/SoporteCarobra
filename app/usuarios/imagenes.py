from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 25_000_000
AVATAR_SIZE = (512, 512)
ALLOWED_AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}


def validar_foto_perfil(archivo):
    if archivo.size > MAX_AVATAR_BYTES:
        raise ValidationError("La foto no puede pesar más de 5 MB.")

    try:
        archivo.seek(0)

        with Image.open(archivo) as imagen:
            if imagen.format not in ALLOWED_AVATAR_FORMATS:
                raise ValidationError(
                    "Usa una imagen JPG, PNG o WebP."
                )

            if imagen.width * imagen.height > MAX_AVATAR_PIXELS:
                raise ValidationError(
                    "La resolución de la foto es demasiado grande."
                )

            imagen.verify()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError("El archivo no contiene una imagen válida.")
    finally:
        archivo.seek(0)

    return archivo


def normalizar_foto_perfil(archivo):
    archivo.seek(0)

    with Image.open(archivo) as imagen:
        imagen = ImageOps.exif_transpose(imagen)
        imagen = ImageOps.fit(
            imagen,
            AVATAR_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        imagen = imagen.convert("RGBA" if "A" in imagen.getbands() else "RGB")
        salida = BytesIO()
        imagen.save(salida, format="WEBP", quality=86, method=6)

    return ContentFile(
        salida.getvalue(),
        name=f"{uuid4().hex}.webp",
    )


def actualizar_foto_perfil(perfil, nueva_foto=None, eliminar=False):
    if not nueva_foto and not eliminar:
        return False

    nombre_anterior = perfil.foto.name if perfil.foto else ""
    almacenamiento = perfil.foto.storage

    if nueva_foto:
        perfil.foto = normalizar_foto_perfil(nueva_foto)
    else:
        perfil.foto = None

    perfil.save(update_fields=["foto", "actualizado_at"])

    if nombre_anterior and nombre_anterior != perfil.foto.name:
        transaction.on_commit(
            lambda: almacenamiento.delete(nombre_anterior)
        )

    return True
