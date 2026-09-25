"""Lectura aislada del formato JSON intermedio; no conoce Django ni MySQL."""
import json
from pathlib import Path


SECCIONES_REQUERIDAS = (
    "usuarios",
    "tickets",
    "comentarios",
    "historial",
    "grupos",
    "coberturas",
)
SECCIONES_OPCIONALES = ("tiendas", "archivos")


class ErrorEntradaLegacy(ValueError):
    pass


def cargar_json_legacy(ruta):
    """Devuelve datos Python sin normalizar ni abrir rutas declaradas dentro."""
    try:
        with Path(ruta).open(encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except FileNotFoundError as error:
        raise ErrorEntradaLegacy("INPUT_NO_ENCONTRADO") from error
    except (OSError, UnicodeDecodeError) as error:
        raise ErrorEntradaLegacy("INPUT_NO_LEIBLE") from error
    except json.JSONDecodeError as error:
        raise ErrorEntradaLegacy("JSON_INVALIDO") from error
    if not isinstance(datos, dict):
        raise ErrorEntradaLegacy("ESTRUCTURA_RAIZ_INVALIDA")
    return datos
