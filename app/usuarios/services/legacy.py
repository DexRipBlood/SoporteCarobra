"""Reglas auditables para preparar identidades de usuarios legacy."""
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional
import re
import unicodedata

from django.contrib.auth import get_user_model
from django.db.models.functions import Lower, Trim

from usuarios.models import IdentidadLegacyUsuario, PerfilUsuario


class AccionIdentidadLegacy(StrEnum):
    MATCH_EXISTENTE = "MATCH_EXISTENTE"
    CREAR_NUEVO = "CREAR_NUEVO"
    CONFLICTO = "CONFLICTO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


@dataclass(frozen=True)
class PropuestaRolLegacy:
    legacy_rol: str
    rol_destino: str
    requiere_revision: bool = False
    razon: Optional[str] = None


@dataclass(frozen=True)
class ResolucionIdentidadLegacy:
    legacy_source: str
    legacy_id: str
    legacy_username: str
    legacy_email: str
    legacy_rol: str
    accion: AccionIdentidadLegacy
    django_user_id: Optional[int]
    confianza: Optional[str]
    rol_destino: str
    requiere_revision: bool
    razon: Optional[str] = None
    habilitar_user: bool = False
    habilitar_perfil: bool = False


@dataclass(frozen=True)
class AlertaPreparacionLegacy:
    codigo: str
    valor: str
    legacy_ids: tuple[str, ...] = ()
    django_user_ids: tuple[int, ...] = ()


_CLAVES_SECRETAS_LEGACY = {
    "password",
    "passwd",
    "password_hash",
    "hash_password",
    "hash",
    "salt",
    "remember_token",
    "token",
    "access_token",
    "refresh_token",
    "session",
    "session_id",
}
_CLAVES_SECRETAS_LEGACY_COMPACTAS = {
    clave.replace("_", "") for clave in _CLAVES_SECRETAS_LEGACY
}


def normalizar_correo(valor):
    return str(valor or "").strip().lower()


def normalizar_username(valor):
    return str(valor or "").strip().lower()


def normalizar_rol(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return " ".join(texto.upper().split())


def normalizar_clave_legacy(valor):
    """Normaliza mayúsculas, acentos y separadores de una clave legacy."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    partes = re.split(r"[^a-z0-9]+", texto.casefold())
    return "_".join(parte for parte in partes if parte)


def es_clave_secreta_legacy(clave):
    normalizada = normalizar_clave_legacy(clave)
    return (
        normalizada in _CLAVES_SECRETAS_LEGACY
        or normalizada.replace("_", "") in _CLAVES_SECRETAS_LEGACY_COMPACTAS
    )


def sanear_datos_origen_legacy(datos):
    """Devuelve una copia sin secretos apta para ``datos_origen``.

    Sanea diccionarios anidados y listas sin mutar el objeto recibido, para
    que hashes, tokens y sesiones no alcancen el registro auditable.
    """
    if isinstance(datos, Mapping):
        return {
            clave: sanear_datos_origen_legacy(valor)
            for clave, valor in datos.items()
            if not es_clave_secreta_legacy(clave)
        }
    if isinstance(datos, (list, tuple)):
        return [sanear_datos_origen_legacy(valor) for valor in datos]
    return datos


def proponer_rol_legacy(legacy_rol):
    rol = normalizar_rol(legacy_rol)
    if rol in {"SUPERROOT", "ADMIN"}:
        return PropuestaRolLegacy(legacy_rol=str(legacy_rol or ""), rol_destino=PerfilUsuario.Rol.ADMIN)
    if rol in {"SOPORTE", "COORDINADOR", "INTERNO"}:
        return PropuestaRolLegacy(legacy_rol=str(legacy_rol or ""), rol_destino=PerfilUsuario.Rol.USUARIO)
    return PropuestaRolLegacy(
        legacy_rol=str(legacy_rol or ""),
        rol_destino=PerfilUsuario.Rol.USUARIO,
        requiere_revision=bool(rol),
        razon="ROL_LEGACY_DESCONOCIDO" if rol else None,
    )


def _usuarios_por_campo(campo, valor):
    if not valor:
        return []
    User = get_user_model()
    normalizado = "email_normalizado" if campo == "email" else "username_normalizado"
    return list(
        User.objects.annotate(**{normalizado: Lower(Trim(campo))})
        .filter(**{normalizado: valor})
        .order_by("pk")
    )


def _identidades_por_campo(campo, valor, *, excluir=None):
    if not valor:
        return []
    normalizado = "email_normalizado" if campo == "legacy_email" else "username_normalizado"
    consulta = IdentidadLegacyUsuario.objects.annotate(
        **{normalizado: Lower(Trim(campo))}
    ).filter(**{normalizado: valor})
    if excluir:
        consulta = consulta.exclude(
            legacy_source=excluir[0], legacy_id=excluir[1]
        )
    return list(consulta.order_by("pk"))


def _discrepancia_actividad(usuario, legacy_activo):
    if legacy_activo is None:
        return False
    try:
        perfil_activo = usuario.perfil.activo
    except PerfilUsuario.DoesNotExist:
        perfil_activo = None
    return usuario.is_active != legacy_activo or (
        perfil_activo is not None and perfil_activo != legacy_activo
    )


def _resultado_revision(*, source, legacy_id, username, email, legacy_rol, propuesta, razon, accion=AccionIdentidadLegacy.REQUIERE_REVISION, user=None):
    return ResolucionIdentidadLegacy(
        legacy_source=source,
        legacy_id=legacy_id,
        legacy_username=username,
        legacy_email=email,
        legacy_rol=legacy_rol,
        accion=accion,
        django_user_id=user.pk if user else None,
        confianza=None,
        rol_destino=propuesta.rol_destino,
        requiere_revision=True,
        razon=razon,
    )


def resolver_identidad_legacy(*, legacy_source, legacy_id, legacy_username="", legacy_email="", legacy_rol="", legacy_activo=None):
    """Decide un vínculo sin crear, editar o habilitar cuentas Django.

    El resultado es idempotente: la misma entrada y el mismo estado de la
    base devuelven la misma decisión. La futura importación deberá persistir
    ``IdentidadLegacyUsuario`` sólo después de aceptar el resultado.
    """
    source = str(legacy_source or "").strip()
    legacy_id = str(legacy_id or "").strip()
    username = normalizar_username(legacy_username)
    email = normalizar_correo(legacy_email)
    rol_original = str(legacy_rol or "").strip()
    propuesta = proponer_rol_legacy(rol_original)

    existente = IdentidadLegacyUsuario.objects.filter(
        legacy_source=source, legacy_id=legacy_id
    ).select_related("user__perfil").first()
    usuarios_email = _usuarios_por_campo("email", email)
    usuarios_username = _usuarios_por_campo("username", username)

    if len(usuarios_email) > 1:
        return _resultado_revision(source=source, legacy_id=legacy_id, username=username, email=email, legacy_rol=rol_original, propuesta=propuesta, razon="EMAIL_DUPLICADO")
    if len(usuarios_username) > 1:
        return _resultado_revision(source=source, legacy_id=legacy_id, username=username, email=email, legacy_rol=rol_original, propuesta=propuesta, razon="USERNAME_DUPLICADO")
    if _identidades_por_campo("legacy_email", email, excluir=(source, legacy_id)):
        return _resultado_revision(source=source, legacy_id=legacy_id, username=username, email=email, legacy_rol=rol_original, propuesta=propuesta, razon="LEGACY_EMAIL_DUPLICADO")
    if _identidades_por_campo("legacy_username", username, excluir=(source, legacy_id)):
        return _resultado_revision(source=source, legacy_id=legacy_id, username=username, email=email, legacy_rol=rol_original, propuesta=propuesta, razon="LEGACY_USERNAME_DUPLICADO")
    if usuarios_email and usuarios_username and usuarios_email[0].pk != usuarios_username[0].pk:
        return _resultado_revision(source=source, legacy_id=legacy_id, username=username, email=email, legacy_rol=rol_original, propuesta=propuesta, razon="EMAIL_USERNAME_DIFIEREN")

    candidato = usuarios_email[0] if usuarios_email else (usuarios_username[0] if usuarios_username else None)
    confianza = "EXACT_EMAIL" if usuarios_email else ("EXACT_USERNAME" if usuarios_username else None)
    if existente:
        if candidato and candidato.pk != existente.user_id:
            return _resultado_revision(source=source, legacy_id=legacy_id, username=username, email=email, legacy_rol=rol_original, propuesta=propuesta, razon="IDENTIDAD_LEGACY_EN_CONFLICTO", accion=AccionIdentidadLegacy.CONFLICTO, user=existente.user)
        candidato = existente.user
        confianza = "IDENTIDAD_EXISTENTE"

    if candidato and _discrepancia_actividad(candidato, legacy_activo):
        return _resultado_revision(source=source, legacy_id=legacy_id, username=username, email=email, legacy_rol=rol_original, propuesta=propuesta, razon="ESTADO_ACTIVO_DISCREPANTE", user=candidato)
    if candidato:
        return ResolucionIdentidadLegacy(
            legacy_source=source,
            legacy_id=legacy_id,
            legacy_username=username,
            legacy_email=email,
            legacy_rol=rol_original,
            accion=AccionIdentidadLegacy.MATCH_EXISTENTE,
            django_user_id=candidato.pk,
            confianza=confianza,
            rol_destino=propuesta.rol_destino,
            requiere_revision=propuesta.requiere_revision,
            razon=propuesta.razon,
        )
    return ResolucionIdentidadLegacy(
        legacy_source=source,
        legacy_id=legacy_id,
        legacy_username=username,
        legacy_email=email,
        legacy_rol=rol_original,
        accion=AccionIdentidadLegacy.CREAR_NUEVO,
        django_user_id=None,
        confianza=None,
        rol_destino=propuesta.rol_destino,
        requiere_revision=propuesta.requiere_revision,
        razon=propuesta.razon,
        # Las nuevas cuentas se habilitarán por invitación/restablecimiento u
        # OAuth; este servicio jamás activa cuentas por un dato legacy.
        habilitar_user=False,
        habilitar_perfil=False,
    )


def validar_preparacion_identidades_legacy(registros):
    """Detecta ambigüedades de un lote antes de que el importador escriba."""
    por_email = defaultdict(list)
    por_username = defaultdict(list)
    for registro in registros:
        obtener = registro.get if isinstance(registro, dict) else getattr
        source = str(obtener("legacy_source", "") or "").strip()
        legacy_id = str(obtener("legacy_id", "") or "").strip()
        clave = f"{source}:{legacy_id}"
        email = normalizar_correo(obtener("legacy_email", ""))
        username = normalizar_username(obtener("legacy_username", ""))
        if email:
            por_email[email].append(clave)
        if username:
            por_username[username].append(clave)

    alertas = []
    for email, ids in por_email.items():
        if len(ids) > 1:
            alertas.append(AlertaPreparacionLegacy("LEGACY_EMAIL_DUPLICADO", email, tuple(ids)))
    for username, ids in por_username.items():
        if len(ids) > 1:
            alertas.append(AlertaPreparacionLegacy("LEGACY_USERNAME_DUPLICADO", username, tuple(ids)))
    for email in por_email:
        usuarios = _usuarios_por_campo("email", email)
        if len(usuarios) > 1:
            alertas.append(AlertaPreparacionLegacy("EMAIL_DUPLICADO", email, django_user_ids=tuple(usuario.pk for usuario in usuarios)))
    for username in por_username:
        usuarios = _usuarios_por_campo("username", username)
        if len(usuarios) > 1:
            alertas.append(AlertaPreparacionLegacy("USERNAME_DUPLICADO", username, django_user_ids=tuple(usuario.pk for usuario in usuarios)))
    return tuple(alertas)
