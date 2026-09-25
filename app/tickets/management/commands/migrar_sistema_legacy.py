"""Previsualización de migración legacy; no contiene ruta de escritura."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tickets.services.legacy_import.analizador import analizar_legacy
from tickets.services.legacy_import.lector import ErrorEntradaLegacy, cargar_json_legacy


class Command(BaseCommand):
    help = "Analiza una exportación legacy JSON sin modificar PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Obligatorio: sólo analiza.")
        parser.add_argument("--source", required=True, help="Origen único de toda la ejecución.")
        parser.add_argument("--input", required=True, help="Ruta al JSON intermedio de pruebas.")
        parser.add_argument("--report", help="Ruta opcional para guardar el reporte seguro JSON.")

    def handle(self, *args, **options):
        if not options["dry_run"]:
            raise CommandError(
                "El modo escritura todavía no está implementado; ejecute con --dry-run."
            )
        source = str(options["source"] or "").strip()
        if not source:
            raise CommandError("--source no puede estar vacío.")
        try:
            datos = cargar_json_legacy(options["input"])
        except ErrorEntradaLegacy as error:
            raise CommandError(str(error)) from error
        try:
            reporte = analizar_legacy(datos, source=source)
        except ValueError as error:
            raise CommandError(str(error)) from error

        if options.get("report"):
            try:
                Path(options["report"]).write_text(
                    json.dumps(reporte.como_dict(), ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
            except OSError as error:
                raise CommandError("REPORT_NO_ESCRIBIBLE") from error
        self._imprimir_resumen(reporte)

    def _imprimir_resumen(self, reporte):
        resumen = reporte.resumen
        self.stdout.write("=================================")
        self.stdout.write("MIGRACIÓN LEGACY — DRY RUN")
        self.stdout.write("=================================")
        self.stdout.write("")
        self.stdout.write(f"Usuarios analizados:             {resumen.usuarios_analizados}")
        self.stdout.write(f"  Match existentes:              {resumen.usuarios_match_existente}")
        self.stdout.write(f"  Nuevos propuestos:             {resumen.usuarios_nuevos_propuestos}")
        self.stdout.write(f"  Revisión:                      {resumen.usuarios_revision}")
        self.stdout.write(f"  Conflictos:                    {resumen.usuarios_conflicto}")
        self.stdout.write("")
        self.stdout.write(f"Tickets analizados:              {resumen.tickets_analizados}")
        self.stdout.write(f"  Listos para migrar:            {resumen.tickets_listos}")
        self.stdout.write(f"  Revisión:                      {resumen.tickets_revision}")
        self.stdout.write(f"  Bloqueados:                    {resumen.tickets_bloqueados}")
        self.stdout.write("")
        self.stdout.write(f"Comentarios:                     {resumen.comentarios_analizados}")
        self.stdout.write(f"Historial:                       {resumen.historial_analizado}")
        self.stdout.write(f"Archivos:                        {resumen.archivos_analizados}")
        self.stdout.write("")
        self.stdout.write(f"ERRORES:                         {resumen.errores}")
        self.stdout.write(f"ADVERTENCIAS:                    {resumen.advertencias}")
        self.stdout.write("")
        self.stdout.write("Base de datos modificada: NO")
        self.stdout.write("=================================")
