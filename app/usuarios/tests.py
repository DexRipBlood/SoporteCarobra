from io import BytesIO
from io import StringIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import PerfilUsuario
from tickets.models import EstadoTicket, Ticket


User = get_user_model()


class DashboardResumenTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="clave")
        PerfilUsuario.objects.create(user=self.admin, rol=PerfilUsuario.Rol.ADMIN)
        self.operador = User.objects.create_user(username="operador", password="clave")
        PerfilUsuario.objects.create(user=self.operador)

    def test_admin_panel_muestra_metricas_reales(self):
        Ticket.objects.create(creado_por=self.operador, estado_interno=EstadoTicket.NUEVO)
        Ticket.objects.create(responsable=self.operador, estado_interno=EstadoTicket.EN_PROCESO)
        Ticket.objects.create(responsable=self.operador, estado_interno=EstadoTicket.CERRADO)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["activos"], 2)
        self.assertEqual(response.context["dashboard"]["sin_asignar"], 1)
        self.assertEqual(response.context["dashboard"]["en_proceso"], 1)

    def test_mi_panel_solo_cuenta_tickets_visibles(self):
        ajeno = User.objects.create_user(username="ajeno")
        PerfilUsuario.objects.create(user=ajeno)
        Ticket.objects.create(responsable=self.operador, estado_interno=EstadoTicket.NUEVO)
        Ticket.objects.create(responsable=ajeno, estado_interno=EstadoTicket.NUEVO)
        self.client.force_login(self.operador)

        response = self.client.get(reverse("mi_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["activos"], 1)


def foto_de_prueba(nombre="avatar.png", color=(55, 103, 230)):
    contenido = BytesIO()
    Image.new("RGB", (900, 600), color).save(contenido, format="PNG")
    return SimpleUploadedFile(
        nombre,
        contenido.getvalue(),
        content_type="image/png",
    )


class PerfilUsuarioViewTests(TestCase):
    def setUp(self):
        self.media_temporal = TemporaryDirectory()
        self.addCleanup(self.media_temporal.cleanup)
        self.media_settings = override_settings(
            MEDIA_ROOT=self.media_temporal.name
        )
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.user = User.objects.create_user(
            username="marco",
            password="clave-segura",
            email="anterior@empresa.com",
        )

    def test_perfil_requiere_autenticacion(self):
        response = self.client.get(reverse("perfil"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('perfil')}",
        )

    def test_get_crea_perfil_y_muestra_formulario(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("perfil"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Información personal")
        self.assertContains(response, 'value="anterior@empresa.com"')
        self.assertTrue(
            PerfilUsuario.objects.filter(user=self.user).exists()
        )

        content = response.content.decode()
        theme_bootstrap = content.index(
            'localStorage.getItem("carobra_theme")'
        )
        first_stylesheet = content.index('rel="stylesheet"')
        self.assertLess(theme_bootstrap, first_stylesheet)

    def test_post_actualiza_usuario_y_datos_corporativos(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("perfil"),
            {
                "first_name": "Marco",
                "last_name": "Fong",
                "email": "marco@empresa.com",
                "numero_empleado": "CRB-0248",
                "telefono": "+52 55 1234 5678",
                "area": "Operaciones",
                "cargo": "Analista",
            },
        )

        self.assertRedirects(response, reverse("perfil"))
        self.user.refresh_from_db()
        perfil = self.user.perfil
        self.assertEqual(self.user.get_full_name(), "Marco Fong")
        self.assertEqual(self.user.email, "marco@empresa.com")
        self.assertEqual(perfil.numero_empleado, "CRB-0248")
        self.assertEqual(perfil.area, "Operaciones")
        self.assertEqual(perfil.cargo, "Analista")

    def test_post_rechaza_correo_asignado_a_otra_cuenta(self):
        User.objects.create_user(
            username="otra-cuenta",
            email="ocupado@empresa.com",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("perfil"),
            {
                "first_name": "Marco",
                "last_name": "Fong",
                "email": "OCUPADO@empresa.com",
                "numero_empleado": "",
                "telefono": "",
                "area": "",
                "cargo": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Este correo ya está asociado a otra cuenta.",
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "anterior@empresa.com")

    def test_usuario_puede_subir_y_consultar_su_foto(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("perfil"),
            {
                "first_name": "Marco",
                "last_name": "Fong",
                "email": "marco@empresa.com",
                "numero_empleado": "CRB-0248",
                "telefono": "+52 55 1234 5678",
                "area": "Operaciones",
                "cargo": "Analista",
                "foto": foto_de_prueba(),
            },
        )

        self.assertRedirects(response, reverse("perfil"))
        self.user.perfil.refresh_from_db()
        self.assertTrue(self.user.perfil.foto.name.endswith(".webp"))

        photo_response = self.client.get(
            reverse("usuario_foto", args=[self.user.pk])
        )
        self.assertEqual(photo_response.status_code, 200)
        self.assertEqual(photo_response["Content-Type"], "image/webp")
        self.assertEqual(photo_response["Cache-Control"], "private, max-age=3600")

        self.client.logout()
        anonymous_response = self.client.get(
            reverse("usuario_foto", args=[self.user.pk])
        )
        self.assertRedirects(
            anonymous_response,
            f"{reverse('login')}?next={reverse('usuario_foto', args=[self.user.pk])}",
        )

    def test_usuario_puede_quitar_su_foto(self):
        perfil = PerfilUsuario.objects.create(
            user=self.user,
            foto=foto_de_prueba(),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("perfil"),
            {
                "first_name": "Marco",
                "last_name": "Fong",
                "email": "marco@empresa.com",
                "numero_empleado": "",
                "telefono": "",
                "area": "",
                "cargo": "",
                "eliminar_foto": "on",
            },
        )

        self.assertRedirects(response, reverse("perfil"))
        perfil.refresh_from_db()
        self.assertFalse(perfil.foto)


class AdministracionUsuariosTests(TestCase):
    def setUp(self):
        self.media_temporal = TemporaryDirectory()
        self.addCleanup(self.media_temporal.cleanup)
        self.media_settings = override_settings(
            MEDIA_ROOT=self.media_temporal.name
        )
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.admin = User.objects.create_user(
            username="administrador",
            password="clave-segura",
            first_name="Admin",
            email="admin@empresa.com",
        )
        self.admin_profile = PerfilUsuario.objects.create(
            user=self.admin,
            rol=PerfilUsuario.Rol.ADMIN,
        )
        self.regular_user = User.objects.create_user(
            username="operador",
            password="clave-segura",
            email="operador@empresa.com",
        )
        PerfilUsuario.objects.create(user=self.regular_user)

    def user_payload(self, **overrides):
        payload = {
            "username": "nuevo.usuario",
            "first_name": "Nuevo",
            "last_name": "Usuario",
            "email": "nuevo@empresa.com",
            "numero_empleado": "CRB-100",
            "telefono": "+52 55 1111 2222",
            "area": "Operaciones",
            "cargo": "Analista",
            "rol": PerfilUsuario.Rol.USUARIO,
            "activo": "on",
            "password1": "ClaveTemporal123!",
            "password2": "ClaveTemporal123!",
        }
        payload.update(overrides)
        return payload

    def test_usuario_regular_no_puede_abrir_administracion(self):
        self.client.force_login(self.regular_user)

        response = self.client.get(reverse("usuarios_lista"))

        self.assertEqual(response.status_code, 403)

    def test_administrador_puede_listar_usuarios(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("usuarios_lista"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Equipo y permisos")
        self.assertContains(response, "operador@empresa.com")

    def test_administrador_puede_abrir_formulario_de_nuevo_usuario(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("usuario_crear"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Agregar colaborador")
        self.assertContains(response, "Foto de perfil")

    def test_administrador_puede_crear_usuario(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("usuario_crear"),
            self.user_payload(),
        )

        self.assertRedirects(response, reverse("usuarios_lista"))
        created_user = User.objects.get(username="nuevo.usuario")
        self.assertTrue(created_user.check_password("ClaveTemporal123!"))
        self.assertTrue(created_user.is_active)
        self.assertEqual(created_user.perfil.area, "Operaciones")
        self.assertEqual(
            created_user.perfil.rol,
            PerfilUsuario.Rol.USUARIO,
        )

    @override_settings(
        EMAIL_CONFIGURED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="soporte@carobra.test",
    )
    def test_crear_usuario_envia_invitacion_para_definir_password(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("usuario_crear"),
            self.user_payload(),
        )

        self.assertRedirects(response, reverse("usuarios_lista"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["nuevo@empresa.com"])
        self.assertIn("/restablecer/", mail.outbox[0].body)
        html = next(
            alternativa.content
            for alternativa in mail.outbox[0].alternatives
            if alternativa.mimetype == "text/html"
        )
        self.assertIn("Tu acceso está listo", html)
        self.assertIn("OPERATIONS CENTER", html)
        self.assertIn("Usuario asignado", html)


    def test_administrador_puede_crear_usuario_con_foto(self):
        self.client.force_login(self.admin)
        payload = self.user_payload(username="usuario.foto", email="foto@empresa.com")
        payload["foto"] = foto_de_prueba("colaborador.png")

        response = self.client.post(reverse("usuario_crear"), payload)

        self.assertRedirects(response, reverse("usuarios_lista"))
        created_user = User.objects.get(username="usuario.foto")
        self.assertTrue(created_user.perfil.foto.name.endswith(".webp"))

    def test_edicion_desactiva_el_acceso_sin_borrar_usuario(self):
        self.client.force_login(self.admin)
        payload = self.user_payload(
            username=self.regular_user.username,
            first_name="Operador",
            last_name="Uno",
            email=self.regular_user.email,
            password1="",
            password2="",
        )
        payload.pop("activo")

        response = self.client.post(
            reverse("usuario_editar", args=[self.regular_user.pk]),
            payload,
        )

        self.assertRedirects(response, reverse("usuarios_lista"))
        self.regular_user.refresh_from_db()
        self.regular_user.perfil.refresh_from_db()
        self.assertFalse(self.regular_user.is_active)
        self.assertFalse(self.regular_user.perfil.activo)
        self.client.logout()
        self.assertFalse(
            self.client.login(
                username="operador",
                password="clave-segura",
            )
        )

    def test_administrador_no_puede_desactivarse_a_si_mismo(self):
        self.client.force_login(self.admin)
        payload = self.user_payload(
            username=self.admin.username,
            first_name=self.admin.first_name,
            last_name=self.admin.last_name,
            email=self.admin.email,
            rol=PerfilUsuario.Rol.ADMIN,
            password1="",
            password2="",
        )
        payload.pop("activo")

        response = self.client.post(
            reverse("usuario_editar", args=[self.admin.pk]),
            payload,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "No puedes desactivar tu propia cuenta.",
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)


class RecuperacionPasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="recuperar",
            password="ClaveAnterior123!",
            email="recuperar@empresa.com",
        )
        PerfilUsuario.objects.create(user=self.user, activo=True)

    @override_settings(
        EMAIL_CONFIGURED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="soporte@carobra.test",
    )
    def test_usuario_puede_solicitar_correo_de_recuperacion(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("/restablecer/", mail.outbox[0].body)
        html = next(
            alternativa.content
            for alternativa in mail.outbox[0].alternatives
            if alternativa.mimetype == "text/html"
        )
        self.assertIn("Restablece tu contraseña", html)
        self.assertIn("SEGURIDAD DE CUENTA", html)

    @override_settings(
        EMAIL_CONFIGURED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="soporte@carobra.test",
    )
    def test_muestra_error_cuando_el_correo_no_esta_registrado(self):
        response = self.client.post(
            reverse("password_reset"),
            {"email": "desconocido@empresa.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "No encontramos una cuenta activa asociada a este correo.",
        )
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_CONFIGURED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="soporte@carobra.test",
    )
    def test_cuenta_google_puede_establecer_password_local(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])

        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("/restablecer/", mail.outbox[0].body)

    @override_settings(
        EMAIL_CONFIGURED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="soporte@carobra.test",
        PUBLIC_BASE_URL="https://soportecarobra.online",
    )
    def test_comando_envia_correo_corporativo_sin_crear_usuario(self):
        output = StringIO()

        call_command(
            "enviar_correo_prueba",
            "destino@empresa.com",
            stdout=output,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["destino@empresa.com"])
        self.assertIn("Correo de prueba enviado", output.getvalue())
        html = next(
            alternativa.content
            for alternativa in mail.outbox[0].alternatives
            if alternativa.mimetype == "text/html"
        )
        self.assertIn("El correo está funcionando", html)
        self.assertIn("https://soportecarobra.online/login/", html)

    @override_settings(EMAIL_CONFIGURED=True)
    def test_login_muestra_enlace_de_recuperacion(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "¿Olvidaste tu contraseña?")
