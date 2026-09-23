from django.conf import settings


def google_oauth(request):
    """Expone solo si Google OAuth está listo, nunca sus credenciales."""
    return {
        "google_oauth_enabled": bool(
            settings.GOOGLE_OAUTH_CLIENT_ID
            and settings.GOOGLE_OAUTH_CLIENT_SECRET
        ),
        "email_enabled": settings.EMAIL_CONFIGURED,
    }
