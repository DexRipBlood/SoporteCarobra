import logging

from django.conf import settings

from .forms import RecuperarPasswordForm


logger = logging.getLogger(__name__)


def enviar_invitacion_usuario(usuario, request):
    """Envía un enlace de un solo uso para definir o cambiar la contraseña."""
    if not settings.EMAIL_CONFIGURED or not usuario.email or not usuario.is_active:
        return False

    formulario = RecuperarPasswordForm({"email": usuario.email})
    if not formulario.is_valid():
        return False

    try:
        formulario.save(
            request=request,
            use_https=request.is_secure(),
            subject_template_name="usuarios/emails/bienvenida_asunto.txt",
            email_template_name="usuarios/emails/bienvenida.txt",
            html_email_template_name="usuarios/emails/bienvenida.html",
            extra_email_context={"usuario_invitado": usuario},
        )
    except Exception:
        logger.exception("No se pudo enviar la invitación a %s", usuario.pk)
        return False

    return True
