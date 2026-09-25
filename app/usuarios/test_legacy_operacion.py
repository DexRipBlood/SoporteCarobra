from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase

from tickets.models import (
    Empresa,
    GrupoSoporte,
    GrupoTrabajo,
    SubgrupoSoporte,
    Tienda,
    Ticket,
    Zona,
)
from tickets.permisos import tickets_visibles_para
from usuarios.models import PerfilUsuario
from usuarios.services.legacy_operacion import (
    EstadoResolucionLegacy,
    proponer_asignacion_personal_legacy,
    proponer_guardia_legacy,
    proponer_operacion_legacy,
    resolver_tienda_legacy,
    resolver_zona_legacy,
)


User = get_user_model()


class PropuestasOperacionLegacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user("operador-legacy")
        cls.otro_usuario = User.objects.create_user("otro-operador")
        cls.perfil = PerfilUsuario.objects.create(user=cls.usuario)
        PerfilUsuario.objects.create(user=cls.otro_usuario)
        cls.empresa = Empresa.objects.create(codigo="BRADESCARD", nombre="Bradescard")
        cls.otra_empresa = Empresa.objects.create(codigo="OTRA", nombre="Otra empresa")
        cls.zona = Zona.objects.create(
            empresa=cls.empresa, codigo="NORTE", nombre="Zona Norte", estado="Nuevo León",
        )
        cls.zona_otra_empresa = Zona.objects.create(
            empresa=cls.otra_empresa, codigo="SUR", nombre="Zona Sur externa", estado="Jalisco",
        )
        cls.tienda = Tienda.objects.create(
            empresa=cls.empresa, zona=cls.zona, id_externo="LEG-101", clave="K-101",
            numero="101", nombre="Tienda 101", estado="Nuevo León",
        )
        Tienda.objects.create(
            empresa=cls.empresa, zona=cls.zona, numero="205", nombre="Tienda 205-A", estado="Nuevo León",
        )
        Tienda.objects.create(
            empresa=cls.empresa, zona=cls.zona, numero="205", nombre="Tienda 205-B", estado="Nuevo León",
        )
        cls.grupo_soporte = GrupoSoporte.objects.create(nombre="SOPORTE TIENDAS")
        cls.subgrupo = SubgrupoSoporte.objects.create(grupo=cls.grupo_soporte, nombre="REDES")
        cls.grupo_trabajo = GrupoTrabajo.objects.create(empresa=cls.empresa, nombre="SOPORTE OCCIDENTE")
        cls.grupo_trabajo_mismo_nombre = GrupoTrabajo.objects.create(
            empresa=cls.empresa, nombre="SOPORTE TIENDAS",
        )

    def propuesta(self, rol, **kwargs):
        return proponer_operacion_legacy(
            legacy_rol=rol, empresa_codigo=self.empresa.codigo, **kwargs,
        )

    def test_admin_y_superroot_proponen_admin_sin_capacidades_adicionales(self):
        for rol in ("ADMIN", "SUPERROOT"):
            with self.subTest(rol=rol):
                propuesta = self.propuesta(rol)
                self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.ADMIN)
                self.assertFalse(propuesta.requiere_revision)
                self.assertIsNone(propuesta.capacidades.puede_seguimiento)
                self.assertFalse(propuesta.capacidades.puede_ver_todos)

    def test_soporte_permanece_usuario_sin_acceso_global(self):
        propuesta = self.propuesta("SOPORTE")

        self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
        self.assertFalse(propuesta.capacidades.puede_ver_todos)
        self.assertFalse(propuesta.requiere_revision)

    def test_coordinador_permanece_usuario_sin_acceso_global(self):
        propuesta = self.propuesta("COORDINADOR")

        self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
        self.assertFalse(propuesta.capacidades.puede_ver_todos)

    def test_interno_permanece_usuario(self):
        propuesta = self.propuesta("INTERNO")

        self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
        self.assertFalse(propuesta.requiere_revision)

    def test_rol_desconocido_requiere_revision(self):
        propuesta = self.propuesta("JEFE_REGIONAL")

        self.assertEqual(propuesta.legacy_rol, "JEFE_REGIONAL")
        self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
        self.assertTrue(propuesta.requiere_revision)
        self.assertIn("ROL_LEGACY_DESCONOCIDO", propuesta.advertencias)

    def test_usuario_sin_empresa_queda_para_revision(self):
        propuesta = proponer_operacion_legacy(legacy_rol="SOPORTE")

        self.assertTrue(propuesta.requiere_revision)
        self.assertIn("EMPRESA_FALTANTE", propuesta.advertencias)

    def test_tienda_exacta_por_id_externo_y_empresa(self):
        empresa = self.propuesta("SOPORTE").empresa
        resultado = resolver_tienda_legacy(
            empresa=empresa, identificador="LEG-101", campo="id_externo",
        )

        self.assertEqual(resultado.estado, EstadoResolucionLegacy.RESUELTO)
        self.assertEqual(resultado.django_id, self.tienda.pk)

    def test_tienda_unica_sin_campo_no_se_resuelve(self):
        empresa = self.propuesta("SOPORTE").empresa
        resultado = resolver_tienda_legacy(empresa=empresa, identificador="LEG-101")

        self.assertEqual(resultado.estado, EstadoResolucionLegacy.REQUIERE_REVISION)
        self.assertIsNone(resultado.django_id)
        self.assertEqual(resultado.advertencias, ("TIENDA_CAMPO_FALTANTE",))

    def test_valor_en_campos_de_tiendas_distintas_sin_campo_no_se_elije(self):
        Tienda.objects.create(
            empresa=self.empresa, zona=self.zona, clave="MISMO-VALOR",
            nombre="Tienda por clave", estado="Nuevo León",
        )
        Tienda.objects.create(
            empresa=self.empresa, zona=self.zona, numero="MISMO-VALOR",
            nombre="Tienda por número", estado="Nuevo León",
        )
        empresa = self.propuesta("SOPORTE").empresa

        resultado = resolver_tienda_legacy(empresa=empresa, identificador="MISMO-VALOR")

        self.assertEqual(resultado.estado, EstadoResolucionLegacy.REQUIERE_REVISION)
        self.assertIsNone(resultado.django_id)
        self.assertIn("TIENDA_CAMPO_FALTANTE", resultado.advertencias)

    def test_tienda_inexistente_requiere_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        resultado = resolver_tienda_legacy(
            empresa=empresa, identificador="NO-EXISTE", campo="id_externo",
        )

        self.assertEqual(resultado.estado, EstadoResolucionLegacy.NO_ENCONTRADA)
        self.assertEqual(resultado.advertencias, ("TIENDA_NO_ENCONTRADA",))

    def test_tienda_ambigua_requiere_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        resultado = resolver_tienda_legacy(empresa=empresa, identificador="205", campo="numero")

        self.assertEqual(resultado.estado, EstadoResolucionLegacy.AMBIGUA)
        self.assertEqual(resultado.advertencias, ("TIENDA_AMBIGUA",))

    def test_zona_exacta_por_empresa_y_codigo(self):
        empresa = self.propuesta("SOPORTE").empresa
        resultado = resolver_zona_legacy(empresa=empresa, codigo="NORTE")

        self.assertEqual(resultado.estado, EstadoResolucionLegacy.RESUELTO)
        self.assertEqual(resultado.django_id, self.zona.pk)

    def test_zona_de_otra_empresa_no_se_vincula(self):
        empresa = self.propuesta("SOPORTE").empresa
        resultado = resolver_zona_legacy(empresa=empresa, codigo="SUR")

        self.assertEqual(resultado.estado, EstadoResolucionLegacy.NO_ENCONTRADA)
        self.assertIsNotNone(self.zona_otra_empresa.pk)

    def test_grupo_soporte_y_subgrupo_son_propuestas_de_enrutamiento(self):
        propuesta = self.propuesta(
            "SOPORTE",
            grupos_soporte=({"grupo_nombre": "SOPORTE TIENDAS", "subgrupo_nombre": "REDES"},),
        )

        grupo = propuesta.grupos_soporte[0]
        self.assertEqual(grupo.grupo.django_id, self.grupo_soporte.pk)
        self.assertEqual(grupo.subgrupo.django_id, self.subgrupo.pk)
        self.assertEqual(propuesta.grupos_trabajo, ())

    def test_grupo_soporte_no_se_convierte_en_grupo_trabajo_por_nombre(self):
        propuesta = self.propuesta(
            "SOPORTE",
            grupos_soporte=({"grupo_nombre": "SOPORTE TIENDAS"},),
        )

        self.assertEqual(propuesta.grupos_soporte[0].grupo.django_id, self.grupo_soporte.pk)
        self.assertEqual(propuesta.grupos_trabajo, ())
        self.assertTrue(GrupoTrabajo.objects.filter(pk=self.grupo_trabajo_mismo_nombre.pk).exists())

    def test_membresia_de_grupo_trabajo_se_propone_por_separado(self):
        propuesta = self.propuesta(
            "SOPORTE",
            grupos_trabajo=({"grupo_nombre": "SOPORTE OCCIDENTE", "nivel": "N2", "principal": True},),
        )

        membresia = propuesta.grupos_trabajo[0]
        self.assertEqual(membresia.grupo.django_id, self.grupo_trabajo.pk)
        self.assertEqual(membresia.nivel, "N2")
        self.assertTrue(membresia.principal)
        self.assertEqual(propuesta.grupos_soporte, ())

    def test_guardia_no_concede_puede_ver_todos(self):
        propuesta = self.propuesta(
            "SOPORTE",
            guardia={
                "legacy_usuario_id": "23", "grupo_nombre": "SOPORTE OCCIDENTE",
                "fecha_inicio": date(2026, 9, 1), "fecha_fin": date(2026, 9, 1),
                "hora_inicio": time(9), "hora_fin": time(18),
            },
        )

        self.assertFalse(propuesta.capacidades.puede_ver_todos)
        self.assertFalse(propuesta.guardia.requiere_revision)
        self.assertEqual(propuesta.guardia.grupo_trabajo.django_id, self.grupo_trabajo.pk)

    def test_cobertura_incompleta_queda_para_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        cobertura = proponer_asignacion_personal_legacy(
            empresa=empresa,
            alcance="TIENDA",
            funcion="PERSONAL",
        )

        self.assertTrue(cobertura.requiere_revision)
        self.assertIn("COBERTURA_INCOMPLETA", cobertura.advertencias)

    def test_cobertura_con_zona_y_tienda_contradictorias_queda_para_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        zona_ajena = Zona.objects.create(
            empresa=self.empresa, codigo="SUR", nombre="Zona Sur", estado="Jalisco",
        )
        cobertura = proponer_asignacion_personal_legacy(
            empresa=empresa,
            alcance="TIENDA",
            funcion="PERSONAL",
            zona_codigo=zona_ajena.codigo,
            tienda_identificador="LEG-101",
            tienda_campo="id_externo",
        )

        self.assertTrue(cobertura.requiere_revision)
        self.assertIn("COBERTURA_CONTRADICTORIA", cobertura.advertencias)

    def test_cobertura_estado_con_zona_o_tienda_es_incompatible(self):
        empresa = self.propuesta("SOPORTE").empresa
        cobertura = proponer_asignacion_personal_legacy(
            empresa=empresa,
            alcance="ESTADO",
            funcion="COORDINADOR_ESTATAL",
            estado="Nuevo León",
            zona_codigo="NORTE",
            tienda_identificador="LEG-101",
            tienda_campo="id_externo",
        )

        self.assertTrue(cobertura.requiere_revision)
        self.assertIn("COBERTURA_DATOS_INCOMPATIBLES_CON_ALCANCE", cobertura.advertencias)
        self.assertIsNotNone(cobertura.zona)
        self.assertIsNotNone(cobertura.tienda)

    def test_cobertura_zona_con_tienda_es_incompatible(self):
        empresa = self.propuesta("SOPORTE").empresa
        cobertura = proponer_asignacion_personal_legacy(
            empresa=empresa,
            alcance="ZONA",
            funcion="ENCARGADO_ZONAL",
            zona_codigo="NORTE",
            tienda_identificador="LEG-101",
            tienda_campo="id_externo",
        )

        self.assertTrue(cobertura.requiere_revision)
        self.assertIn("COBERTURA_DATOS_INCOMPATIBLES_CON_ALCANCE", cobertura.advertencias)

    def test_cobertura_con_periodo_invertido_queda_para_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        cobertura = proponer_asignacion_personal_legacy(
            empresa=empresa,
            alcance="ESTADO",
            funcion="COORDINADOR_ESTATAL",
            estado="Nuevo León",
            fecha_inicio=date(2026, 9, 2),
            fecha_fin=date(2026, 9, 1),
        )

        self.assertTrue(cobertura.requiere_revision)
        self.assertIn("COBERTURA_PERIODO_INVALIDO", cobertura.advertencias)

    def test_propuesta_no_modifica_permisos_productivos(self):
        valores_antes = (
            self.perfil.rol, self.perfil.puede_seguimiento, self.perfil.puede_cerrar,
            self.perfil.puede_reasignar, self.perfil.puede_ver_todos,
        )

        propuesta = self.propuesta("COORDINADOR")
        self.perfil.refresh_from_db()

        self.assertEqual(propuesta.rol_destino, PerfilUsuario.Rol.USUARIO)
        self.assertEqual(
            valores_antes,
            (
                self.perfil.rol, self.perfil.puede_seguimiento, self.perfil.puede_cerrar,
                self.perfil.puede_reasignar, self.perfil.puede_ver_todos,
            ),
        )

    def test_ticket_nativo_conserva_visibilidad_actual(self):
        ticket = Ticket.objects.create(creado_por=self.usuario, empresa=self.empresa)

        self.propuesta("SOPORTE")

        self.assertTrue(tickets_visibles_para(self.usuario).filter(pk=ticket.pk).exists())
        self.assertFalse(tickets_visibles_para(self.otro_usuario).filter(pk=ticket.pk).exists())

    def test_guardia_sin_periodo_explicito_queda_para_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        guardia = proponer_guardia_legacy(
            empresa=empresa, legacy_usuario_id="23", grupo_nombre="SOPORTE OCCIDENTE",
        )

        self.assertTrue(guardia.requiere_revision)
        self.assertIn("GUARDIA_PERIODO_INCOMPLETO", guardia.advertencias)

    def test_guardia_con_fechas_invertidas_queda_para_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        guardia = proponer_guardia_legacy(
            empresa=empresa, legacy_usuario_id="23", grupo_nombre="SOPORTE OCCIDENTE",
            fecha_inicio=date(2026, 9, 2), fecha_fin=date(2026, 9, 1),
            hora_inicio=time(9), hora_fin=time(18),
        )

        self.assertTrue(guardia.requiere_revision)
        self.assertIn("GUARDIA_PERIODO_INVALIDO", guardia.advertencias)

    def test_guardia_mismo_dia_con_horario_no_ascendente_queda_para_revision(self):
        empresa = self.propuesta("SOPORTE").empresa
        guardia = proponer_guardia_legacy(
            empresa=empresa, legacy_usuario_id="23", grupo_nombre="SOPORTE OCCIDENTE",
            fecha_inicio=date(2026, 9, 1), fecha_fin=date(2026, 9, 1),
            hora_inicio=time(18), hora_fin=time(18),
        )

        self.assertTrue(guardia.requiere_revision)
        self.assertIn("GUARDIA_HORARIO_INVALIDO", guardia.advertencias)
