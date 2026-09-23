from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect


User = get_user_model()


class GoogleSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Permite Google únicamente para usuarios internos preautorizados."""

    def is_open_for_signup(self, request, sociallogin):
        return False

    def pre_social_login(self, request, sociallogin):
        super().pre_social_login(request, sociallogin)

        email = (sociallogin.user.email or "").strip()
        usuario = (
            User.objects
            .filter(
                email__iexact=email,
                is_active=True,
                perfil__activo=True,
            )
            .first()
        )

        if not email or usuario is None:
            messages.error(
                request,
                "Tu cuenta de Google no está autorizada para acceder al sistema.",
            )
            raise ImmediateHttpResponse(redirect("login"))
