import json
import gzip
import shutil
from math import hypot
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def simplificar_anillo(anillo, tolerancia):
    if len(anillo) <= 4:
        return anillo
    primero = anillo[0]
    puntos = [primero]
    ultimo = primero
    for punto in anillo[1:-1]:
        if hypot(punto[0] - ultimo[0], punto[1] - ultimo[1]) >= tolerancia:
            puntos.append(punto)
            ultimo = punto
    if len(puntos) < 3:
        puntos = [anillo[0], anillo[len(anillo) // 3], anillo[(len(anillo) * 2) // 3]]
    puntos.append(puntos[0])
    return puntos


def orientar(anillo, horario=False):
    area = sum(
        (anillo[i + 1][0] - anillo[i][0])
        * (anillo[i + 1][1] + anillo[i][1])
        for i in range(len(anillo) - 1)
    )
    es_horario = area > 0
    return list(reversed(anillo)) if es_horario != horario else anillo


class Command(BaseCommand):
    help = "Simplifica el límite oficial de INEGI y genera la máscara del mapa de México."

    def add_arguments(self, parser):
        parser.add_argument("--origen", default=str(Path(settings.MEDIA_ROOT) / "mapas" / "mexico-estados.geojson"))
        parser.add_argument("--tolerancia", type=float, default=0.001)

    def handle(self, *args, **options):
        origen = Path(options["origen"])
        if not origen.exists():
            raise CommandError(f"No existe el archivo de INEGI: {origen}")

        with origen.open(encoding="utf-8") as archivo:
            datos = json.load(archivo)

        entidades = []
        huecos_mexico = []
        for feature in datos.get("features", []):
            geometria = feature.get("geometry") or {}
            if geometria.get("type") == "Polygon":
                poligonos = [geometria.get("coordinates", [])]
            elif geometria.get("type") == "MultiPolygon":
                poligonos = geometria.get("coordinates", [])
            else:
                continue

            salida_poligonos = []
            for poligono in poligonos:
                if not poligono:
                    continue
                anillos = [
                    simplificar_anillo(anillo, options["tolerancia"])
                    for anillo in poligono
                    if len(anillo) >= 4
                ]
                if anillos:
                    salida_poligonos.append(anillos)
                    huecos_mexico.append(orientar(anillos[0], horario=True))

            entidades.append({
                "type": "Feature",
                "properties": {
                    "clave": feature.get("properties", {}).get("cve_ent", ""),
                    "nombre": feature.get("properties", {}).get("nomgeo", ""),
                },
                "geometry": {"type": "MultiPolygon", "coordinates": salida_poligonos},
            })

        destino = origen.parent
        estados = destino / "mexico-estados-simplificado.geojson"
        mascara = destino / "mexico-mask.geojson"
        limite = destino / "mexico-limite.geojson"
        huecos_mascara = huecos_mexico
        if limite.exists():
            with limite.open(encoding="utf-8") as archivo:
                nacional = json.load(archivo)
            if nacional.get("type") == "GeometryCollection":
                geometrias = nacional.get("geometries", [])
            elif nacional.get("type") == "FeatureCollection":
                geometrias = [item.get("geometry", {}) for item in nacional.get("features", [])]
            elif nacional.get("type") == "Feature":
                geometrias = [nacional.get("geometry", {})]
            else:
                geometrias = [nacional]
            huecos_mascara = []
            for geometria in geometrias:
                if geometria.get("type") == "Polygon":
                    poligonos = [geometria.get("coordinates", [])]
                elif geometria.get("type") == "MultiPolygon":
                    poligonos = geometria.get("coordinates", [])
                else:
                    continue
                huecos_mascara.extend(
                    orientar(poligono[0], horario=True)
                    for poligono in poligonos
                    if poligono
                )
        mundo = orientar([
            [-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]
        ], horario=False)

        with estados.open("w", encoding="utf-8") as archivo:
            json.dump({"type": "FeatureCollection", "features": entidades}, archivo, separators=(",", ":"))
        with mascara.open("w", encoding="utf-8") as archivo:
            json.dump({
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [mundo, *huecos_mascara]},
            }, archivo, separators=(",", ":"))
        with mascara.open("rb") as origen_mascara, gzip.open(
            f"{mascara}.gz", "wb", compresslevel=9
        ) as archivo_comprimido:
            shutil.copyfileobj(origen_mascara, archivo_comprimido)

        self.stdout.write(self.style.SUCCESS(
            f"Generados {estados.name} y {mascara.name} con {len(entidades)} entidades."
        ))
