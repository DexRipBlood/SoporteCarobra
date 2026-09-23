from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tickets.models import Empresa, Tienda, Zona
from usuarios.models import PerfilUsuario

from .admin import PendienteAdmin, PendienteHistorialAdmin
from .forms import PendienteForm
from .models import Pendiente, PendienteHistorial
from .services import actualizar_pendiente, crear_pendiente


User = get_user_model()


class GestorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="gestor-admin")
        PerfilUsuario.objects.create(user=cls.admin, rol=PerfilUsuario.Rol.ADMIN)
        cls.usuario = User.objects.create_user(username="gestor-usuario")
        PerfilUsuario.objects.create(user=cls.usuario)
        cls.otro = User.objects.create_user(username="gestor-otro")
        PerfilUsuario.objects.create(user=cls.otro, rol=PerfilUsuario.Rol.ADMIN)
        empresa = Empresa.objects.create(nombre="Empresa Gestor", codigo="GST")
        zona = Zona.objects.create(empresa=empresa, codigo="Z1", nombre="Centro", estado="Jalisco")
        cls.tienda = Tienda.objects.create(empresa=empresa, zona=zona, nombre="Tienda Gestor", estado="Jalisco")

    def crear(self, **datos):
        return crear_pendiente(usuario=self.admin, datos={"titulo": "Revisar enlace", **datos})

    def actualizar(self, pendiente, **datos):
        return actualizar_pendiente(pendiente_id=pendiente.pk, usuario=self.admin, datos=datos)

    def datos_formulario(self, pendiente=None, **datos):
        base = {
            "titulo": "Actividad desde formulario", "detalle": "Seguimiento",
            "area": "SISTEMAS", "tda": self.tienda.pk, "categoria": "TAREA",
            "tipo_trabajo": "GESTION", "prioridad": "MEDIA", "responsable": self.usuario.pk,
            "solicitante": "Solicitante externo", "canal": "SISTEMA", "siguiente_accion": "Revisar",
            "fecha_compromiso": timezone.localdate().isoformat(),
        }
        if pendiente:
            base.update(estado=pendiente.estado, bloqueo=pendiente.bloqueo,
                        bloqueado_por=pendiente.bloqueado_por, frecuencia=pendiente.frecuencia,
                        version=pendiente.ultima_actualizacion.isoformat(), comentario="Seguimiento")
        return {**base, **datos}

    def test_creacion_folio_defaults_e_historial(self):
        p = self.crear(responsable=self.usuario, tda=self.tienda, folio="MANUAL", estado="COMPLETADO", frecuencia="DIARIA")
        otro = self.crear()
        p.refresh_from_db()
        self.assertEqual(p.folio, f"GST-{p.pk:06d}")
        self.assertNotEqual(p.folio, otro.folio)
        self.assertEqual(p.estado, "PENDIENTE")
        self.assertEqual(p.frecuencia, "UNICA")
        self.assertEqual(p.bloqueo, "SIN_BLOQUEO")
        self.assertEqual(p.creado_por, self.admin)
        self.assertEqual(p.responsable, self.usuario)
        self.assertEqual(p.historial.get().tipo_evento, "CREACION")
        self.assertIsNone(p.fecha_cierre)

    def test_titulo_blanco_rechazado_sin_datos_parciales(self):
        with self.assertRaises(ValidationError):
            self.crear(titulo="  ")
        self.assertEqual(Pendiente.objects.count(), 0)
        self.assertEqual(PendienteHistorial.objects.count(), 0)

    def test_pendiente_a_en_curso_registra_primera_atencion_una_sola_vez(self):
        p = self.crear()
        instante = timezone.now() + timedelta(hours=1)
        with patch("gestor.services.timezone.now", return_value=instante):
            p = self.actualizar(p, estado="EN_CURSO")
        self.assertEqual(p.fecha_atencion_inicial, instante)
        self.assertEqual(len(p.recomendaciones), 3)
        p = self.actualizar(p, estado="PENDIENTE")
        p = self.actualizar(p, estado="EN_CURSO")
        self.assertEqual(p.fecha_atencion_inicial, instante)
        self.assertTrue(p.historial.filter(tipo_evento="ESTADO", valor_nuevo="En curso").exists())

    def test_en_espera_requiere_bloqueo_explicacion_y_siguiente_accion(self):
        p = self.actualizar(self.crear(), estado="EN_CURSO")
        total = p.historial.count()
        with self.assertRaises(ValidationError) as error:
            self.actualizar(p, estado="EN_ESPERA", bloqueado_por=" ", siguiente_accion=" ")
        self.assertEqual(set(error.exception.message_dict), {"bloqueo", "bloqueado_por", "siguiente_accion"})
        p.refresh_from_db()
        self.assertEqual(p.estado, "EN_CURSO")
        self.assertEqual(p.historial.count(), total)
        p = self.actualizar(p, estado="EN_ESPERA", bloqueo="BRADESCARD", bloqueado_por="Salvador Cervantes", siguiente_accion="Esperar autorización")
        self.assertEqual(p.estado, "EN_ESPERA")
        self.assertEqual(p.bloqueado_por, "Salvador Cervantes")
        self.assertTrue(p.historial.filter(tipo_evento="BLOQUEO").exists())

    def test_pendiente_directo_a_espera_registra_atencion(self):
        p = self.actualizar(self.crear(), estado="EN_ESPERA", bloqueo="PERSONA", bloqueado_por="Persona externa", siguiente_accion="Confirmar respuesta")
        self.assertIsNotNone(p.fecha_atencion_inicial)

    def test_completar_registra_cierre_y_congela_metricas(self):
        p = self.actualizar(self.crear(), estado="EN_CURSO")
        instante = p.fecha_creacion + timedelta(days=2)
        with patch("gestor.services.timezone.now", return_value=instante):
            p = self.actualizar(p, estado="COMPLETADO")
        self.assertEqual(p.fecha_cierre, instante)
        self.assertEqual(p.tiempo_resolucion, timedelta(days=2))
        self.assertEqual(p.tiempo_abierto, timedelta(days=2))
        p = self.actualizar(p, titulo="Ajuste sin reabrir")
        self.assertEqual(p.fecha_cierre, instante)
        self.assertEqual(p.historial.filter(tipo_evento="CIERRE").count(), 1)

    def test_reapertura_preserva_historial_y_atencion_inicial(self):
        p = self.actualizar(self.crear(), estado="EN_CURSO")
        atencion = p.fecha_atencion_inicial
        p = self.actualizar(p, estado="COMPLETADO")
        cierre = p.historial.get(tipo_evento="CIERRE")
        p = self.actualizar(p, estado="EN_CURSO")
        self.assertIsNone(p.fecha_cierre)
        self.assertIsNone(p.tiempo_resolucion)
        self.assertEqual(p.fecha_atencion_inicial, atencion)
        self.assertTrue(p.historial.filter(pk=cierre.pk).exists())
        self.assertTrue(p.historial.filter(tipo_evento="REAPERTURA").exists())
        p = self.actualizar(p, estado="COMPLETADO")
        self.assertEqual(p.historial.filter(tipo_evento="CIERRE").count(), 2)

    def test_vencido_atraso_y_semaforo(self):
        hoy = timezone.localdate()
        p = self.crear(fecha_compromiso=hoy - timedelta(days=3))
        self.assertTrue(p.vencido)
        self.assertEqual(p.dias_atraso, 3)
        self.assertEqual(p.semaforo, "ROJO")
        self.assertEqual(list(Pendiente.objects.vencidos()), [p])
        p.fecha_compromiso = hoy
        self.assertFalse(p.vencido)
        self.assertEqual(p.semaforo, "AMARILLO")
        p.fecha_compromiso = hoy + timedelta(days=5)
        self.assertEqual(p.semaforo, "VERDE")
        p.prioridad = "CRITICA"
        self.assertEqual(p.semaforo, "AMARILLO")
        for estado in Pendiente.ESTADOS_TERMINALES:
            p.estado = estado
            p.fecha_compromiso = hoy - timedelta(days=3)
            self.assertEqual(p.semaforo, "GRIS")
            self.assertEqual(p.dias_atraso, 0)
            self.assertFalse(p.vencido)

    def test_audita_campos_importantes_y_comentarios(self):
        p = self.crear()
        p = self.actualizar(p, responsable=self.usuario, fecha_compromiso=timezone.localdate(), prioridad="ALTA", siguiente_accion="Llamar", bloqueo="VALIDACION", bloqueado_por="Finanzas")
        self.assertTrue({"RESPONSABLE", "COMPROMISO", "PRIORIDAD", "SIGUIENTE_ACCION", "BLOQUEO"}.issubset(set(p.historial.values_list("tipo_evento", flat=True))))
        actualizar_pendiente(pendiente_id=p.pk, usuario=self.admin, datos={}, comentario="Seguimos esperando")
        self.assertTrue(p.historial.filter(tipo_evento="COMENTARIO", comentario="Seguimos esperando").exists())

    def test_edicion_obsoleta_no_sobrescribe_cambios_ni_auditoria(self):
        p = self.crear()
        version = p.ultima_actualizacion
        self.actualizar(p, titulo="Cambio de otro admin")
        total = p.historial.count()
        with self.assertRaises(ValidationError):
            actualizar_pendiente(pendiente_id=p.pk, usuario=self.admin, datos={"titulo": "Edición vieja"}, version=version)
        p.refresh_from_db()
        self.assertEqual(p.titulo, "Cambio de otro admin")
        self.assertEqual(p.historial.count(), total)

    def test_anonimo_requiere_login_y_regular_no_accede_a_ninguna_ruta(self):
        p = self.crear(responsable=self.usuario)
        urls = [reverse("gestor:lista"), reverse("gestor:crear")]
        urls += [reverse(f"gestor:{ruta}", args=[p.folio]) for ruta in ("detalle", "editar", "cancelar")]
        for url in urls:
            with self.subTest(url=url):
                self.client.logout()
                self.assertEqual(self.client.get(url).status_code, 302)
                self.client.force_login(self.usuario)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            crear_pendiente(usuario=self.usuario, datos={"titulo": "No permitido"})
        with self.assertRaises(PermissionDenied):
            actualizar_pendiente(pendiente_id=p.pk, usuario=self.usuario, datos={"estado": "COMPLETADO"})

    def test_permiso_django_aislado_no_abre_el_modulo_a_usuario_regular(self):
        self.usuario.user_permissions.add(Permission.objects.get(codename="view_pendiente"))
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("gestor:lista")).status_code, 403)

    def test_superusuario_accede_sin_perfil_y_admin_inactivo_no(self):
        superuser = User.objects.create_superuser(username="gestor-root", email="root@example.test", password="test")
        self.client.force_login(superuser)
        self.assertEqual(self.client.get(reverse("gestor:lista")).status_code, 200)
        PerfilUsuario.objects.filter(user=self.admin).update(activo=False)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("gestor:lista")).status_code, 403)

    def test_crud_http_y_validacion_espera(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse("gestor:crear"), self.datos_formulario(estado="COMPLETADO", folio="FORZADO"))
        p = Pendiente.objects.get()
        self.assertRedirects(respuesta, reverse("gestor:detalle", args=[p.folio]))
        self.assertEqual(p.estado, "PENDIENTE")
        editar = reverse("gestor:editar", args=[p.folio])
        respuesta = self.client.post(editar, self.datos_formulario(p, estado="EN_ESPERA"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("bloqueo", respuesta.context["form"].errors)
        respuesta = self.client.post(editar, self.datos_formulario(p, estado="EN_CURSO"))
        self.assertEqual(respuesta.status_code, 302)
        p.refresh_from_db()
        self.assertIsNotNone(p.fecha_atencion_inicial)
        self.assertEqual(self.client.get(editar).status_code, 200)
        respuesta = self.client.get(reverse("gestor:detalle", args=[p.folio]))
        self.assertContains(respuesta, "Historial")
        self.assertContains(respuesta, "gestor")
        self.assertContains(respuesta, "Actividad desde formulario")

    def test_cancelacion_requiere_post_y_motivo_y_conserva_historial(self):
        self.client.force_login(self.admin)
        p = self.crear()
        url = reverse("gestor:cancelar", args=[p.folio])
        self.assertEqual(self.client.get(url).status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.estado, "PENDIENTE")
        self.assertEqual(self.client.post(url, {"version": p.ultima_actualizacion.isoformat()}).status_code, 200)
        respuesta = self.client.post(url, {"version": p.ultima_actualizacion.isoformat(), "comentario": "Ya no aplica"})
        self.assertEqual(respuesta.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.estado, "CANCELADO")
        self.assertTrue(p.historial.filter(tipo_evento="CANCELACION", comentario="Ya no aplica").exists())
        self.assertTrue(p.historial.filter(tipo_evento="CREACION").exists())
        with self.assertRaises(ProtectedError):
            p.delete()

    def test_dashboard_excluye_terminales_de_kpis(self):
        hoy = timezone.localdate()
        self.crear(fecha_compromiso=hoy, prioridad="CRITICA")
        self.crear(fecha_compromiso=hoy - timedelta(days=1), responsable=self.admin)
        self.actualizar(self.crear(), estado="EN_ESPERA", bloqueo="AREA", bloqueado_por="RH", siguiente_accion="Esperar")
        for estado in Pendiente.ESTADOS_TERMINALES:
            self.actualizar(self.crear(fecha_compromiso=hoy - timedelta(days=1), prioridad="CRITICA"), estado=estado)
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("gestor:lista"))
        self.assertEqual(respuesta.context["kpis"], {"abiertos": 3, "vencidos": 1, "hoy": 1, "espera": 1, "criticos": 1, "sin_responsable": 2})

    def test_filtros_combinados_busqueda_y_fechas(self):
        p = self.crear(titulo="Autorización de retiro", responsable=self.usuario, area="FINANZAS", tda=self.tienda,
                      prioridad="ALTA", categoria="SOLICITUD", tipo_trabajo="RECURRENTE", fecha_compromiso=timezone.localdate())
        p = self.actualizar(p, frecuencia="SEMANAL", bloqueo="BRADESCARD", bloqueado_por="Salvador", estado="EN_ESPERA", siguiente_accion="Esperar autorización")
        self.crear(titulo="Otra tarea")
        self.client.force_login(self.admin)
        filtros = {"q": "Salvador", "responsable": self.usuario.pk, "area": "FINANZAS", "tda": self.tienda.pk,
                   "prioridad": "ALTA", "categoria": "SOLICITUD", "tipo_trabajo": "RECURRENTE", "frecuencia": "SEMANAL",
                   "estado": "EN_ESPERA", "bloqueo": "BRADESCARD", "fecha_desde": timezone.localdate(), "fecha_hasta": timezone.localdate()}
        respuesta = self.client.get(reverse("gestor:lista"), filtros)
        self.assertEqual(list(respuesta.context["pagina"]), [p])
        self.assertContains(respuesta, p.titulo)
        self.assertNotContains(respuesta, "Otra tarea")
        for campo, valor in (("responsable", "inválido"), ("fecha_desde", "no-es-fecha"), ("estado", "INVENTADO")):
            respuesta = self.client.get(reverse("gestor:lista"), {campo: valor})
            self.assertEqual(respuesta.status_code, 200)
            self.assertTrue(respuesta.context["form"].errors)
            self.assertEqual(respuesta.context["pagina"].paginator.count, 0)

    def test_vistas_rapidas_mis_abiertos_y_completados(self):
        propio = self.crear(responsable=self.admin, fecha_compromiso=timezone.localdate())
        ajeno = self.crear(responsable=self.otro)
        completo = self.actualizar(self.crear(responsable=self.admin), estado="COMPLETADO")
        self.client.force_login(self.admin)
        for vista, esperados in (("mis", {propio.pk}), ("hoy", {propio.pk}), ("abiertos", {propio.pk, ajeno.pk}), ("completados", {completo.pk})):
            respuesta = self.client.get(reverse("gestor:lista"), {"vista": vista})
            self.assertEqual({p.pk for p in respuesta.context["pagina"]}, esperados)

    def test_paginacion_conserva_filtros_y_limita_historial(self):
        p = self.crear()
        for numero in range(45):
            self.actualizar(p, titulo=f"Cambio {numero}")
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("gestor:detalle", args=[p.folio]))
        self.assertEqual(len(respuesta.context["historial"]), 40)
        self.assertTrue(respuesta.context["historial"].has_next())
        respuesta = self.client.get(reverse("gestor:lista"), {"q": "Cambio", "prioridad": "MEDIA", "page": "999"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("q=Cambio", respuesta.context["parametros"])
        self.assertNotIn("page=", respuesta.context["parametros"])

    def test_formulario_conserva_responsable_y_tienda_inactivos(self):
        p = self.crear(responsable=self.usuario, tda=self.tienda)
        User.objects.filter(pk=self.usuario.pk).update(is_active=False)
        Tienda.objects.filter(pk=self.tienda.pk).update(activa=False)
        self.assertTrue(PendienteForm(self.datos_formulario(p), instance=p).is_valid())
        self.assertFalse(PendienteForm(self.datos_formulario()).is_valid())

    def test_admin_django_es_solo_lectura_incluso_para_superusuario(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        for clase, modelo in ((PendienteAdmin, Pendiente), (PendienteHistorialAdmin, PendienteHistorial)):
            panel = clase(modelo, AdminSite())
            self.assertTrue(panel.has_view_permission(request))
            self.assertFalse(panel.has_add_permission(request))
            self.assertFalse(panel.has_change_permission(request))
            self.assertFalse(panel.has_delete_permission(request))

    def test_csrf_requerido_para_escrituras(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(reverse("gestor:crear"), self.datos_formulario()).status_code, 403)

    def test_contenido_del_usuario_se_escapa_en_detalle_e_historial(self):
        p = self.crear(titulo="<script>alert(1)</script>", detalle="<img src=x onerror=alert(1)>")
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("gestor:detalle", args=[p.folio]))
        self.assertContains(respuesta, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(respuesta, "<script>alert(1)</script>")

    def test_listado_paginado_no_agrega_consultas_por_cada_responsable_o_tienda(self):
        self.crear(responsable=self.usuario, tda=self.tienda)
        self.client.force_login(self.admin)
        url = reverse("gestor:lista")
        # Calienta templates y permisos antes de comparar el crecimiento de consultas.
        self.client.get(url)
        with CaptureQueriesContext(connection) as consultas_uno:
            self.client.get(url)
        for numero in range(26):
            self.crear(titulo=f"Tarea adicional {numero}", responsable=self.usuario, tda=self.tienda)
        with CaptureQueriesContext(connection) as consultas_muchos:
            respuesta = self.client.get(url)
        self.assertEqual(len(respuesta.context["pagina"]), 25)
        self.assertEqual(respuesta.context["pagina"].paginator.count, 27)
        self.assertLessEqual(len(consultas_muchos), len(consultas_uno) + 1)
