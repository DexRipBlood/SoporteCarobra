from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import PerfilUsuario


def es_administrador(user):
    if not user.is_authenticated or not user.is_active:
        return False

    if user.is_superuser:
        return True

    try:
        perfil = user.perfil
    except PerfilUsuario.DoesNotExist:
        return False

    return perfil.activo and perfil.rol == PerfilUsuario.Rol.ADMIN


def administrador_required(view_function):
    @login_required
    @wraps(view_function)
    def wrapped_view(request, *args, **kwargs):
        if not es_administrador(request.user):
            raise PermissionDenied

        return view_function(request, *args, **kwargs)

    return wrapped_view
