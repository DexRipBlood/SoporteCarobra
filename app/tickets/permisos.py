from django.db.models import Q
from django.utils import timezone

from usuarios.models import PerfilUsuario
from usuarios.permisos import es_administrador

from .models import Ticket


def usuario_tiene_acceso_operativo(user):
    if not user.is_authenticated or not user.is_active:
        return False

    if user.is_superuser:
        return True

    try:
        return user.perfil.activo
    except PerfilUsuario.DoesNotExist:
        return False


def tickets_visibles_para(user, queryset=None):
    queryset = queryset if queryset is not None else Ticket.objects.all()

    if not usuario_tiene_acceso_operativo(user):
        return queryset.none()

    if es_administrador(user) or getattr(getattr(user, "perfil", None), "puede_ver_todos", False):
        return queryset

    return queryset.filter(
        Q(creado_por=user)
        | Q(responsable=user)
        | Q(partner=user)
        | Q(suplente=user, suplente_hasta__gt=timezone.now())
    ).distinct()


def participa_en_ticket(user, ticket):
    return es_administrador(user) or user.pk in (ticket.creado_por_id, ticket.responsable_id, ticket.partner_id) or (
        ticket.suplente_id == user.pk and ticket.suplente_hasta is not None and ticket.suplente_hasta > timezone.now()
    )
