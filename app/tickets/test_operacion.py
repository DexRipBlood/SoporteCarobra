from datetime import datetime, timedelta, time
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from usuarios.models import PerfilUsuario
from .models import AsignacionPersonal, Empresa, Persona, Zona, Tienda, Ticket, ConfiguracionSLA, EstadoTicket, ProgramacionTrabajo, GrupoTrabajo, MembresiaGrupo, SegmentoSLA
from .forms import ZonaForm, ProgramacionTrabajoForm
from .permisos import tickets_visibles_para
from .services.operacion import equipo_tienda, seguimiento_actual, iniciar_sla, resumen_sla, sincronizar_sla, cambiar_seguimiento, requieren_administracion
from .services.operacion import con_sla_actual
from .services.importacion_bradescard import importar_bradescard
from .services.importador_excel import COLUMNAS_ESPERADAS, analizar_importacion_bradescard
from .services.legacy import traducir_estado_legacy
from .views import _filas_reporte_incidencias


class OperacionConectadaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.admin = U.objects.create_user(username="admin-operacion")
        cls.juan = U.objects.create_user(username="juan")
        cls.luis = U.objects.create_user(username="luis")
        cls.suplente = U.objects.create_user(username="suplente")
        for user in (cls.admin, cls.juan, cls.luis, cls.suplente):
            PerfilUsuario.objects.create(user=user, rol="ADMIN" if user == cls.admin else "USUARIO")
        cls.empresa = Empresa.objects.create(codigo="INTERNO", nombre="Bradescard")
        cls.zona = Zona.objects.create(empresa=cls.empresa, codigo="INTERNO-D1", nombre="D1", estado="Jalisco",
                                      distrital_nombre="Roberto Suárez", responsable=cls.juan, partner=cls.luis)
        cls.tienda = Tienda.objects.create(empresa=cls.empresa, zona=cls.zona, numero="B150", nombre="Bodega B150", cadena="BODEGA")
        cls.regla = ConfiguracionSLA.objects.create(categoria="Internet", incidencia_general="Sin enlace", limite_minutos=240, prioridad="ALTA")

    def ticket(self):
        t = Ticket.objects.create(empresa=self.empresa, tienda_registrada=self.tienda, tienda="B150", categoria="Internet", incidencia_general="Sin enlace", responsable=self.juan, partner=self.luis, configuracion_sla=self.regla, sla_limite_minutos=240)
        iniciar_sla(t)
        return t

    def turno(self, usuario, modalidad="OFICINA", grupo=None):
        return ProgramacionTrabajo.objects.create(usuario=usuario, grupo=grupo, fecha_inicio=timezone.localdate(), fecha_fin=timezone.localdate(), hora_inicio=time(0), hora_fin=time(23,59), modalidad=modalidad)

    def excel(self, carpeta, tickets=None):
        libro = Workbook()
        hoja = libro.active
        hoja.append(list(COLUMNAS_ESPERADAS.values()))
        tickets = tickets or (("1001", "Internet", "Nuevo"), ("1002", "Equipo", "Nuevo"))
        for numero, categoria, estatus in tickets:
            datos = {"ticket_bradescard": numero, "tienda": "B150", "categoria": categoria, "incidencia_general": "Sin enlace", "estatus": estatus}
            hoja.append([datos.get(columna, "") for columna in COLUMNAS_ESPERADAS])
        ruta = Path(carpeta) / "importacion.xlsx"
        libro.save(ruta)
        return ruta

    def test_distrital_no_es_usuario_y_equipo_se_hereda(self):
        self.assertEqual(equipo_tienda(self.tienda), (self.juan, self.luis))
        self.assertFalse(get_user_model().objects.filter(username="Roberto Suárez").exists())
        form = ZonaForm({"empresa": self.empresa.pk, "nombre": "D2", "estado": "Jalisco", "distrital_nombre": "Nuevo contacto", "responsable": self.juan.pk, "partner": self.juan.pk, "activa": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("partner", form.errors)

    def test_home_office_del_partner_cubre_descanso_del_encargado(self):
        t = self.ticket()
        self.turno(self.juan, "DESCANSO")
        self.turno(self.luis, "HOME_OFFICE")
        self.assertEqual(seguimiento_actual(t)["atiende"], self.luis)
        self.assertFalse(requieren_administracion(Ticket.objects.all()).filter(pk=t.pk).exists())

    def test_ambos_descansan_o_no_tienen_horario_requiere_admin(self):
        t = self.ticket()
        self.assertTrue(seguimiento_actual(t)["requiere_admin"])
        self.turno(self.juan, "DESCANSO")
        self.turno(self.luis, "DESCANSO")
        self.assertTrue(requieren_administracion(Ticket.objects.all()).filter(pk=t.pk).exists())

    def test_grupo_inventario_no_cuenta_como_atencion_de_tickets(self):
        g = GrupoTrabajo.objects.create(empresa=self.empresa, nombre="Inventario", atiende_tickets=False)
        MembresiaGrupo.objects.create(grupo=g, usuario=self.juan)
        self.turno(self.juan, grupo=g)
        t = self.ticket()
        self.assertIsNone(seguimiento_actual(t)["atiende"])
        self.assertTrue(requieren_administracion(Ticket.objects.all()).filter(pk=t.pk).exists())

    def test_grupo_de_tickets_filtra_categorias(self):
        g = GrupoTrabajo.objects.create(empresa=self.empresa, nombre="Internet", atiende_tickets=True)
        g.incidencias.add(self.regla)
        MembresiaGrupo.objects.create(grupo=g, usuario=self.juan)
        self.turno(self.juan, grupo=g)
        t = self.ticket()
        self.assertEqual(seguimiento_actual(t)["atiende"], self.juan)
        self.assertFalse(requieren_administracion(Ticket.objects.all()).filter(pk=t.pk).exists())
        t.categoria = "Equipo"
        t.save()
        self.assertTrue(seguimiento_actual(t)["requiere_admin"])
        self.assertTrue(requieren_administracion(Ticket.objects.all()).filter(pk=t.pk).exists())

    def test_suplencia_solo_admin_y_acceso_expira(self):
        t = self.ticket()
        url = reverse("tickets:suplencia", args=[t.folio])
        datos = {"usuario": self.suplente.pk, "hasta": (timezone.localtime()+timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"), "motivo": "Descanso del equipo"}
        self.client.force_login(self.juan)
        self.assertEqual(self.client.post(url, datos).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        t.refresh_from_db()
        self.assertEqual(t.responsable, self.juan)
        self.assertEqual(t.partner, self.luis)
        self.assertEqual(seguimiento_actual(t)["atiende"], self.suplente)
        self.assertTrue(tickets_visibles_para(self.suplente).filter(pk=t.pk).exists())
        self.assertTrue(t.historial.filter(evento="SUPLENCIA").exists())
        Ticket.objects.filter(pk=t.pk).update(suplente_hasta=timezone.now()-timedelta(seconds=1))
        self.assertFalse(tickets_visibles_para(self.suplente).filter(pk=t.pk).exists())

    def test_sla_atencion_pausa_reanudacion_y_resuelto_sigue_contando(self):
        t = self.ticket()
        inicio = t.creado_at
        with patch("tickets.services.operacion.timezone.now", return_value=inicio+timedelta(minutes=15)):
            cambiar_seguimiento(t.pk, self.luis, {"estado": "EN_PROCESO", "siguiente_accion": "Diagnóstico"})
        with patch("tickets.services.operacion.timezone.now", return_value=inicio+timedelta(hours=1)):
            cambiar_seguimiento(t.pk, self.luis, {"estado": "EN_ESPERA", "siguiente_accion": "Esperar autorización", "motivo_espera": "Falla proveedor", "esperando_a": "Proveedor"})
        t.refresh_from_db()
        self.assertEqual(resumen_sla(t, inicio+timedelta(hours=3))["efectivo"], 3600)
        with patch("tickets.services.operacion.timezone.now", return_value=inicio+timedelta(hours=3)):
            cambiar_seguimiento(t.pk, self.luis, {"estado": "RESUELTO", "siguiente_accion": "Validar con tienda"})
        t.refresh_from_db()
        resumen = resumen_sla(t, inicio+timedelta(hours=3, minutes=45))
        self.assertEqual(resumen["efectivo"], 6300)
        self.assertEqual(resumen["pausa"], 7200)
        self.assertEqual(resumen["primera_atencion"], 900)
        self.assertEqual(t.segmentos_sla.filter(fin__isnull=True).count(), 1)

    def test_ticket_normal_con_saldo_legacy_cero_conserva_calculo_actual(self):
        ticket = self.ticket()
        inicio = ticket.creado_at
        momento = inicio + timedelta(minutes=30)

        resumen = resumen_sla(ticket, momento)
        sincronizar_sla(ticket, self.juan, momento)
        ticket.refresh_from_db()

        self.assertEqual(ticket.sla_legacy_segundos, 0)
        self.assertEqual(resumen["efectivo"], 1800)
        self.assertEqual(ticket.sla_segundos_acumulados, 1800)

    def test_sla_legacy_y_segmentos_se_suman_sin_mezclarse(self):
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            responsable=self.juan,
            sla_limite_minutos=240,
            sla_legacy_segundos=60 * 60,
        )
        inicio = ticket.creado_at
        SegmentoSLA.objects.create(
            ticket=ticket,
            responsable=self.juan,
            inicio=inicio,
            fin=inicio + timedelta(minutes=30),
            cuenta_sla=True,
        )

        resumen = resumen_sla(ticket, inicio + timedelta(minutes=30))

        self.assertEqual(resumen["efectivo"], 90 * 60)
        self.assertEqual(ticket.segmentos_sla.count(), 1)

    def test_tiempo_restante_descuenta_saldo_legacy(self):
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            responsable=self.juan,
            sla_limite_minutos=240,
            sla_legacy_segundos=165 * 60,
        )
        inicio = ticket.creado_at
        SegmentoSLA.objects.create(
            ticket=ticket,
            responsable=self.juan,
            inicio=inicio,
            fin=inicio + timedelta(minutes=10),
            cuenta_sla=True,
        )

        resumen = resumen_sla(ticket, inicio + timedelta(minutes=10))

        self.assertEqual(resumen["efectivo"], 175 * 60)
        self.assertEqual(resumen["restante"], 65 * 60)

    def test_sla_excedido_considera_saldo_legacy(self):
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            responsable=self.juan,
            sla_limite_minutos=60,
            sla_legacy_segundos=(60 * 60) + 1,
        )

        sincronizar_sla(ticket, self.juan, ticket.creado_at)
        ticket.refresh_from_db()

        self.assertTrue(resumen_sla(ticket, ticket.creado_at)["excedido"])
        self.assertTrue(ticket.sla_excedido)
        self.assertEqual(ticket.sla_segundos_acumulados, (60 * 60) + 1)

    def test_pausa_nueva_no_agrega_tiempo_efectivo_al_saldo_legacy(self):
        ticket = self.ticket()
        ticket.sla_legacy_segundos = 60 * 60
        ticket.save(update_fields=["sla_legacy_segundos"])
        inicio = ticket.creado_at

        with patch("tickets.services.operacion.timezone.now", return_value=inicio + timedelta(minutes=10)):
            cambiar_seguimiento(ticket.pk, self.juan, {
                "estado": EstadoTicket.EN_ESPERA,
                "motivo_espera": "Pendiente del proveedor",
                "esperando_a": "Proveedor",
                "siguiente_accion": "Esperar autorización",
            })
        ticket.refresh_from_db()
        resumen = resumen_sla(ticket, inicio + timedelta(minutes=40))

        self.assertEqual(resumen["efectivo"], 70 * 60)
        self.assertEqual(resumen["pausa"], 30 * 60)

    def test_reapertura_continua_desde_saldo_legacy_sin_reiniciarlo(self):
        ticket = self.ticket()
        ticket.sla_legacy_segundos = 60 * 60
        inicio = ticket.creado_at
        cierre = inicio + timedelta(minutes=10)
        ticket.estado_interno = EstadoTicket.CERRADO
        ticket.cerrado_at = cierre
        ticket.save(update_fields=["sla_legacy_segundos", "estado_interno", "cerrado_at"])
        sincronizar_sla(ticket, self.juan, cierre)

        ticket.estado_interno = EstadoTicket.EN_PROCESO
        ticket.cerrado_at = None
        ticket.save(update_fields=["estado_interno", "cerrado_at"])
        sincronizar_sla(ticket, self.juan, cierre)
        sincronizar_sla(ticket, self.juan, cierre + timedelta(minutes=20))
        ticket.refresh_from_db()

        self.assertEqual(ticket.sla_legacy_segundos, 60 * 60)
        self.assertEqual(resumen_sla(ticket, cierre + timedelta(minutes=20))["efectivo"], 90 * 60)
        self.assertEqual(ticket.sla_segundos_acumulados, 90 * 60)

    def test_con_sla_actual_considera_saldo_legacy(self):
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            sla_limite_minutos=60,
            sla_legacy_segundos=(60 * 60) + 1,
        )

        actual = con_sla_actual(Ticket.objects.filter(pk=ticket.pk)).get()

        self.assertEqual(actual.duracion_sla_actual, timedelta(seconds=(60 * 60) + 1))
        self.assertTrue(actual.sla_vencido_actual)

    def test_reporteria_considera_saldo_legacy_en_tiempo_y_vencimiento(self):
        dia = timezone.localdate()
        tz = timezone.get_current_timezone()
        inicio = timezone.make_aware(datetime.combine(dia, time(12, 0)), tz)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            responsable=self.juan,
            sla_limite_minutos=60,
            sla_legacy_segundos=60 * 60,
        )
        # auto_now_add usa la hora real; se fija mediodía local para que el
        # segmento 12:00–12:30 siempre pertenezca al día del reporte.
        Ticket.objects.filter(pk=ticket.pk).update(
            creado_at=inicio,
            legacy_cutover_at=inicio,
        )
        ticket.refresh_from_db()
        SegmentoSLA.objects.create(
            ticket=ticket,
            responsable=self.juan,
            inicio=inicio,
            fin=inicio + timedelta(minutes=30),
            cuenta_sla=True,
        )

        filas = _filas_reporte_incidencias({
            "fecha_inicio": dia,
            "fecha_fin": dia,
        })
        fila = next(fila for fila in filas if fila["ticket"].pk == ticket.pk)

        self.assertEqual(fila["efectivo"], 90 * 60)
        self.assertTrue(fila["excedido"])

    def test_ticket_normal_inicia_sla_desde_creado_at(self):
        ticket = Ticket.objects.create(empresa=self.empresa, responsable=self.juan)

        iniciar_sla(ticket)
        segmento = ticket.segmentos_sla.get()

        self.assertIsNone(ticket.legacy_cutover_at)
        self.assertEqual(segmento.inicio, ticket.creado_at)
        self.assertTrue(segmento.cuenta_sla)

    def test_ticket_legacy_inicia_sla_desde_el_corte(self):
        corte = timezone.now().replace(microsecond=0)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            responsable=self.juan,
            estado_interno=EstadoTicket.EN_PROCESO,
            legacy_cutover_at=corte,
            sla_legacy_segundos=60 * 60,
        )
        creado_original = corte - timedelta(days=10)
        Ticket.objects.filter(pk=ticket.pk).update(creado_at=creado_original)
        ticket.refresh_from_db()

        iniciar_sla(ticket)
        segmento = ticket.segmentos_sla.get()

        self.assertEqual(segmento.inicio, corte)
        self.assertNotEqual(segmento.inicio, ticket.creado_at)

    def test_fecha_original_legacy_anterior_al_corte_no_duplica_sla(self):
        corte = timezone.now().replace(microsecond=0)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            estado_interno=EstadoTicket.EN_PROCESO,
            legacy_cutover_at=corte,
            sla_legacy_segundos=60 * 60,
        )
        Ticket.objects.filter(pk=ticket.pk).update(creado_at=corte - timedelta(days=30))
        ticket.refresh_from_db()

        iniciar_sla(ticket)
        resumen = resumen_sla(ticket, corte + timedelta(minutes=30))

        self.assertEqual(resumen["efectivo"], 90 * 60)
        self.assertEqual(resumen["pausa"], 0)

    def test_inicializacion_legacy_abre_el_tipo_de_segmento_por_estado(self):
        corte = timezone.now().replace(microsecond=0)
        casos = {
            EstadoTicket.NUEVO: (SegmentoSLA.Tipo.ATENCION, True),
            EstadoTicket.ASIGNADO: (SegmentoSLA.Tipo.ATENCION, True),
            EstadoTicket.EN_PROCESO: (SegmentoSLA.Tipo.ATENCION, True),
            EstadoTicket.EN_ESPERA: (SegmentoSLA.Tipo.PAUSA, False),
        }
        for estado, (tipo, cuenta_sla) in casos.items():
            with self.subTest(estado=estado):
                ticket = Ticket.objects.create(
                    empresa=self.empresa,
                    estado_interno=estado,
                    legacy_cutover_at=corte,
                )

                iniciar_sla(ticket)
                segmento = ticket.segmentos_sla.get()

                self.assertEqual(segmento.inicio, corte)
                self.assertEqual(segmento.tipo, tipo)
                self.assertEqual(segmento.cuenta_sla, cuenta_sla)

    def test_espera_legacy_sin_detalles_interactivos_permanece_pausada(self):
        corte = timezone.now().replace(microsecond=0)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            estado_interno=EstadoTicket.EN_ESPERA,
            legacy_cutover_at=corte,
        )

        sincronizar_sla(ticket, ahora=corte + timedelta(minutes=10))
        segmento = ticket.segmentos_sla.get()

        self.assertFalse(segmento.cuenta_sla)
        self.assertIsNone(segmento.fin)
        self.assertEqual(resumen_sla(ticket, corte + timedelta(minutes=10))["efectivo"], 0)

    def test_resuelto_y_cerrado_legacy_no_dejan_segmento_abierto(self):
        corte = timezone.now().replace(microsecond=0)
        for estado in (EstadoTicket.RESUELTO, EstadoTicket.CERRADO):
            with self.subTest(estado=estado):
                ticket = Ticket.objects.create(
                    empresa=self.empresa,
                    estado_interno=estado,
                    legacy_cutover_at=corte,
                    sla_legacy_segundos=60 * 60,
                )

                iniciar_sla(ticket)
                sincronizar_sla(ticket, ahora=corte + timedelta(minutes=10))

                self.assertFalse(ticket.segmentos_sla.filter(fin__isnull=True).exists())
                self.assertEqual(resumen_sla(ticket, corte + timedelta(minutes=10))["efectivo"], 60 * 60)

    def test_reapertura_legacy_previa_al_corte_inicia_segmento_en_corte(self):
        corte = timezone.now().replace(microsecond=0)
        reapertura_legacy = corte - timedelta(hours=2)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            estado_interno=EstadoTicket.EN_PROCESO,
            legacy_cutover_at=corte,
            ultima_reapertura_at=reapertura_legacy,
        )

        iniciar_sla(ticket)
        segmento = ticket.segmentos_sla.get()

        self.assertEqual(segmento.inicio, corte)
        self.assertGreater(segmento.inicio, ticket.ultima_reapertura_at)

    def test_reapertura_legacy_previa_al_corte_no_duplica_intervalo(self):
        corte = timezone.now().replace(microsecond=0)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            estado_interno=EstadoTicket.EN_PROCESO,
            legacy_cutover_at=corte,
            ultima_reapertura_at=corte - timedelta(hours=2),
            sla_legacy_segundos=60 * 60,
        )
        Ticket.objects.filter(pk=ticket.pk).update(creado_at=corte - timedelta(days=5))
        ticket.refresh_from_db()

        iniciar_sla(ticket)
        resumen = resumen_sla(ticket, corte + timedelta(minutes=30))

        self.assertEqual(resumen["efectivo"], 90 * 60)

    def test_reapertura_legacy_posterior_al_corte_inicia_en_fecha_real(self):
        corte = timezone.now().replace(microsecond=0)
        reapertura = corte + timedelta(hours=2)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            estado_interno=EstadoTicket.CERRADO,
            cerrado_at=corte,
            legacy_cutover_at=corte,
            sla_legacy_segundos=60 * 60,
        )
        iniciar_sla(ticket)
        ticket.estado_interno = EstadoTicket.EN_PROCESO
        ticket.cerrado_at = None
        ticket.ultima_reapertura_at = reapertura
        ticket.save(update_fields=["estado_interno", "cerrado_at", "ultima_reapertura_at"])

        sincronizar_sla(ticket, ahora=reapertura)
        sincronizar_sla(ticket, ahora=reapertura + timedelta(minutes=10))
        ticket.refresh_from_db()
        segmento = ticket.segmentos_sla.get()

        self.assertEqual(ticket.sla_legacy_segundos, 60 * 60)
        self.assertEqual(segmento.inicio, reapertura)
        self.assertEqual(ticket.sla_segundos_acumulados, 70 * 60)

    def test_reapertura_ticket_nativo_conserva_inicio_actual(self):
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            estado_interno=EstadoTicket.CERRADO,
            cerrado_at=timezone.now().replace(microsecond=0),
        )
        iniciar_sla(ticket)
        reapertura = ticket.cerrado_at + timedelta(hours=1)
        ticket.estado_interno = EstadoTicket.EN_PROCESO
        ticket.cerrado_at = None
        ticket.ultima_reapertura_at = reapertura
        ticket.save(update_fields=["estado_interno", "cerrado_at", "ultima_reapertura_at"])

        sincronizar_sla(ticket, ahora=reapertura)
        segmento = ticket.segmentos_sla.filter(fin__isnull=True).get()

        self.assertIsNone(ticket.legacy_cutover_at)
        self.assertEqual(segmento.inicio, reapertura)

    def test_traduccion_de_todos_los_estados_legacy_conocidos(self):
        casos = {
            "Nuevo": EstadoTicket.NUEVO,
            "Asignado": EstadoTicket.ASIGNADO,
            "En curso": EstadoTicket.EN_PROCESO,
            "En curso (asignada)": EstadoTicket.EN_PROCESO,
            "En seguimiento": EstadoTicket.EN_PROCESO,
            "En espera": EstadoTicket.EN_ESPERA,
            "En observación": EstadoTicket.RESUELTO,
            "Resuelto": EstadoTicket.RESUELTO,
            "Cerrado": EstadoTicket.CERRADO,
        }
        for estado_legacy, esperado in casos.items():
            with self.subTest(estado_legacy=estado_legacy):
                resultado = traducir_estado_legacy(estado_legacy)
                self.assertEqual(resultado.estado, esperado)
                self.assertFalse(resultado.requiere_revision)

    def test_abierto_y_pendiente_legacy_usan_contexto(self):
        for estado_legacy in ("Abierto", "Pendiente"):
            with self.subTest(estado_legacy=estado_legacy, caso="sin contexto"):
                self.assertEqual(traducir_estado_legacy(estado_legacy).estado, EstadoTicket.NUEVO)
            with self.subTest(estado_legacy=estado_legacy, caso="responsable"):
                self.assertEqual(
                    traducir_estado_legacy(estado_legacy, tiene_responsable=True).estado,
                    EstadoTicket.ASIGNADO,
                )
            with self.subTest(estado_legacy=estado_legacy, caso="actividad"):
                self.assertEqual(
                    traducir_estado_legacy(estado_legacy, tiene_actividad=True).estado,
                    EstadoTicket.EN_PROCESO,
                )

    def test_estado_legacy_desconocido_requiere_revision(self):
        resultado = traducir_estado_legacy("Estado en tránsito")

        self.assertIsNone(resultado.estado)
        self.assertTrue(resultado.requiere_revision)
        self.assertIn("Estado en tránsito", resultado.advertencia)

    def test_traduccion_legacy_tolera_acentos_mayusculas_y_espacios(self):
        resultado = traducir_estado_legacy("  EN   OBSERVACIÓN  ")

        self.assertEqual(resultado.estado, EstadoTicket.RESUELTO)
        self.assertFalse(resultado.requiere_revision)

    def test_reporteria_legacy_solo_agrega_saldo_en_periodo_del_corte(self):
        dia = timezone.localdate()
        tz = timezone.get_current_timezone()
        corte = timezone.make_aware(datetime.combine(dia, time(12, 0)), tz)
        ticket = Ticket.objects.create(
            empresa=self.empresa,
            legacy_cutover_at=corte,
            sla_legacy_segundos=60 * 60,
        )
        # El día del corte se deriva de la fecha local, no de corte.date()
        # (que sería UTC y falla si la prueba corre cerca de medianoche).
        Ticket.objects.filter(pk=ticket.pk).update(creado_at=corte)
        ticket.refresh_from_db()

        filas_corte = _filas_reporte_incidencias({
            "fecha_inicio": dia,
            "fecha_fin": dia,
        })
        filas_posteriores = _filas_reporte_incidencias({
            "fecha_inicio": dia + timedelta(days=1),
            "fecha_fin": dia + timedelta(days=1),
        })
        fila_corte = next(fila for fila in filas_corte if fila["ticket"].pk == ticket.pk)
        fila_posterior = next(fila for fila in filas_posteriores if fila["ticket"].pk == ticket.pk)

        self.assertEqual(fila_corte["efectivo"], 60 * 60)
        self.assertEqual(fila_posterior["efectivo"], 0)

    def test_tickets_existentes_sin_datos_legacy_siguen_permitidos(self):
        primer_ticket = Ticket.objects.create(empresa=self.empresa)
        segundo_ticket = Ticket.objects.create(empresa=self.empresa)

        self.assertIsNone(primer_ticket.legacy_source)
        self.assertIsNone(primer_ticket.legacy_id)
        self.assertEqual(primer_ticket.sla_legacy_segundos, 0)
        self.assertEqual(resumen_sla(primer_ticket, primer_ticket.creado_at)["efectivo"], 0)
        self.assertEqual(Ticket.objects.filter(pk__in=[primer_ticket.pk, segundo_ticket.pk]).count(), 2)

    def test_identidad_legacy_es_unica_y_saldo_no_puede_ser_negativo(self):
        Ticket.objects.create(
            empresa=self.empresa,
            legacy_source="php_mysql",
            legacy_id="42",
        )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Ticket.objects.create(
                    empresa=self.empresa,
                    legacy_source="php_mysql",
                    legacy_id="42",
                )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Ticket.objects.create(
                    empresa=self.empresa,
                    sla_legacy_segundos=-1,
                )

    def test_espera_incompleta_no_pausa_ni_cambia_estado(self):
        t = self.ticket()
        with self.assertRaises(ValidationError):
            cambiar_seguimiento(t.pk, self.juan, {"estado": "EN_ESPERA"})
        t.refresh_from_db()
        self.assertEqual(t.estado_interno, "NUEVO")
        self.assertFalse(t.segmentos_sla.filter(cuenta_sla=False).exists())

    def test_historial_sla_excedido_guarda_tiempo_excedido(self):
        t = self.ticket()
        t.sla_limite_minutos = 60
        t.save(update_fields=["sla_limite_minutos"])
        momento = t.creado_at + timedelta(minutes=90)

        sincronizar_sla(t, self.juan, momento)

        evento_sla = t.historial.get(evento="SLA_EXCEDIDO")
        self.assertEqual(evento_sla.valor_nuevo["tiempo_excedido"], 1800)
        self.assertEqual(resumen_sla(t, momento)["excedido_por"], 1800)

    def test_escalar_no_pausa_sla(self):
        t = self.ticket()
        self.client.force_login(self.luis)
        self.client.post(reverse("tickets:escalar", args=[t.folio]), {"motivo": "No podemos resolver"})
        t.refresh_from_db()
        self.assertTrue(t.solicitud_admin)
        self.assertFalse(resumen_sla(t)["pausado"])
        self.assertTrue(t.historial.filter(evento="ESCALADO").exists())

    def test_solo_consultar_todos_no_permite_editar_ajenos(self):
        t = self.ticket()
        PerfilUsuario.objects.filter(user=self.suplente).update(puede_ver_todos=True)
        self.client.force_login(self.suplente)
        self.assertEqual(self.client.get(reverse("tickets:detalle", args=[t.folio])).status_code, 200)
        self.assertEqual(self.client.post(reverse("tickets:seguimiento", args=[t.folio]), {"estado": "EN_PROCESO"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("tickets:detalle", args=[t.folio]), {"accion": "comentario", "tipo": "PUBLICO", "comentario": "No debe guardar"}).status_code, 403)

    def test_filtro_importacion_empresa_asignacion_y_reimportacion(self):
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            ruta = self.excel(carpeta)
            preview = analizar_importacion_bradescard(ruta, empresa=self.empresa, categorias=["Internet"])
            self.assertEqual(preview["total"], 1)
            self.assertEqual(preview["omitidos"], 1)
            resultado = importar_bradescard(ruta, usuario=self.admin, empresa=self.empresa, categorias=["Internet"])
            self.assertTrue(resultado["ok"], resultado)
            t = Ticket.objects.get(ticket_bradescard="1001")
            self.assertEqual(t.tienda_registrada, self.tienda)
            self.assertEqual((t.responsable, t.partner), (self.juan, self.luis))
            self.assertEqual(t.sla_limite_minutos, 240)
            self.assertTrue(t.solicitud_admin)
            self.assertEqual(t.segmentos_sla.count(), 1)
            t.responsable = self.suplente
            t.save()
            resultado = importar_bradescard(ruta, usuario=self.admin, empresa=self.empresa, categorias=["Internet", "Equipo"])
            self.assertTrue(resultado["ok"], resultado)
            t.refresh_from_db()
            self.assertEqual(t.responsable, self.suplente)
            self.assertEqual(Ticket.objects.count(), 2)
            otra = Empresa.objects.create(codigo="OTRA", nombre="Otra empresa")
            resultado = importar_bradescard(ruta, usuario=self.admin, empresa=otra, categorias=["Internet"])
            self.assertTrue(resultado["ok"], resultado)
            ajeno = Ticket.objects.get(empresa=otra)
            self.assertIsNone(ajeno.tienda_registrada)
            self.assertIsNone(ajeno.responsable)

    def test_importacion_conserva_estatus_cerrado_del_excel(self):
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            ruta = self.excel(
                carpeta,
                tickets=(
                    ("2001", "Internet", "Cerrado"),
                    ("2002", "Internet", "Cerrado"),
                ),
            )

            resultado = importar_bradescard(
                ruta,
                usuario=self.admin,
                empresa=self.empresa,
                categorias=["Internet"],
            )

            self.assertTrue(resultado["ok"], resultado)
            tickets = Ticket.objects.filter(
                ticket_bradescard__in=("2001", "2002"),
            ).order_by("ticket_bradescard")
            self.assertEqual(tickets.count(), 2)
            self.assertTrue(
                all(ticket.estado_interno == "CERRADO" for ticket in tickets)
            )
            self.assertTrue(all(ticket.cerrado_at for ticket in tickets))
            self.assertFalse(
                SegmentoSLA.objects.filter(
                    ticket__in=tickets,
                    fin__isnull=True,
                ).exists()
            )

    def test_importacion_reabre_ticket_cerrado_si_bradescard_lo_reporta_abierto(self):
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            ruta = self.excel(
                carpeta,
                tickets=(("3001", "Internet", "Cerrado"),),
            )
            self.assertTrue(
                importar_bradescard(
                    ruta,
                    usuario=self.admin,
                    empresa=self.empresa,
                    categorias=["Internet"],
                )["ok"]
            )

            from openpyxl import load_workbook

            libro = load_workbook(ruta)
            columna_estatus = list(COLUMNAS_ESPERADAS).index("estatus") + 1
            libro.active.cell(2, columna_estatus, "En curso (asignada)")
            libro.save(ruta)

            resultado = importar_bradescard(
                ruta,
                usuario=self.admin,
                empresa=self.empresa,
                categorias=["Internet"],
            )
            ticket = Ticket.objects.get(ticket_bradescard="3001")

            self.assertTrue(resultado["ok"], resultado)
            self.assertEqual(ticket.estado_interno, "EN_PROCESO")
            self.assertIsNone(ticket.cerrado_at)
            self.assertEqual(ticket.numero_reaperturas, 1)
            self.assertTrue(ticket.segmentos_sla.filter(fin__isnull=True).exists())
            self.assertTrue(
                ticket.historial.filter(
                    evento="REABIERTO",
                    descripcion__contains="Bradescard reporta",
                ).exists()
            )
            self.assertTrue(ticket.comentarios.filter(tipo="SISTEMA", comentario__contains="reabrió automáticamente").exists())

    def test_mismo_excel_reabre_ticket_cerrado_si_bradescard_sigue_en_espera(self):
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            ruta = self.excel(
                carpeta,
                tickets=(("3002", "Internet", "En espera"),),
            )
            self.assertTrue(
                importar_bradescard(
                    ruta,
                    usuario=self.admin,
                    empresa=self.empresa,
                    categorias=["Internet"],
                )["ok"]
            )
            ticket = Ticket.objects.get(ticket_bradescard="3002")
            ticket.estado_interno = "CERRADO"
            ticket.cerrado_at = timezone.now()
            ticket.save(update_fields=["estado_interno", "cerrado_at"])
            ticket.segmentos_sla.filter(fin__isnull=True).update(fin=ticket.cerrado_at)

            resultado = importar_bradescard(
                ruta,
                usuario=self.admin,
                empresa=self.empresa,
                categorias=["Internet"],
            )
            ticket.refresh_from_db()

            self.assertTrue(resultado["ok"], resultado)
            self.assertEqual(ticket.estado_interno, "EN_ESPERA")
            self.assertEqual(ticket.numero_reaperturas, 1)
            self.assertTrue(
                ticket.historial.filter(
                    evento="REABIERTO",
                    descripcion__contains="Bradescard reporta",
                ).exists()
            )

    def test_calendario_rechaza_solapamiento_y_miembro_ajeno(self):
        self.turno(self.juan)
        datos = {"usuario": self.juan.pk, "fecha_inicio": timezone.localdate(), "fecha_fin": timezone.localdate(), "hora_inicio": "09:00", "hora_fin": "18:00", "modalidad": "HOME_OFFICE"}
        self.assertFalse(ProgramacionTrabajoForm(datos).is_valid())
        g = GrupoTrabajo.objects.create(empresa=self.empresa, nombre="Sin miembros")
        datos.update(usuario=self.luis.pk, grupo=g.pk)
        form = ProgramacionTrabajoForm(datos)
        self.assertFalse(form.is_valid())
        self.assertIn("usuario", form.errors)

    def test_paneles_con_datos_y_personal_de_tienda_pendiente(self):
        self.turno(self.juan)
        t = self.ticket()
        self.client.force_login(self.admin)
        for ruta in ("territorio", "calendario", "incidencias", "permisos"):
            self.assertEqual(self.client.get(reverse("tickets:"+ruta)).status_code, 200)
        for tipo in ("empresa", "distrito", "tienda", "grupo", "miembro", "incidencia"):
            self.assertEqual(self.client.get(reverse("tickets:catalogo_nuevo", args=[tipo])).status_code, 200)
        respuesta = self.client.get(reverse("tickets:detalle", args=[t.folio]))
        self.assertContains(respuesta, "Directorio de Activos pendiente de integrar")
        self.assertContains(respuesta, "Roberto Suárez")
        respuesta = self.client.get(reverse("tickets:territorio"), {"empresa": self.empresa.pk, "distrito": self.zona.pk})
        self.assertContains(respuesta, "Bodega B150")
        self.assertContains(respuesta, "Mapa completo y filtros")
        self.assertNotContains(respuesta, "INTERNO-D1")
        self.client.force_login(self.juan)
        self.assertEqual(self.client.get(reverse("tickets:calendario")).status_code, 403)

    def test_socio_define_tipo_visible_aunque_cadena_historica_este_incorrecta(self):
        self.tienda.socio = "Promoda"
        self.tienda.ciudad = "Guadalajara"
        self.tienda.cadena = Tienda.Cadena.OTRA
        self.tienda.save(update_fields=["socio", "ciudad", "cadena"])
        self.assertEqual(self.tienda.tipo_tienda_codigo, Tienda.Cadena.PROMODA)
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("tickets:territorio"), {"empresa": self.empresa.pk})
        self.assertContains(respuesta, "Tipo de tienda")
        self.assertContains(respuesta, "Promoda")
        filtrada = self.client.get(reverse("tickets:territorio"), {"empresa": self.empresa.pk, "socio": "Promoda", "ciudad": "Guadalajara"})
        self.assertContains(filtrada, self.tienda.nombre)
        self.assertContains(filtrada, "Ver ubicación")

    def test_sla_vencido_visible_sin_necesitar_otro_cambio_de_estado(self):
        t = self.ticket()
        SegmentoSLA.objects.filter(ticket=t).update(inicio=timezone.now()-timedelta(hours=5))
        self.assertTrue(con_sla_actual(Ticket.objects.all()).get(pk=t.pk).sla_vencido_actual)
        self.client.force_login(self.juan)
        respuesta = self.client.get(reverse("tickets:lista"))
        self.assertEqual(respuesta.context["estadisticas"]["sla_excedidos"], 1)
        datos = self.client.get(reverse("tickets:tiempos", args=[t.folio])).json()
        self.assertTrue(datos["excedido"])
        self.client.force_login(self.suplente)
        self.assertEqual(self.client.get(reverse("tickets:tiempos", args=[t.folio])).status_code, 404)

    def test_clasificacion_manual_se_conserva_al_actualizar_excel(self):
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            ruta = self.excel(carpeta)
            self.assertTrue(importar_bradescard(ruta, empresa=self.empresa, usuario=self.admin, categorias=["Internet"])["ok"])
            t = Ticket.objects.get(ticket_bradescard="1001")
            regla = ConfiguracionSLA.objects.create(categoria="Soporte", incidencia_general="Reclasificado", limite_minutos=60)
            self.client.force_login(self.admin)
            self.client.post(reverse("tickets:clasificar", args=[t.folio]), {"regla": regla.pk})
            from openpyxl import load_workbook
            libro = load_workbook(ruta)
            libro.active.cell(2, list(COLUMNAS_ESPERADAS).index("incidencia_especifica")+1, "Actualización externa")
            libro.save(ruta)
            self.assertTrue(importar_bradescard(ruta, empresa=self.empresa, usuario=self.admin, categorias=["Internet"])["ok"])
            t.refresh_from_db()
            self.assertEqual(t.categoria, "Soporte")
            self.assertEqual(t.configuracion_sla, regla)

    def test_migracion_agrupa_d1_y_conserva_las_tiendas_y_registros_anteriores(self):
        from importlib import import_module
        from django.apps import apps
        otra_zona = Zona.objects.create(empresa=self.empresa, nombre="D1", codigo="D1-OTRO-ESTADO", estado="Puebla")
        tienda = Tienda.objects.create(empresa=self.empresa, zona=otra_zona, numero="B151", nombre="Bodega B151")
        grupo = GrupoTrabajo.objects.create(empresa=self.empresa, nombre="Equipo de prueba")
        grupo.zonas.add(otra_zona)
        import_module("tickets.migrations.0009_conectar_distritos_y_sla").conectar(apps, None)
        tienda.refresh_from_db()
        otra_zona.refresh_from_db()
        self.assertEqual(tienda.zona_id, self.zona.pk)
        self.assertFalse(otra_zona.activa)
        self.assertEqual(Tienda.objects.count(), 2)
        self.assertTrue(grupo.zonas.filter(pk=self.zona.pk).exists())

    def test_reporteria_muestra_y_exporta_las_incidencias_del_periodo(self):
        ticket = self.ticket()
        self.client.force_login(self.admin)
        fecha = timezone.localdate().isoformat()
        url = reverse("tickets:reporteria_incidencias")

        respuesta = self.client.get(url, {"fecha_inicio": fecha, "fecha_fin": fecha})

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, ticket.folio)
        self.assertContains(respuesta, "Bodega B150")

        excel = self.client.get(url, {"fecha_inicio": fecha, "fecha_fin": fecha, "exportar": "xlsx"})
        self.assertEqual(excel.status_code, 200)
        self.assertEqual(
            excel["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        from openpyxl import load_workbook
        libro = load_workbook(BytesIO(excel.content))
        hoja = libro["Incidencias SLA"]
        self.assertIn("Métricas por encargado", libro.sheetnames)
        self.assertIn("Resumen ejecutivo", libro.sheetnames)
        self.assertEqual(hoja["D1"].value, "Incidencias operativas con ticket · Seguimiento SLA")
        self.assertEqual(hoja["D6"].value, ("lun.", "mar.", "mié.", "jue.", "vie.", "sáb.", "dom.")[timezone.localdate().weekday()])
        self.assertEqual(hoja["D7"].value, timezone.localdate().day)

    def test_inventario_es_un_panel_vacio_solo_para_administracion(self):
        url = reverse("tickets:inventario")
        self.client.force_login(self.juan)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Inventario")
        self.assertContains(respuesta, 'class="inventory-panel"')

    def test_reporteria_acepta_periodo_rapido_semanal(self):
        ticket = self.ticket()
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            reverse("tickets:reporteria_incidencias"),
            {"periodo": "semana_actual"},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, ticket.folio)

    def test_detalle_muestra_personal_importado_de_la_tienda(self):
        persona = Persona.objects.create(id_personal="PD-TEST", nombre="Activo de tienda", activa=True)
        AsignacionPersonal.objects.create(persona=persona, empresa=self.empresa, tienda=self.tienda, alcance="TIENDA", funcion="PERSONAL", activa=True)
        ticket = self.ticket()
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("tickets:detalle", args=[ticket.folio]))
        self.assertContains(respuesta, "Personal de tienda")
        self.assertContains(respuesta, "Activo de tienda")
