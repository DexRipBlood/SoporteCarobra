from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from usuarios.adapters import GoogleSocialAccountAdapter
from usuarios.models import IdentidadLegacyUsuario, PerfilUsuario
from usuarios.services.legacy import (
    AccionIdentidadLegacy,
    proponer_rol_legacy,
    resolver_identidad_legacy,
    sanear_datos_origen_legacy,
    validar_preparacion_identidades_legacy,
)


User = get_user_model()


class IdentidadLegacyUsuarioTests(TestCase):
    def crear_usuario(self, username, email="", *, activo=True, perfil_activo=True):
        user = User.objects.create_user(username=username, email=email, is_active=activo)
        PerfilUsuario.objects.create(user=user, activo=perfil_activo)
        return user

    def test_match_exacto_por_correo(self):
        user = self.crear_usuario("jlopez", "jlopez@empresa.com")

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_username="jlopez",
            legacy_email="jlopez@empresa.com", legacy_rol="SOPORTE",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.MATCH_EXISTENTE)
        self.assertEqual(resultado.django_user_id, user.pk)
        self.assertEqual(resultado.confianza, "EXACT_EMAIL")
        self.assertEqual(resultado.rol_destino, PerfilUsuario.Rol.USUARIO)

    def test_correo_normaliza_mayusculas_y_espacios(self):
        user = self.crear_usuario("jlopez", "jlopez@empresa.com")

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_email="  JLOPEZ@EMPRESA.COM  ",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.MATCH_EXISTENTE)
        self.assertEqual(resultado.django_user_id, user.pk)

    def test_fallback_por_username_sin_correo(self):
        user = self.crear_usuario("jlopez")

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_username=" JLOPEZ ",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.MATCH_EXISTENTE)
        self.assertEqual(resultado.django_user_id, user.pk)
        self.assertEqual(resultado.confianza, "EXACT_USERNAME")

    def test_conflicto_por_email_duplicado(self):
        self.crear_usuario("uno", "persona@empresa.com")
        self.crear_usuario("dos", "PERSONA@EMPRESA.COM")

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_email="persona@empresa.com",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.REQUIERE_REVISION)
        self.assertEqual(resultado.razon, "EMAIL_DUPLICADO")

    def test_conflicto_si_email_y_username_apuntan_a_usuarios_distintos(self):
        self.crear_usuario("por-correo", "persona@empresa.com")
        self.crear_usuario("por-username", "otro@empresa.com")

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_email="persona@empresa.com",
            legacy_username="por-username",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.REQUIERE_REVISION)
        self.assertEqual(resultado.razon, "EMAIL_USERNAME_DIFIEREN")

    def test_match_por_correo_no_conflicta_con_username_sin_otra_cuenta(self):
        user = self.crear_usuario("cuenta-django", "persona@empresa.com")

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_email="persona@empresa.com",
            legacy_username="usuario-historico-distinto",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.MATCH_EXISTENTE)
        self.assertEqual(resultado.django_user_id, user.pk)
        self.assertEqual(resultado.confianza, "EXACT_EMAIL")

    def test_conflicto_por_username_normalizado_ambiguo(self):
        self.crear_usuario("JLopez", "uno@empresa.com")
        self.crear_usuario("jlopez", "dos@empresa.com")

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_username=" jlopez ",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.REQUIERE_REVISION)
        self.assertEqual(resultado.razon, "USERNAME_DUPLICADO")

    def test_conflicto_por_email_legacy_ya_persistido(self):
        primero = self.crear_usuario("uno", "uno@empresa.com")
        self.crear_usuario("dos", "dos@empresa.com")
        IdentidadLegacyUsuario.objects.create(
            user=primero,
            legacy_source="php",
            legacy_id="16",
            legacy_email="persona@empresa.com",
        )

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_email="persona@empresa.com",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.REQUIERE_REVISION)
        self.assertEqual(resultado.razon, "LEGACY_EMAIL_DUPLICADO")

    def test_sin_coincidencia_es_candidato_a_crear_sin_habilitar(self):
        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_username="nueva",
            legacy_email="nueva@empresa.com", legacy_activo=True,
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.CREAR_NUEVO)
        self.assertIsNone(resultado.django_user_id)
        self.assertFalse(resultado.habilitar_user)
        self.assertFalse(resultado.habilitar_perfil)

    def test_identidad_legacy_no_puede_duplicarse_por_source_e_id(self):
        user = self.crear_usuario("jlopez")
        IdentidadLegacyUsuario.objects.create(user=user, legacy_source="php", legacy_id="17")

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                IdentidadLegacyUsuario.objects.create(user=user, legacy_source="php", legacy_id="17")

    def test_roles_admin_y_superroot_proponen_admin(self):
        for rol in ("ADMIN", "SUPERROOT"):
            with self.subTest(rol=rol):
                self.assertEqual(proponer_rol_legacy(rol).rol_destino, PerfilUsuario.Rol.ADMIN)

    def test_roles_operativos_proponen_usuario_sin_permisos_elevados(self):
        for rol in ("SOPORTE", "COORDINADOR", "INTERNO"):
            with self.subTest(rol=rol):
                propuesta = proponer_rol_legacy(rol)
                self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
                self.assertFalse(hasattr(propuesta, "puede_ver_todos"))

    def test_rol_legacy_vacio_requiere_revision(self):
        for rol in ("", None):
            with self.subTest(rol=rol):
                propuesta = proponer_rol_legacy(rol)
                self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
                self.assertTrue(propuesta.requiere_revision)
                self.assertEqual(propuesta.razon, "ROL_LEGACY_VACIO")

    def test_rol_legacy_desconocido_requiere_revision(self):
        propuesta = proponer_rol_legacy("JEFE_REGIONAL")

        self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
        self.assertTrue(propuesta.requiere_revision)
        self.assertEqual(propuesta.razon, "ROL_LEGACY_DESCONOCIDO")

    def test_google_oauth_sigue_sin_autoregistro(self):
        self.assertFalse(GoogleSocialAccountAdapter().is_open_for_signup(None, None))

    def test_usuario_django_existente_no_es_modificado_por_resolucion(self):
        user = self.crear_usuario("jlopez", "jlopez@empresa.com")

        resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_email="jlopez@empresa.com",
        )
        user.refresh_from_db()

        self.assertTrue(user.is_active)
        self.assertTrue(user.perfil.activo)
        self.assertEqual(IdentidadLegacyUsuario.objects.count(), 0)

    def test_legacy_inactivo_no_habilita_ni_desactiva_cuenta_existente(self):
        user = self.crear_usuario("jlopez", "jlopez@empresa.com", activo=True, perfil_activo=True)

        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="17", legacy_email="jlopez@empresa.com",
            legacy_activo=False,
        )
        user.refresh_from_db()

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.REQUIERE_REVISION)
        self.assertEqual(resultado.razon, "ESTADO_ACTIVO_DISCREPANTE")
        self.assertTrue(user.is_active)
        self.assertTrue(user.perfil.activo)

    def test_validacion_previa_detecta_email_legacy_repetido(self):
        alertas = validar_preparacion_identidades_legacy([
            {"legacy_source": "php", "legacy_id": "17", "legacy_email": "persona@empresa.com"},
            {"legacy_source": "php", "legacy_id": "18", "legacy_email": " PERSONA@EMPRESA.COM "},
        ])

        self.assertEqual(alertas[0].codigo, "LEGACY_EMAIL_DUPLICADO")

    def test_validacion_previa_acepta_objetos(self):
        @dataclass
        class RegistroLegacy:
            legacy_source: str
            legacy_id: str
            legacy_email: str
            legacy_username: str = ""

        alertas = validar_preparacion_identidades_legacy([
            RegistroLegacy("php", "17", "persona@empresa.com"),
            RegistroLegacy("php", "18", " PERSONA@EMPRESA.COM "),
        ])

        self.assertEqual(alertas[0].codigo, "LEGACY_EMAIL_DUPLICADO")

    def test_resolver_requiere_source_legacy(self):
        resultado = resolver_identidad_legacy(
            legacy_source="", legacy_id="17", legacy_email="nueva@empresa.com",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.REQUIERE_REVISION)
        self.assertEqual(resultado.razon, "LEGACY_SOURCE_FALTANTE")
        self.assertEqual(User.objects.count(), 0)

    def test_resolver_requiere_id_legacy(self):
        resultado = resolver_identidad_legacy(
            legacy_source="php", legacy_id="", legacy_email="nueva@empresa.com",
        )

        self.assertEqual(resultado.accion, AccionIdentidadLegacy.REQUIERE_REVISION)
        self.assertEqual(resultado.razon, "LEGACY_ID_FALTANTE")
        self.assertEqual(User.objects.count(), 0)

    def test_identidad_legacy_no_permite_source_o_id_vacios(self):
        user = self.crear_usuario("jlopez")

        for source, legacy_id in (("", "17"), ("php", "")):
            with self.subTest(source=source, legacy_id=legacy_id):
                with transaction.atomic():
                    with self.assertRaises(IntegrityError):
                        IdentidadLegacyUsuario.objects.create(
                            user=user,
                            legacy_source=source,
                            legacy_id=legacy_id,
                        )

    def test_constraint_rechaza_source_o_id_compuestos_solo_por_espacios(self):
        user = self.crear_usuario("jlopez")

        # bulk_create evita Model.save(), por lo que demuestra que la
        # protección está en la base de datos y no sólo en la normalización.
        for source, legacy_id in (("   ", "17"), ("php", "   ")):
            with self.subTest(source=source, legacy_id=legacy_id):
                with transaction.atomic():
                    with self.assertRaises(IntegrityError):
                        IdentidadLegacyUsuario.objects.bulk_create([
                            IdentidadLegacyUsuario(
                                user=user,
                                legacy_source=source,
                                legacy_id=legacy_id,
                            ),
                        ])

    def test_identidad_legacy_no_se_duplica_con_espacios_en_identificadores(self):
        user = self.crear_usuario("jlopez")
        IdentidadLegacyUsuario.objects.create(
            user=user,
            legacy_source="php",
            legacy_id="17",
        )

        # También se evita si una inserción evita Model.save().
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                IdentidadLegacyUsuario.objects.bulk_create([
                    IdentidadLegacyUsuario(
                        user=user,
                        legacy_source=" php ",
                        legacy_id="17",
                    ),
                ])

    def test_password_hash_no_llega_a_datos_origen_persistidos(self):
        user = self.crear_usuario("jlopez")
        identidad = IdentidadLegacyUsuario.objects.create(
            user=user,
            legacy_source="php",
            legacy_id="17",
            datos_origen={"username": "jlopez", "password_hash": "secreto"},
        )
        identidad.refresh_from_db()

        self.assertNotIn("password_hash", identidad.datos_origen)
        self.assertEqual(identidad.datos_origen["username"], "jlopez")

    def test_tokens_y_sesiones_no_llegan_a_datos_origen(self):
        datos = {
            "remember_token": "recordarme",
            "ACCESS_TOKEN": "acceso",
            "refreshToken": "refresco",
            "session_id": "sesion",
            "perfil": {"Token": "anidado", "nombre": "Julia"},
        }

        saneados = sanear_datos_origen_legacy(datos)

        self.assertEqual(saneados, {"perfil": {"nombre": "Julia"}})

    def test_datos_normales_se_conservan_en_saneador(self):
        datos = {
            "username": "jlopez",
            "correo": "jlopez@empresa.com",
            "nombre": "Julia López",
            "rol": "SOPORTE",
            "telefono": "55555555",
            "puesto": "Analista",
            "activo": True,
        }

        self.assertEqual(sanear_datos_origen_legacy(datos), datos)

    def test_saneador_no_modifica_diccionario_original(self):
        datos = {
            "password": "secreto",
            "perfil": {"access_token": "privado", "nombre": "Julia"},
        }

        sanear_datos_origen_legacy(datos)

        self.assertEqual(datos["password"], "secreto")
        self.assertEqual(datos["perfil"]["access_token"], "privado")
