from io import BytesIO
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from usuarios.models import PerfilUsuario

from .models import (
    AsignacionPersonal,
    ArchivoTicket,
    ComentarioTicket,
    ConfiguracionSLA,
    Empresa,
    EstadoTicket,
    HistorialTicket,
    ImportacionTickets,
    OrigenTicket,
    Persona,
    PrioridadTicket,
    Ticket,
    Tienda,
    Zona,
)
from .services.importacion_bradescard import responsable_automatico
from .services.importacion_catalogos import analizar_catalogo, importar_catalogo


User = get_user_model()


def excel_prueba(encabezados, filas):
    libro = Workbook()
    hoja = libro.active
    hoja.append(encabezados)
    for fila in filas:
        hoja.append(fila)
    contenido = BytesIO()
    libro.save(contenido)
    contenido.seek(0)
    return contenido


class EstructuraOperativaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin-estructura", password="clave")
        PerfilUsuario.objects.create(user=self.admin, rol=PerfilUsuario.Rol.ADMIN)
        self.usuario = User.objects.create_user(username="regular-estructura", password="clave")
        PerfilUsuario.objects.create(user=self.usuario)
        self.empresa = Empresa.objects.create(codigo="BRAD", nombre="Bradescard")

    def test_panel_solo_es_visible_para_administrador(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("tickets:estructura")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("tickets:estructura")).status_code, 200)

    def test_administrador_configura_tiempo_y_prioridad_por_incidencia(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("tickets:catalogo_nuevo", args=["incidencia"]),
            {
                "accion": "guardar",
                "categoria": "Energía",
                "incidencia_general": "Sin suministro",
                "limite_minutos": 90,
                "prioridad": PrioridadTicket.CRITICA,
                "activo": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("tickets:incidencias"),
        )
        regla = ConfiguracionSLA.objects.get(
            categoria="Energía",
            incidencia_general="Sin suministro",
        )
        self.assertEqual(regla.limite_minutos, 90)
        self.assertEqual(regla.prioridad, PrioridadTicket.CRITICA)

    def test_territorio_muestra_nombres_y_oculta_codigos_internos(self):
        zona = Zona.objects.create(
            empresa=self.empresa,
            codigo="DIST-CENTRO",
            nombre="Distrito Centro",
            estado="Jalisco",
        )
        tienda = Tienda.objects.create(
            empresa=self.empresa,
            zona=zona,
            id_externo="EXT-VISIBLE",
            numero="007",
            nombre="Sucursal visible",
            estado="Jalisco",
        )
        self.client.force_login(self.admin)

        empresas = self.client.get(
            reverse("tickets:territorio")
        )
        tiendas = self.client.get(
            reverse("tickets:territorio")
        )

        self.assertContains(empresas, "Bradescard")
        self.assertContains(tiendas, tienda.nombre)
        self.assertNotContains(tiendas, tienda.codigo)
        self.assertNotContains(tiendas, "EXT-VISIBLE")

    def test_todos_los_paneles_operativos_son_independientes(self):
        self.client.force_login(self.admin)
        for seccion in (
            "empresas", "zonas", "tiendas", "coberturas", "calendario", "sla"
        ):
            with self.subTest(seccion=seccion):
                response = self.client.get(
                    reverse("tickets:panel_configuracion", args=[seccion]), follow=True
                )
                self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self.client.get(reverse("tickets:equipos"), follow=True).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("tickets:importaciones")).status_code,
            200,
        )

    def test_cobertura_retirada_no_acepta_nuevas_asignaciones(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("tickets:panel_configuracion", args=["coberturas"]),
            {
                "accion": "guardar",
                "usuario": self.usuario.pk,
                "empresa": self.empresa.pk,
                "alcance": AsignacionPersonal.Alcance.ESTADO,
                "funcion": AsignacionPersonal.Funcion.COORDINADOR_ESTATAL,
                "estado": "Jalisco",
                "zona": "",
                "tienda": "",
                "horario": "09:00 a 18:00",
                "fecha_inicio": "2026-09-01",
                "fecha_fin": "",
                "principal": "on",
                "activa": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("tickets:estructura"),
        )
        self.assertFalse(AsignacionPersonal.objects.filter(empresa=self.empresa).exists())

    def test_centro_de_importaciones_usa_nombre_generico(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("tickets:importaciones"))

        self.assertContains(response, "Tickets externos")
        self.assertNotContains(response, "Importar Bradescard")

    def test_centro_de_importaciones_muestra_guion_si_el_usuario_fue_eliminado(self):
        ImportacionTickets.objects.create(
            nombre_archivo="historico.xlsx",
            hash_archivo="a" * 64,
            usuario=None,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("tickets:importaciones"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "historico.xlsx")

    def test_importa_zona_y_tienda_desde_excel(self):
        archivo = excel_prueba(
            [
                "ID de tienda", "Key", "Tienda", "Nombre de la tienda",
                "Dirección", "Estado", "Agencia", "Socio", "Distrital",
                "Municipio",
                "Gerente distrital", "Coordinador", "Tipo de coordinador",
                "Encargado de soporte", "Partner", "Líder actual", "Retiro",
                "Prioridad", "Piloto",
            ],
            [[
                "EXT-001", "KEY-1", "001", "Sucursal Centro",
                "Av. Constitución 100, Monterrey", "Nuevo León", "Norte",
                "Bodega", "Distrito Norte", "Monterrey", "Gerente Uno", "Coord Uno",
                "Regional", "Soporte Uno", "Soporte Dos", "Líder Uno", "No",
                "Alta", "Sí",
            ]],
        )
        preview = analizar_catalogo(archivo, "TIENDAS", self.empresa)
        resultado = importar_catalogo(preview, self.empresa)
        tienda = Tienda.objects.get(empresa=self.empresa, id_externo="EXT-001")

        self.assertEqual(resultado["nuevos"], 1)
        self.assertTrue(Zona.objects.filter(empresa=self.empresa, nombre="Distrito Norte").exists())
        self.assertRegex(tienda.codigo, r"^TDA-\d{6}$")
        self.assertEqual(tienda.encargado_soporte_nombre, "Soporte Uno")
        self.assertEqual(tienda.partner_nombre, "Soporte Dos")
        self.assertEqual(tienda.socio, "Bodega")
        self.assertEqual(tienda.cadena, Tienda.Cadena.BODEGA)
        self.assertEqual(tienda.ciudad, "Monterrey")
        self.assertTrue(tienda.piloto)
        self.assertFalse(tienda.retiro)
        self.assertEqual(preview["resumen"], {"nuevas": 1, "actualizables": 0})

    def test_reimportar_tienda_conserva_codigo_y_reinicia_ubicacion(self):
        zona = Zona.objects.create(
            empresa=self.empresa, codigo="DIST-1", nombre="Distrito", estado="Jalisco"
        )
        tienda = Tienda.objects.create(
            empresa=self.empresa,
            zona=zona,
            id_externo="EXT-2",
            numero="002",
            nombre="Tienda anterior",
            estado="Jalisco",
            direccion="Dirección anterior",
            latitud=20.67,
            longitud=-103.35,
            estado_geocodificacion=Tienda.EstadoGeocodificacion.LOCALIZADA,
        )
        codigo_original = tienda.codigo
        archivo = excel_prueba(
            ["ID de tienda", "Tienda", "Nombre de la tienda", "Estado", "Distrital", "Dirección"],
            [["EXT-2", "002", "Tienda actualizada", "Jalisco", "Distrito", "Dirección nueva"]],
        )
        preview = analizar_catalogo(archivo, "TIENDAS", self.empresa)
        resultado = importar_catalogo(preview, self.empresa)
        tienda.refresh_from_db()

        self.assertEqual(resultado["actualizados"], 1)
        self.assertEqual(tienda.codigo, codigo_original)
        self.assertEqual(tienda.nombre, "Tienda actualizada")
        self.assertIsNone(tienda.latitud)
        self.assertEqual(tienda.estado_geocodificacion, Tienda.EstadoGeocodificacion.PENDIENTE)

    def test_detecta_id_de_tienda_repetido_en_el_archivo(self):
        archivo = excel_prueba(
            ["ID de tienda", "Tienda", "Nombre de la tienda", "Estado", "Distrital"],
            [
                ["EXT-3", "003", "Tienda 3", "Puebla", "Centro"],
                ["EXT-3", "004", "Tienda 4", "Puebla", "Centro"],
            ],
        )
        preview = analizar_catalogo(archivo, "TIENDAS", self.empresa)

        self.assertEqual(len(preview["errores"]), 1)
        self.assertIn("repetido", preview["errores"][0]["errores"][0])

    def test_mapa_de_tiendas_es_solo_para_administradores(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("tickets:mapa_tiendas")).status_code, 403)
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("tickets:mapa_tiendas"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Tipo de tienda")
        self.assertContains(respuesta, "Ciudad/localidad")
        self.assertContains(respuesta, "Aplicar filtros")
        self.assertContains(respuesta, "Mapa vectorial de México")
        self.assertContains(respuesta, "Buscar tienda o calle")
        self.assertContains(respuesta, "vendor/maplibre/maplibre-gl.")

    def test_mapa_vectorial_acepta_solicitudes_por_rango(self):
        self.client.force_login(self.admin)
        with TemporaryDirectory() as directorio:
            mapas = Path(directorio) / "mapas"
            mapas.mkdir()
            (mapas / "mexico-20260913.pmtiles").write_bytes(b"0123456789")
            with override_settings(MEDIA_ROOT=directorio):
                respuesta = self.client.get(
                    reverse("tickets:mapa_vectorial_mexico"),
                    headers={"range": "bytes=2-5"},
                )
                contenido = b"".join(respuesta.streaming_content)
        self.assertEqual(respuesta.status_code, 206)
        self.assertEqual(respuesta["Content-Range"], "bytes 2-5/10")
        self.assertEqual(respuesta["Accept-Ranges"], "bytes")
        self.assertEqual(contenido, b"2345")

    def test_filtros_del_mapa_actualizan_solo_los_datos(self):
        zona = Zona.objects.create(
            empresa=self.empresa, codigo="MAP-D1", nombre="D1", estado="Veracruz"
        )
        tienda = Tienda.objects.create(
            empresa=self.empresa, zona=zona, numero="031", nombre="Tienda Veracruz",
            socio="Bodega", cadena=Tienda.Cadena.BODEGA, estado="VERACRUZ",
            ciudad="Veracruz", direccion="Centro, Veracruz", latitud="19.1738", longitud="-96.1342",
        )
        Tienda.objects.create(
            empresa=self.empresa, zona=zona, numero="032", nombre="Otra tienda",
            socio="Promoda", cadena=Tienda.Cadena.PROMODA, estado="VERACRUZ",
            ciudad="Xalapa", latitud="19.5438", longitud="-96.9102",
        )
        self.client.force_login(self.admin)
        respuesta = self.client.get(
            reverse("tickets:mapa_tiendas"),
            {"socio": "Bodega", "distrital": "D1", "estado": "VERACRUZ", "ciudad": "Veracruz"},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(datos["total"], 1)
        self.assertEqual(datos["localizadas"], 1)
        self.assertEqual(datos["marcadores"][0]["id"], tienda.pk)
        self.assertEqual(datos["marcadores"][0]["ciudad"], "Veracruz")

    def test_administrador_puede_descargar_plantilla_de_tiendas(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("tickets:plantilla_tiendas"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("plantilla_tiendas_carobra.xlsx", respuesta["Content-Disposition"])
        self.assertTrue(respuesta.content.startswith(b"PK"))

    def test_encargado_de_soporte_es_responsable_automatico_del_ticket(self):
        agente = User.objects.create_user(username="soporte-tienda", password="clave")
        PerfilUsuario.objects.create(user=agente)
        persona = Persona.objects.create(
            id_personal="SOP-1", nombre="Soporte Tienda", usuario=agente
        )
        zona = Zona.objects.create(
            empresa=self.empresa, codigo="DIST-SOP", nombre="Distrito Soporte", estado="México"
        )
        tienda = Tienda.objects.create(
            empresa=self.empresa,
            zona=zona,
            id_externo="EXT-SOP",
            numero="SOP-01",
            nombre="Tienda con soporte",
            estado="México",
            encargado_soporte=persona,
            encargado_soporte_nombre=persona.nombre,
        )

        self.assertEqual(responsable_automatico(tienda), agente)

    def test_cobertura_legada_ya_no_decide_la_asignacion(self):
        agente = User.objects.create_user(
            username="cobertura-incidencia", password="clave"
        )
        PerfilUsuario.objects.create(user=agente)
        persona = Persona.objects.create(
            id_personal="COV-1", nombre="Agente Cobertura", usuario=agente
        )
        zona = Zona.objects.create(
            empresa=self.empresa,
            codigo="DIST-COV",
            nombre="Distrito Cobertura",
            estado="Jalisco",
        )
        tienda = Tienda.objects.create(
            empresa=self.empresa,
            zona=zona,
            id_externo="EXT-COV",
            numero="COV-01",
            nombre="Tienda Cobertura",
            estado="Jalisco",
        )
        incidencia = ConfiguracionSLA.objects.create(
            categoria="Red", incidencia_general="Sin enlace",
            limite_minutos=120, prioridad=PrioridadTicket.ALTA,
        )
        cobertura = AsignacionPersonal.objects.create(
            persona=persona,
            empresa=self.empresa,
            alcance=AsignacionPersonal.Alcance.TIENDA,
            funcion=AsignacionPersonal.Funcion.PERSONAL,
            tienda=tienda,
        )
        cobertura.incidencias.add(incidencia)

        self.assertIsNone(responsable_automatico(tienda, incidencia))

    def test_importacion_de_coordenadas_actualiza_sin_duplicar_tienda(self):
        zona = Zona.objects.create(
            empresa=self.empresa, codigo="DIST-GDL", nombre="Guadalajara", estado="Jalisco"
        )
        tienda = Tienda.objects.create(
            empresa=self.empresa,
            zona=zona,
            id_externo="EXT-GDL",
            numero="100",
            nombre="Tienda sin coordenadas",
            estado="Jalisco",
        )
        nombre_original = tienda.nombre
        archivo = excel_prueba(
            ["Longitud", "ID de tienda", "Latitud"],
            [[-103.349609, "EXT-GDL", 20.659699]],
        )
        preview = analizar_catalogo(archivo, "COORDENADAS", self.empresa)
        resultado = importar_catalogo(preview, self.empresa)
        tienda.refresh_from_db()

        self.assertEqual(resultado["actualizados"], 1)
        self.assertEqual(Tienda.objects.filter(empresa=self.empresa).count(), 1)
        self.assertEqual(tienda.nombre, nombre_original)
        self.assertEqual(str(tienda.latitud), "20.659699")
        self.assertEqual(str(tienda.longitud), "-103.349609")
        self.assertEqual(tienda.estado_geocodificacion, Tienda.EstadoGeocodificacion.LOCALIZADA)

    def test_importacion_de_coordenadas_rechaza_id_desconocido(self):
        archivo = excel_prueba(
            ["ID de tienda", "Latitud", "Longitud"],
            [["NO-EXISTE", 19.432608, -99.133209]],
        )
        preview = analizar_catalogo(archivo, "COORDENADAS", self.empresa)

        self.assertEqual(preview["filas"], [])
        self.assertIn("no existe", preview["errores"][0]["errores"][0])

    def test_administrador_puede_editar_coordenadas_manualmente(self):
        zona = Zona.objects.create(
            empresa=self.empresa, codigo="DIST-CDMX", nombre="CDMX", estado="Ciudad de México"
        )
        tienda = Tienda.objects.create(
            empresa=self.empresa,
            zona=zona,
            id_externo="EXT-CDMX",
            numero="200",
            nombre="Tienda CDMX",
            estado="Ciudad de México",
        )
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse("tickets:actualizar_coordenadas"), {
            "tienda": tienda.pk,
            "latitud": "19.432608",
            "longitud": "-99.133209",
        })
        tienda.refresh_from_db()

        self.assertRedirects(respuesta, reverse("tickets:mapa_tiendas"))
        self.assertEqual(str(tienda.latitud), "19.432608")
        self.assertEqual(str(tienda.longitud), "-99.133209")

    def test_descarga_plantilla_exclusiva_de_coordenadas(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("tickets:plantilla_coordenadas"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("plantilla_coordenadas_tiendas.xlsx", respuesta["Content-Disposition"])

    def test_importa_usuario_sin_exponer_password_en_excel(self):
        archivo = excel_prueba(
            ["CORREO", "NOMBRE", "APELLIDOS", "NUMERO_EMPLEADO", "ROL"],
            [["nueva@empresa.com", "Nueva", "Persona", "EMP-1", "USUARIO"]],
        )
        preview = analizar_catalogo(archivo, "USUARIOS")
        resultado = importar_catalogo(preview)
        usuario = User.objects.get(email="nueva@empresa.com")

        self.assertEqual(resultado["nuevos"], 1)
        self.assertTrue(usuario.has_usable_password())
        self.assertTrue(hasattr(usuario, "persona_operativa"))


class SeguridadTicketsTests(TestCase):
    def setUp(self):
        self.media_temporal = TemporaryDirectory()
        self.addCleanup(self.media_temporal.cleanup)
        self.media_settings = override_settings(
            MEDIA_ROOT=self.media_temporal.name
        )
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)

        self.admin = self.crear_usuario("admin", PerfilUsuario.Rol.ADMIN)
        self.creador = self.crear_usuario("creador")
        self.asignado = self.crear_usuario("asignado")
        self.ajeno = self.crear_usuario("ajeno")

        self.ticket_creado = Ticket.objects.create(
            folio="TK-PRUEBA-CREADO",
            origen=OrigenTicket.BRADESCARD,
            ticket_bradescard="BRAD-10001",
            creado_por=self.creador,
            incidencia_especifica="Ticket creado por el usuario",
        )
        self.ticket_asignado = Ticket.objects.create(
            folio="TK-PRUEBA-ASIGNADO",
            responsable=self.creador,
            creado_por=self.admin,
            incidencia_especifica="Ticket asignado al usuario",
        )
        self.ticket_ajeno = Ticket.objects.create(
            folio="TK-PRUEBA-AJENO",
            creado_por=self.ajeno,
            responsable=self.asignado,
            incidencia_especifica="Ticket que no debe ver",
        )

    def crear_usuario(self, username, rol=PerfilUsuario.Rol.USUARIO):
        usuario = User.objects.create_user(
            username=username,
            password="clave-segura",
            email=f"{username}@empresa.com",
        )
        PerfilUsuario.objects.create(user=usuario, rol=rol, activo=True)
        return usuario

    def crear_archivo(self, ticket, comentario=None, nombre="evidencia.pdf"):
        return ArchivoTicket.objects.create(
            ticket=ticket,
            comentario=comentario,
            usuario=self.admin,
            archivo=SimpleUploadedFile(
                nombre,
                b"contenido protegido",
                content_type="application/pdf",
            ),
            nombre_original=nombre,
            mime_type="application/pdf",
            size_bytes=19,
        )

    def test_usuario_solo_lista_tickets_creados_o_asignados(self):
        self.client.force_login(self.creador)

        response = self.client.get(reverse("tickets:lista"), {"vista": "todos"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket_creado.folio)
        self.assertContains(response, self.ticket_asignado.folio)
        self.assertNotContains(response, self.ticket_ajeno.folio)
        self.assertEqual(response.context["estadisticas"]["total"], 2)

    def test_listado_inicial_del_usuario_muestra_tickets_asignados(self):
        self.client.force_login(self.creador)

        response = self.client.get(reverse("tickets:lista"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["vista_actual"], "encargado")
        self.assertContains(response, "Mis tickets")
        self.assertContains(response, self.ticket_asignado.folio)
        self.assertNotContains(response, self.ticket_creado.folio)

    def test_vista_partner_muestra_solo_los_tickets_del_partner_actual(self):
        ticket_partner = Ticket.objects.create(
            folio="TK-PRUEBA-PARTNER",
            creado_por=self.admin,
            partner=self.creador,
            incidencia_especifica="Ticket asignado al partner",
        )
        self.client.force_login(self.creador)

        response = self.client.get(reverse("tickets:lista"), {"vista": "partner"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partner")
        self.assertContains(response, ticket_partner.folio)
        self.assertNotContains(response, self.ticket_creado.folio)
        self.assertNotContains(response, self.ticket_asignado.folio)

    def test_filtros_por_fecha_de_cierre_y_prioridad(self):
        hoy = timezone.now()
        cerrado_reciente = Ticket.objects.create(
            folio="TK-CIERRE-RECIENTE",
            creado_por=self.admin,
            estado_interno=EstadoTicket.CERRADO,
            prioridad=PrioridadTicket.CRITICA,
            cerrado_at=hoy,
        )
        cerrado_anterior = Ticket.objects.create(
            folio="TK-CIERRE-ANTERIOR",
            creado_por=self.admin,
            estado_interno=EstadoTicket.CERRADO,
            prioridad=PrioridadTicket.BAJA,
            cerrado_at=hoy - timedelta(days=7),
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("tickets:lista"),
            {
                "vista": "todos",
                "fecha_cierre_desde": timezone.localdate().isoformat(),
                "prioridad": PrioridadTicket.CRITICA,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, cerrado_reciente.folio)
        self.assertNotContains(response, cerrado_anterior.folio)

    def test_listado_y_encabezado_destacan_ticket_bradescard(self):
        self.client.force_login(self.creador)

        list_response = self.client.get(reverse("tickets:lista"), {"vista": "todos"})
        self.assertContains(list_response, "BRAD-10001")
        self.assertContains(list_response, "Ticket Bradescard")

        detail_response = self.client.get(
            reverse("tickets:detalle", args=[self.ticket_creado.folio])
        )
        content = detail_response.content.decode()
        hero = content.split('<section class="ticket-hero" id="ticket-resumen">', 1)[1].split(
            "</section>",
            1,
        )[0]
        self.assertIn("BRAD-10001", hero)
        self.assertNotIn("Ticket creado por el usuario", hero)

    def test_administrador_lista_todos_los_tickets(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("tickets:lista"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket_creado.folio)
        self.assertContains(response, self.ticket_asignado.folio)
        self.assertContains(response, self.ticket_ajeno.folio)
        self.assertEqual(response.context["estadisticas"]["total"], 3)

    def test_listado_ordena_por_columna_y_deja_cerrados_al_final(self):
        cerrado = Ticket.objects.create(
            folio="TK-PRUEBA-CERRADO",
            ticket_bradescard="100",
            categoria="A",
            creado_por=self.admin,
            estado_interno=EstadoTicket.CERRADO,
        )
        abierto = Ticket.objects.create(
            folio="TK-PRUEBA-ABIERTO",
            ticket_bradescard="200",
            categoria="Z",
            creado_por=self.admin,
            estado_interno=EstadoTicket.NUEVO,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("tickets:lista"),
            {"orden": "ticket", "direccion": "asc"},
        )

        tickets = list(response.context["pagina"])
        self.assertEqual(response.status_code, 200)
        self.assertLess(tickets.index(abierto), tickets.index(cerrado))
        self.assertContains(response, "Ir a página")
        self.assertContains(response, "orden=ticket")

        partial_response = self.client.get(
            reverse("tickets:lista"),
            {"orden": "estado", "direccion": "asc"},
            headers={"x-requested-with": "XMLHttpRequest"},
        )

        self.assertEqual(partial_response.status_code, 200)
        self.assertTemplateUsed(partial_response, "tickets/_lista_resultados.html")
        self.assertContains(partial_response, 'id="ticketsResults"')
        self.assertNotContains(partial_response, "<html")

    def test_detalle_muestra_responsable_sin_asignar_en_tienda(self):
        empresa = Empresa.objects.create(codigo="SINRESP", nombre="Empresa sin responsable")
        zona = Zona.objects.create(
            empresa=empresa,
            codigo="SINRESP-ZONA",
            nombre="Zona sin responsable",
        )
        tienda = Tienda.objects.create(
            empresa=empresa,
            zona=zona,
            nombre="Sucursal sin responsable",
        )
        ticket = Ticket.objects.create(
            folio="TK-PRUEBA-SIN-RESPONSABLE",
            empresa=empresa,
            tienda_registrada=tienda,
            creado_por=self.creador,
            incidencia_especifica="Ticket pendiente de asignacion.",
        )
        self.client.force_login(self.creador)

        response = self.client.get(reverse("tickets:detalle", args=[ticket.folio]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sin asignar")

    def test_usuario_no_puede_abrir_ticket_ajeno(self):
        self.client.force_login(self.creador)

        response = self.client.get(
            reverse("tickets:detalle", args=[self.ticket_ajeno.folio])
        )

        self.assertEqual(response.status_code, 404)

    def test_partner_de_tienda_puede_ver_y_comentar_ticket(self):
        empresa = Empresa.objects.create(codigo="PART", nombre="Empresa partner")
        zona = Zona.objects.create(
            empresa=empresa,
            codigo="PART-ZONA",
            nombre="Zona partner",
            estado="Jalisco",
        )
        persona_partner = Persona.objects.create(
            id_personal="PART-1",
            nombre="Partner de soporte",
            usuario=self.creador,
        )
        tienda = Tienda.objects.create(
            empresa=empresa,
            zona=zona,
            nombre="Tienda partner",
            estado="Jalisco",
            partner=persona_partner,
            partner_nombre=persona_partner.nombre,
        )
        ticket = Ticket.objects.create(
            folio="TK-PRUEBA-PARTNER",
            empresa=empresa,
            tienda_registrada=tienda,
            partner=self.creador,
            creado_por=self.ajeno,
            responsable=self.asignado,
            incidencia_especifica="Seguimiento visible para el partner",
        )
        self.client.force_login(self.creador)

        detail_response = self.client.get(
            reverse("tickets:detalle", args=[ticket.folio])
        )
        comment_response = self.client.post(
            reverse("tickets:detalle", args=[ticket.folio]),
            {
                "accion": "comentario",
                "comentario": "Actualización realizada por el partner.",
                "tipo": ComentarioTicket.Tipo.COMENTARIO,
            },
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.context["rol_en_ticket"], "Partner")
        self.assertRedirects(
            comment_response,
            reverse("tickets:detalle", args=[ticket.folio]),
        )
        self.assertTrue(
            ticket.comentarios.filter(usuario=self.creador).exists()
        )

    def test_creacion_carobra_asigna_origen_equipo_prioridad_y_sla(self):
        empresa = Empresa.objects.create(codigo="CAR", nombre="CAROBRA")
        zona = Zona.objects.create(
            empresa=empresa,
            codigo="CAR-ZONA",
            nombre="Zona CAROBRA",
            estado="Jalisco",
        )
        persona_responsable = Persona.objects.create(
            id_personal="CAR-RESP",
            nombre="Responsable CAROBRA",
            usuario=self.asignado,
        )
        persona_partner = Persona.objects.create(
            id_personal="CAR-PART",
            nombre="Partner CAROBRA",
            usuario=self.creador,
        )
        tienda = Tienda.objects.create(
            empresa=empresa,
            zona=zona,
            nombre="Sucursal CAROBRA",
            estado="Jalisco",
            encargado_soporte=persona_responsable,
            partner=persona_partner,
        )
        ConfiguracionSLA.objects.create(
            categoria="Internet",
            incidencia_general="Sin servicio",
            limite_minutos=120,
            prioridad=PrioridadTicket.ALTA,
        )
        self.client.force_login(self.ajeno)

        response = self.client.post(
            reverse("tickets:crear"),
            {
                "tienda_registrada": tienda.pk,
                "categoria": "Internet",
                "incidencia_general": "Sin servicio",
                "incidencia_especifica": "La sucursal no tiene conexión.",
            },
        )

        ticket = Ticket.objects.get(creado_por=self.ajeno, empresa=empresa)
        self.assertRedirects(
            response,
            reverse("tickets:detalle", args=[ticket.folio]),
        )
        self.assertEqual(ticket.origen, OrigenTicket.CAROBRA)
        self.assertEqual(ticket.responsable, self.asignado)
        self.assertEqual(ticket.partner, self.creador)
        self.assertEqual(ticket.estado_interno, EstadoTicket.ASIGNADO)
        self.assertEqual(ticket.prioridad, PrioridadTicket.ALTA)
        self.assertEqual(ticket.sla_limite_minutos, 120)
        self.assertTrue(
            ticket.historial.filter(evento=HistorialTicket.Evento.CREADO).exists()
        )

    def test_filtro_separa_tickets_carobra_y_bradescard(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("tickets:lista"),
            {"origen": OrigenTicket.BRADESCARD},
        )

        self.assertContains(response, self.ticket_creado.folio)
        self.assertNotContains(response, self.ticket_asignado.folio)
        self.assertEqual(response.context["pagina"].paginator.count, 1)

    def test_participante_no_puede_cerrar_sin_evidencia(self):
        self.client.force_login(self.creador)

        response = self.client.post(
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
            {
                "accion": "cierre",
                "comentario": "La incidencia quedó solucionada.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Este campo es obligatorio")
        self.ticket_creado.refresh_from_db()
        self.assertNotEqual(
            self.ticket_creado.estado_interno,
            EstadoTicket.CERRADO,
        )

    def test_formulario_de_cierre_se_integra_en_seguimiento(self):
        self.client.force_login(self.creador)

        response = self.client.get(
            reverse("tickets:detalle", args=[self.ticket_creado.folio])
        )

        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode()
        seguimiento = contenido.index('id="ticket-seguimiento"')
        cierre = contenido.index('name="accion" value="cierre"')
        formulario = contenido.rfind('<form', 0, cierre)
        self.assertLess(seguimiento, cierre)
        self.assertIn('class="ticket-followup"', contenido[formulario:cierre])
        self.assertNotIn('class="ticket-followup-close"', contenido)
        self.assertNotIn('id="ticket-ciclo"', contenido)

    def test_participante_cierra_con_comentario_y_evidencia(self):
        self.client.force_login(self.creador)

        response = self.client.post(
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
            {
                "accion": "cierre",
                "comentario": "Se validó la solución con la tienda.",
                "archivo": SimpleUploadedFile(
                    "cierre.pdf",
                    b"evidencia de cierre",
                    content_type="application/pdf",
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
        )
        self.ticket_creado.refresh_from_db()
        self.assertEqual(
            self.ticket_creado.estado_interno,
            EstadoTicket.CERRADO,
        )
        self.assertIsNotNone(self.ticket_creado.cerrado_at)
        self.assertTrue(
            self.ticket_creado.comentarios.filter(
                usuario=self.creador,
                tipo=ComentarioTicket.Tipo.CIERRE,
            ).exists()
        )
        self.assertTrue(
            self.ticket_creado.archivos.filter(
                usuario=self.creador,
                tipo=ArchivoTicket.Tipo.CIERRE,
            ).exists()
        )
        self.assertTrue(
            self.ticket_creado.historial.filter(
                evento="CERRADO",
                usuario=self.creador,
            ).exists()
        )

    def test_usuario_regular_no_puede_reabrir_ticket(self):
        self.ticket_creado.estado_interno = EstadoTicket.CERRADO
        self.ticket_creado.save(update_fields=["estado_interno"])
        self.client.force_login(self.creador)

        response = self.client.post(
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
            {
                "accion": "reapertura",
                "motivo_reapertura": "La falla volvió a presentarse.",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.ticket_creado.refresh_from_db()
        self.assertEqual(
            self.ticket_creado.estado_interno,
            EstadoTicket.CERRADO,
        )

    def test_administrador_reabre_y_conserva_sla_excedido(self):
        self.ticket_creado.estado_interno = EstadoTicket.CERRADO
        self.ticket_creado.sla_excedido = True
        self.ticket_creado.save(
            update_fields=["estado_interno", "sla_excedido"]
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
            {
                "accion": "reapertura",
                "motivo_reapertura": "Bradescard mantiene el ticket abierto.",
            },
        )

        self.assertRedirects(
            response,
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
        )
        self.ticket_creado.refresh_from_db()
        self.assertEqual(
            self.ticket_creado.estado_interno,
            EstadoTicket.EN_PROCESO,
        )
        self.assertEqual(self.ticket_creado.numero_reaperturas, 1)
        self.assertTrue(self.ticket_creado.sla_excedido)
        self.assertTrue(
            self.ticket_creado.historial.filter(
                evento="REABIERTO",
                usuario=self.admin,
            ).exists()
        )

    def test_administrador_no_puede_omitir_evidencia_desde_gestion(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
            {
                "accion": "gestion",
                "estado_interno": EstadoTicket.CERRADO,
                "prioridad": self.ticket_creado.prioridad,
                "responsable": "",
                "grupo": "",
                "subgrupo": "",
                "dependencia_actual": "",
                "estatus_operativo_actual": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("estado_interno", response.context["gestion_form"].errors)
        self.ticket_creado.refresh_from_db()
        self.assertNotEqual(
            self.ticket_creado.estado_interno,
            EstadoTicket.CERRADO,
        )

    def test_usuario_no_puede_gestionar_ticket_con_post_manual(self):
        self.client.force_login(self.creador)

        response = self.client.post(
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
            {
                "accion": "gestion",
                "estado_interno": EstadoTicket.CERRADO,
                "prioridad": self.ticket_creado.prioridad,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.ticket_creado.refresh_from_db()
        self.assertEqual(self.ticket_creado.estado_interno, EstadoTicket.NUEVO)

    def test_importacion_es_exclusiva_para_administradores(self):
        self.client.force_login(self.creador)

        response = self.client.get(reverse("tickets:importar_bradescard"))

        self.assertEqual(response.status_code, 403)

    def test_notas_internas_no_se_muestran_ni_se_aceptan_al_usuario(self):
        ComentarioTicket.objects.create(
            ticket=self.ticket_creado,
            usuario=self.admin,
            tipo=ComentarioTicket.Tipo.INTERNO,
            comentario="Información confidencial interna",
        )
        self.client.force_login(self.creador)

        response = self.client.get(
            reverse("tickets:detalle", args=[self.ticket_creado.folio])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Información confidencial interna")
        self.assertNotContains(response, "Nota interna")
        self.assertNotContains(response, "Guardar responsable")
        self.assertNotContains(response, "Gestión interna")

        post_response = self.client.post(
            reverse("tickets:detalle", args=[self.ticket_creado.folio]),
            {
                "accion": "comentario",
                "comentario": "Intento de nota privada",
                "tipo": ComentarioTicket.Tipo.INTERNO,
            },
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertFalse(
            ComentarioTicket.objects.filter(
                comentario="Intento de nota privada"
            ).exists()
        )

    def test_archivo_se_sirve_por_ruta_autenticada(self):
        archivo = self.crear_archivo(self.ticket_creado)
        self.client.force_login(self.creador)

        response = self.client.get(
            reverse("tickets:descargar_archivo", args=[archivo.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(
            b"".join(response.streaming_content),
            b"contenido protegido",
        )

    def test_archivo_de_ticket_ajeno_devuelve_404(self):
        archivo = self.crear_archivo(self.ticket_ajeno)
        self.client.force_login(self.creador)

        response = self.client.get(
            reverse("tickets:descargar_archivo", args=[archivo.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_archivo_de_nota_interna_solo_es_visible_para_admin(self):
        comentario = ComentarioTicket.objects.create(
            ticket=self.ticket_creado,
            usuario=self.admin,
            tipo=ComentarioTicket.Tipo.INTERNO,
            comentario="Nota con evidencia privada",
        )
        archivo = self.crear_archivo(self.ticket_creado, comentario=comentario)

        self.client.force_login(self.creador)
        regular_response = self.client.get(
            reverse("tickets:descargar_archivo", args=[archivo.pk])
        )
        self.assertEqual(regular_response.status_code, 404)

        self.client.force_login(self.admin)
        admin_response = self.client.get(
            reverse("tickets:descargar_archivo", args=[archivo.pk])
        )
        self.assertEqual(admin_response.status_code, 200)

    def test_archivo_requiere_inicio_de_sesion(self):
        archivo = self.crear_archivo(self.ticket_creado)
        url = reverse("tickets:descargar_archivo", args=[archivo.pk])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('login')}?next={url}")
