from django.urls import path
from django.contrib.auth import views as auth_views
from .forms import CambiarPasswordForm, RecuperarPasswordForm

from .views import (
    admin_panel,
    dashboard,
    mi_panel,
    perfil,
    usuario_crear,
    usuario_editar,
    usuario_foto,
    usuarios_lista,
)


urlpatterns = [
    path(
        "",
        dashboard,
        name="home",
    ),

    path(
        "dashboard/",
        dashboard,
        name="dashboard",
    ),

    path(
        "admin-panel/",
        admin_panel,
        name="admin_panel",
    ),

    path(
        "mi-panel/",
        mi_panel,
        name="mi_panel",
    ),

    path(
        "perfil/",
        perfil,
        name="perfil",
    ),

    path(
        "usuarios/",
        usuarios_lista,
        name="usuarios_lista",
    ),

    path(
        "usuarios/nuevo/",
        usuario_crear,
        name="usuario_crear",
    ),

    path(
        "usuarios/<int:user_id>/editar/",
        usuario_editar,
        name="usuario_editar",
    ),

    path(
        "usuarios/<int:user_id>/foto/",
        usuario_foto,
        name="usuario_foto",
    ),

    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="usuarios/login.html"
        ),
        name="login",
    ),

    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),

    path(
        "recuperar-contrasena/",
        auth_views.PasswordResetView.as_view(
            template_name="usuarios/password_reset_form.html",
            form_class=RecuperarPasswordForm,
            email_template_name="usuarios/emails/password_reset.txt",
            html_email_template_name="usuarios/emails/password_reset.html",
            subject_template_name="usuarios/emails/password_reset_asunto.txt",
            success_url="/recuperar-contrasena/enviado/",
        ),
        name="password_reset",
    ),
    path(
        "recuperar-contrasena/enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="usuarios/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "restablecer/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="usuarios/password_reset_confirm.html",
            form_class=CambiarPasswordForm,
            success_url="/restablecer/completado/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "restablecer/completado/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="usuarios/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
]
