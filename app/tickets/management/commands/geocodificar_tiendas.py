import json
import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from tickets.models import Tienda


class Command(BaseCommand):
    help = "Localiza direcciones pendientes de tiendas y conserva sus coordenadas."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--delay", type=float, default=1.1)
        parser.add_argument("--retry-errors", action="store_true")

    def handle(self, *args, **options):
        estados = [Tienda.EstadoGeocodificacion.PENDIENTE]
        if options["retry_errors"]:
            estados.append(Tienda.EstadoGeocodificacion.ERROR)
        tiendas = (
            Tienda.objects.filter(estado_geocodificacion__in=estados)
            .exclude(direccion="")
            .filter(Q(latitud__isnull=True) | Q(longitud__isnull=True))
            .order_by("pk")[:max(options["limit"], 0)]
        )
        localizadas = errores = 0
        for indice, tienda in enumerate(tiendas):
            if indice:
                time.sleep(max(options["delay"], 1.0))
            try:
                resultado = self._buscar(tienda)
                if resultado is None:
                    raise ValueError("La dirección no produjo resultados.")
                latitud = Decimal(str(resultado["lat"]))
                longitud = Decimal(str(resultado["lon"]))
                if not (Decimal("14") <= latitud <= Decimal("33.5") and Decimal("-119") <= longitud <= Decimal("-86")):
                    raise ValueError("El resultado está fuera de México.")
                tienda.latitud = latitud
                tienda.longitud = longitud
                tienda.estado_geocodificacion = Tienda.EstadoGeocodificacion.LOCALIZADA
                tienda.detalle_geocodificacion = str(resultado.get("display_name", ""))[:255]
                tienda.geocodificada_at = timezone.now()
                tienda.save(update_fields=[
                    "latitud", "longitud", "estado_geocodificacion",
                    "detalle_geocodificacion", "geocodificada_at", "actualizado_at",
                ])
                localizadas += 1
                self.stdout.write(self.style.SUCCESS(f"{tienda.codigo}: localizada"))
            except (HTTPError, URLError, TimeoutError, ValueError, KeyError, InvalidOperation, json.JSONDecodeError) as error:
                tienda.estado_geocodificacion = Tienda.EstadoGeocodificacion.ERROR
                tienda.detalle_geocodificacion = str(error)[:255]
                tienda.geocodificada_at = timezone.now()
                tienda.save(update_fields=[
                    "estado_geocodificacion", "detalle_geocodificacion",
                    "geocodificada_at", "actualizado_at",
                ])
                errores += 1
                self.stderr.write(f"{tienda.codigo}: {error}")
        self.stdout.write(f"Proceso terminado: {localizadas} localizadas y {errores} con error.")

    def _buscar(self, tienda):
        consulta = ", ".join(
            parte for parte in (tienda.direccion, tienda.estado, "México") if parte
        )
        parametros = urlencode({
            "q": consulta,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "mx",
        })
        request = Request(
            f"{settings.GEOCODING_ENDPOINT}?{parametros}",
            headers={
                "User-Agent": settings.GEOCODING_USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "es-MX,es;q=0.9",
            },
        )
        with urlopen(request, timeout=15) as response:
            datos = json.loads(response.read().decode("utf-8"))
        return datos[0] if datos else None
