import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase

from usuarios.models import IdentidadLegacyUsuario, PerfilUsuario

from .models import ComentarioTicket, Empresa, SegmentoSLA, Ticket, Tienda, Zona
from .services.legacy_import.analizador import analizar_legacy
from .services.legacy_import.esquema import EstadoAnalisisLegacy


User = get_user_model()


class MigrarSistemaLegacyDryRunTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(
            username="ana-django", email="ana@empresa.test",
        )
        PerfilUsuario.objects.create(user=cls.usuario)
        cls.empresa = Empresa.objects.create(codigo="BRAD", nombre="Bradescard")
        cls.zona = Zona.objects.create(
            empresa=cls.empresa, codigo="NORTE", nombre="Norte", estado="Nuevo León",
        )
        cls.tienda = Tienda.objects.create(
            empresa=cls.empresa, zona=cls.zona, id_externo="T-101",
            nombre="Tienda 101", estado="Nuevo León",
        )

    def setUp(self):
        self.temporal = TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)

    def datos_base(self):
        return {
            "usuarios": [{
                "id": "17", "username": "ana-django", "email": "ana@empresa.test",
                "rol": "SOPORTE", "empresa_codigo": "BRAD",
            }],
            "tickets": [{
                "id": "551", "legacy_estado": "En seguimiento",
                "responsable_legacy_id": "17", "empresa_codigo": "BRAD",
                "tienda_identificador": "T-101", "tienda_campo": "id_externo",
                "sla_legacy_segundos": 5400,
            }],
            "comentarios": [],
            "historial": [],
            "grupos": [],
            "coberturas": [],
        }

    def ejecutar(self, datos, *, source="php_mysql", report=None):
        ruta = Path(self.temporal.name) / "entrada.json"
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        salida = StringIO()
        argumentos = ["--dry-run", "--source", source, "--input", str(ruta)]
        if report:
            argumentos.extend(["--report", str(report)])
        call_command("migrar_sistema_legacy", *argumentos, stdout=salida)
        return salida.getvalue()

    def test_comando_exige_dry_run(self):
        ruta = Path(self.temporal.name) / "entrada.json"
        ruta.write_text(json.dumps(self.datos_base()), encoding="utf-8")

        with self.assertRaisesMessage(CommandError, "modo escritura"):
            call_command("migrar_sistema_legacy", "--source", "php_mysql", "--input", str(ruta))

    def test_source_vacio_se_rechaza(self):
        with self.assertRaisesMessage(CommandError, "--source no puede estar vacío"):
            self.ejecutar(self.datos_base(), source="   ")

    def test_json_invalido_se_rechaza(self):
        ruta = Path(self.temporal.name) / "invalido.json"
        ruta.write_text("{no es json", encoding="utf-8")

        with self.assertRaisesMessage(CommandError, "JSON_INVALIDO"):
            call_command(
                "migrar_sistema_legacy", "--dry-run", "--source", "php_mysql", "--input", str(ruta),
            )

    def test_estructura_incompleta_se_reporta_sin_escrituras(self):
        datos = {"usuarios": [], "tickets": []}
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        contenido = json.loads(reporte.read_text(encoding="utf-8"))
        self.assertIn("ESTRUCTURA_SECCION_FALTANTE", {error["codigo"] for error in contenido["errores"]})
        self.assertFalse(contenido["base_datos_modificada"])

    def test_usuario_match_existente(self):
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(self.datos_base(), report=reporte)

        usuario = json.loads(reporte.read_text(encoding="utf-8"))["usuarios"][0]
        self.assertEqual(usuario["accion"], "MATCH_EXISTENTE")
        self.assertEqual(usuario["django_user_id"], self.usuario.pk)

    def test_usuario_nuevo_solo_se_propone(self):
        datos = self.datos_base()
        datos["usuarios"][0].update({"id": "18", "username": "nuevo", "email": "nuevo@empresa.test"})
        datos["tickets"] = []
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        usuario = json.loads(reporte.read_text(encoding="utf-8"))["usuarios"][0]
        self.assertEqual(usuario["accion"], "CREAR_NUEVO")
        self.assertIsNone(usuario["django_user_id"])
        self.assertFalse(User.objects.filter(username="nuevo").exists())

    def test_usuario_conflictivo_esta_bloqueado(self):
        otro = User.objects.create_user(username="otro", email="otro@empresa.test")
        PerfilUsuario.objects.create(user=otro)
        IdentidadLegacyUsuario.objects.create(
            user=self.usuario, legacy_source="php_mysql", legacy_id="99",
        )
        datos = self.datos_base()
        datos["usuarios"] = [{
            "id": "99", "username": "otro", "email": "otro@empresa.test",
            "rol": "SOPORTE", "empresa_codigo": "BRAD",
        }]
        datos["tickets"] = []
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        usuario = json.loads(reporte.read_text(encoding="utf-8"))["usuarios"][0]
        self.assertEqual(usuario["accion"], "CONFLICTO")
        self.assertEqual(usuario["estado"], EstadoAnalisisLegacy.BLOQUEADO)

    def test_ticket_listo_para_migrar_sin_crearlo(self):
        reporte = Path(self.temporal.name) / "reporte.json"

        salida = self.ejecutar(self.datos_base(), report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["estado"], EstadoAnalisisLegacy.LISTO_PARA_MIGRAR)
        self.assertEqual(ticket["estado_destino"], "EN_PROCESO")
        self.assertEqual(ticket["responsable_django_user_id"], self.usuario.pk)
        self.assertEqual(ticket["empresa_django_id"], self.empresa.pk)
        self.assertEqual(ticket["tienda_django_id"], self.tienda.pk)
        self.assertEqual(ticket["sla_legacy_segundos"], 5400)
        self.assertIn("Base de datos modificada: NO", salida)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_ticket_con_estado_desconocido_esta_bloqueado(self):
        datos = self.datos_base()
        datos["tickets"][0]["legacy_estado"] = "En tránsito no definido"
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertIn("ESTADO_LEGACY_DESCONOCIDO", ticket["errores"])

    def test_responsable_legacy_inexistente_bloquea_ticket(self):
        datos = self.datos_base()
        datos["tickets"][0]["responsable_legacy_id"] = "404"
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertIn("RESPONSABLE_LEGACY_NO_EXISTENTE", ticket["errores"])

    def test_tienda_exacta_con_campo_explicito(self):
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(self.datos_base(), report=reporte)

        self.assertEqual(
            json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]["tienda_django_id"],
            self.tienda.pk,
        )

    def test_tienda_sin_campo_queda_en_revision(self):
        datos = self.datos_base()
        datos["tickets"][0].pop("tienda_campo")
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["estado"], EstadoAnalisisLegacy.REQUIERE_REVISION)
        self.assertIn("TIENDA_CAMPO_FALTANTE", ticket["advertencias"])

    def test_sla_exacto_valido(self):
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(self.datos_base(), report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["sla_disponibilidad"], "EXACTO")
        self.assertEqual(ticket["sla_legacy_segundos"], 5400)

    def test_sla_invalido_no_se_inventa(self):
        datos = self.datos_base()
        datos["tickets"][0]["sla_legacy_segundos"] = -1
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["sla_disponibilidad"], "NO_DISPONIBLE")
        self.assertIsNone(ticket["sla_legacy_segundos"])
        self.assertIn("SLA_LEGACY_INVALIDO", ticket["advertencias"])

    def test_comentario_con_ticket_inexistente_esta_bloqueado(self):
        datos = self.datos_base()
        datos["comentarios"] = [{"id": "c-1", "ticket_legacy_id": "999", "texto": "Comentario"}]
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        comentario = json.loads(reporte.read_text(encoding="utf-8"))["comentarios"][0]
        self.assertEqual(comentario["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertIn("TICKET_LEGACY_NO_EXISTENTE", comentario["errores"])

    def test_timestamp_invalido_bloquea(self):
        datos = self.datos_base()
        datos["tickets"][0]["created_at"] = "ayer a las muchas"
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertIn("TIMESTAMP_INVALIDO", ticket["errores"])

    def test_secretos_no_aparecen_en_salida_ni_reporte(self):
        datos = self.datos_base()
        datos["usuarios"][0].update({
            "password_hash": "HASH_ULTRA_SECRETO",
            "remember_token": "TOKEN_ULTRA_SECRETO",
        })
        reporte = Path(self.temporal.name) / "reporte.json"

        salida = self.ejecutar(datos, report=reporte)

        contenido = reporte.read_text(encoding="utf-8")
        self.assertNotIn("HASH_ULTRA_SECRETO", salida + contenido)
        self.assertNotIn("TOKEN_ULTRA_SECRETO", salida + contenido)
        self.assertNotIn("password_hash", contenido)

    def test_dos_dry_runs_no_modifican_base_de_datos(self):
        conteos_antes = (
            User.objects.count(), Ticket.objects.count(), IdentidadLegacyUsuario.objects.count(),
            SegmentoSLA.objects.count(), ComentarioTicket.objects.count(),
        )

        self.ejecutar(self.datos_base())
        self.ejecutar(self.datos_base())

        self.assertEqual(
            conteos_antes,
            (
                User.objects.count(), Ticket.objects.count(), IdentidadLegacyUsuario.objects.count(),
                SegmentoSLA.objects.count(), ComentarioTicket.objects.count(),
            ),
        )

    def test_report_json_es_seguro_y_source_se_normaliza(self):
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(self.datos_base(), source=" php_mysql ", report=reporte)

        contenido = json.loads(reporte.read_text(encoding="utf-8"))
        self.assertEqual(contenido["source"], "php_mysql")
        self.assertNotIn("datos_origen", json.dumps(contenido))
        self.assertFalse(contenido["base_datos_modificada"])

    def test_ids_duplicados_se_bloquean(self):
        datos = self.datos_base()
        datos["usuarios"].append(dict(datos["usuarios"][0]))
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        usuarios = json.loads(reporte.read_text(encoding="utf-8"))["usuarios"]
        self.assertTrue(all(usuario["estado"] == EstadoAnalisisLegacy.BLOQUEADO for usuario in usuarios))
        self.assertTrue(all("LEGACY_ID_DUPLICADO" in usuario["errores"] for usuario in usuarios))

    def test_usuario_nuevo_es_dependencia_valida_de_responsable(self):
        datos = self.datos_base()
        datos["usuarios"][0].update({"id": "18", "username": "nuevo", "email": "nuevo@empresa.test"})
        datos["tickets"][0]["responsable_legacy_id"] = "18"
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertNotEqual(ticket["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertEqual(ticket["responsable_accion"], "CREAR_NUEVO")
        self.assertIsNone(ticket["responsable_django_user_id"])

    def test_usuario_nuevo_es_dependencia_valida_de_partner(self):
        datos = self.datos_base()
        datos["usuarios"].append({
            "id": "18", "username": "partner-nuevo", "email": "partner@empresa.test",
            "rol": "SOPORTE", "empresa_codigo": "BRAD",
        })
        datos["tickets"][0]["partner_legacy_id"] = "18"
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertNotEqual(ticket["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertEqual(ticket["partner_accion"], "CREAR_NUEVO")
        self.assertIsNone(ticket["partner_django_user_id"])

    def test_usuario_en_revision_propaga_revision_al_ticket(self):
        datos = self.datos_base()
        datos["usuarios"][0].update({
            "id": "18", "username": "nuevo", "email": "nuevo@empresa.test", "rol": "ROL_DESCONOCIDO",
        })
        datos["tickets"][0]["responsable_legacy_id"] = "18"
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["estado"], EstadoAnalisisLegacy.REQUIERE_REVISION)
        self.assertIn("RESPONSABLE_LEGACY_REQUIERE_REVISION", ticket["advertencias"])

    def test_usuario_bloqueado_propaga_bloqueo_al_ticket(self):
        datos = self.datos_base()
        datos["usuarios"].append(dict(datos["usuarios"][0]))
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        ticket = json.loads(reporte.read_text(encoding="utf-8"))["tickets"][0]
        self.assertEqual(ticket["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertIn("RESPONSABLE_LEGACY_BLOQUEADO", ticket["errores"])

    def test_registro_no_mapping_no_desalinea_problemas_del_siguiente(self):
        datos = self.datos_base()
        datos["usuarios"] = ["registro-invalido", {"id": ""}]
        datos["tickets"] = []
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        contenido = json.loads(reporte.read_text(encoding="utf-8"))
        self.assertIn("LEGACY_ID_FALTANTE", contenido["usuarios"][0]["errores"])
        hallazgos = [
            error for error in contenido["errores"]
            if error["codigo"] == "LEGACY_ID_FALTANTE" and error["seccion"] == "usuarios"
        ]
        self.assertEqual(hallazgos[0]["indice"], 1)

    def test_ticket_bloqueado_bloquea_comentario(self):
        datos = self.datos_base()
        datos["tickets"][0]["legacy_estado"] = "Estado desconocido"
        datos["comentarios"] = [{"id": "c-1", "ticket_legacy_id": "551", "texto": "Comentario"}]
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        comentario = json.loads(reporte.read_text(encoding="utf-8"))["comentarios"][0]
        self.assertEqual(comentario["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertIn("TICKET_LEGACY_BLOQUEADO", comentario["errores"])

    def test_ticket_en_revision_propaga_revision_a_historial(self):
        datos = self.datos_base()
        datos["tickets"][0].pop("tienda_campo")
        datos["historial"] = [{"id": "h-1", "ticket_legacy_id": "551", "evento": "ASIGNADO"}]
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        historial = json.loads(reporte.read_text(encoding="utf-8"))["historial"][0]
        self.assertEqual(historial["estado"], EstadoAnalisisLegacy.REQUIERE_REVISION)
        self.assertIn("TICKET_LEGACY_REQUIERE_REVISION", historial["advertencias"])

    def test_ticket_duplicado_bloquea_archivo_relacionado(self):
        datos = self.datos_base()
        datos["tickets"].append(dict(datos["tickets"][0]))
        datos["archivos"] = [{"id": "a-1", "ticket_legacy_id": "551", "ruta": "/legacy/a.pdf"}]
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        archivo = json.loads(reporte.read_text(encoding="utf-8"))["archivos"][0]
        self.assertEqual(archivo["estado"], EstadoAnalisisLegacy.BLOQUEADO)
        self.assertIn("TICKET_LEGACY_BLOQUEADO", archivo["errores"])

    def test_hallazgos_duplicados_conservan_indices_distintos(self):
        datos = self.datos_base()
        datos["usuarios"].append(dict(datos["usuarios"][0]))
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        contenido = json.loads(reporte.read_text(encoding="utf-8"))
        indices = {
            error["indice"] for error in contenido["errores"]
            if error["codigo"] == "LEGACY_ID_DUPLICADO"
            and error["seccion"] == "usuarios" and error["legacy_id"] == "17"
        }
        self.assertEqual(indices, {0, 1})

    def test_reporte_no_serializa_ruta_ni_url_sensible_de_archivo(self):
        datos = self.datos_base()
        datos["archivos"] = [{
            "id": "a-1",
            "ticket_legacy_id": "551",
            "ruta": "https://usuario:CLAVE@legacy/archivo.pdf?token=SECRETO",
            "existe": True,
            "tipo": "application/pdf",
            "tamano": 1234,
        }]
        reporte = Path(self.temporal.name) / "reporte.json"

        self.ejecutar(datos, report=reporte)

        contenido = reporte.read_text(encoding="utf-8")
        archivo = json.loads(contenido)["archivos"][0]
        for secreto in ("CLAVE", "SECRETO", "token=", "usuario:", "origen_declarado"):
            self.assertNotIn(secreto, contenido)
        self.assertEqual(archivo["legacy_id"], "a-1")
        self.assertEqual(archivo["ticket_legacy_id"], "551")
        self.assertTrue(archivo["existencia_declarada"])
        self.assertEqual(archivo["tipo_declarado"], "application/pdf")
        self.assertEqual(archivo["tamano_declarado"], 1234)
        self.assertNotIn("origen_declarado", archivo)

    def test_analisis_no_emite_sql_de_escritura(self):
        with CaptureQueriesContext(connection) as consultas:
            analizar_legacy(self.datos_base(), source="php_mysql")

        sql = "\n".join(consulta["sql"].upper() for consulta in consultas)
        for operacion in ("INSERT", "UPDATE", "DELETE"):
            self.assertNotIn(operacion, sql)
