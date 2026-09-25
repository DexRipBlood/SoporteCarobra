"""Tipos auditables y serializables del análisis de importación legacy."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional


class EstadoAnalisisLegacy(StrEnum):
    LISTO_PARA_MIGRAR = "LISTO_PARA_MIGRAR"
    REQUIERE_REVISION = "REQUIERE_REVISION"
    BLOQUEADO = "BLOQUEADO"


class DisponibilidadSLALegacy(StrEnum):
    EXACTO = "EXACTO"
    RECONSTRUIBLE = "RECONSTRUIBLE"
    NO_DISPONIBLE = "NO_DISPONIBLE"
    AMBIGUO = "AMBIGUO"


@dataclass(frozen=True)
class HallazgoLegacy:
    codigo: str
    seccion: str
    legacy_id: str = ""
    indice: Optional[int] = None


@dataclass(frozen=True)
class ResultadoUsuarioLegacy:
    legacy_id: str
    accion: str
    estado: EstadoAnalisisLegacy
    django_user_id: Optional[int] = None
    advertencias: tuple[str, ...] = ()
    errores: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultadoTicketLegacy:
    legacy_id: str
    estado: EstadoAnalisisLegacy
    estado_original: str = ""
    estado_destino: Optional[str] = None
    responsable_legacy_id: str = ""
    responsable_django_user_id: Optional[int] = None
    responsable_accion: Optional[str] = None
    partner_legacy_id: str = ""
    partner_django_user_id: Optional[int] = None
    partner_accion: Optional[str] = None
    empresa_django_id: Optional[int] = None
    tienda_django_id: Optional[int] = None
    sla_disponibilidad: DisponibilidadSLALegacy = DisponibilidadSLALegacy.NO_DISPONIBLE
    sla_legacy_segundos: Optional[int] = None
    advertencias: tuple[str, ...] = ()
    errores: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultadoRelacionadoLegacy:
    seccion: str
    legacy_id: str
    ticket_legacy_id: str
    estado: EstadoAnalisisLegacy
    advertencias: tuple[str, ...] = ()
    errores: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultadoArchivoLegacy:
    legacy_id: str
    ticket_legacy_id: str
    estado: EstadoAnalisisLegacy
    origen_declarado: str = ""
    existencia_declarada: Optional[bool] = None
    tipo_declarado: str = ""
    tamano_declarado: Optional[int] = None
    advertencias: tuple[str, ...] = ()
    errores: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumenAnalisisLegacy:
    usuarios_analizados: int = 0
    usuarios_match_existente: int = 0
    usuarios_nuevos_propuestos: int = 0
    usuarios_revision: int = 0
    usuarios_conflicto: int = 0
    tickets_analizados: int = 0
    tickets_listos: int = 0
    tickets_revision: int = 0
    tickets_bloqueados: int = 0
    comentarios_analizados: int = 0
    historial_analizado: int = 0
    archivos_analizados: int = 0
    errores: int = 0
    advertencias: int = 0


@dataclass(frozen=True)
class ReporteAnalisisLegacy:
    source: str
    dry_run: bool
    base_datos_modificada: bool
    resumen: ResumenAnalisisLegacy
    usuarios: tuple[ResultadoUsuarioLegacy, ...] = ()
    tickets: tuple[ResultadoTicketLegacy, ...] = ()
    comentarios: tuple[ResultadoRelacionadoLegacy, ...] = ()
    historial: tuple[ResultadoRelacionadoLegacy, ...] = ()
    archivos: tuple[ResultadoArchivoLegacy, ...] = ()
    errores: tuple[HallazgoLegacy, ...] = ()
    advertencias: tuple[HallazgoLegacy, ...] = ()

    def como_dict(self) -> dict[str, Any]:
        """Construye la representación pública mediante allowlist explícita."""
        def lista(valores):
            return list(valores)

        def estado(valor):
            return valor.value if isinstance(valor, StrEnum) else valor

        def usuario(resultado):
            return {
                "legacy_id": resultado.legacy_id,
                "accion": resultado.accion,
                "estado": estado(resultado.estado),
                "django_user_id": resultado.django_user_id,
                "advertencias": lista(resultado.advertencias),
                "errores": lista(resultado.errores),
            }

        def ticket(resultado):
            return {
                "legacy_id": resultado.legacy_id,
                "estado": estado(resultado.estado),
                "estado_original": resultado.estado_original,
                "estado_destino": resultado.estado_destino,
                "responsable_legacy_id": resultado.responsable_legacy_id,
                "responsable_django_user_id": resultado.responsable_django_user_id,
                "responsable_accion": resultado.responsable_accion,
                "partner_legacy_id": resultado.partner_legacy_id,
                "partner_django_user_id": resultado.partner_django_user_id,
                "partner_accion": resultado.partner_accion,
                "empresa_django_id": resultado.empresa_django_id,
                "tienda_django_id": resultado.tienda_django_id,
                "sla_disponibilidad": estado(resultado.sla_disponibilidad),
                "sla_legacy_segundos": resultado.sla_legacy_segundos,
                "advertencias": lista(resultado.advertencias),
                "errores": lista(resultado.errores),
            }

        def relacionado(resultado):
            return {
                "seccion": resultado.seccion,
                "legacy_id": resultado.legacy_id,
                "ticket_legacy_id": resultado.ticket_legacy_id,
                "estado": estado(resultado.estado),
                "advertencias": lista(resultado.advertencias),
                "errores": lista(resultado.errores),
            }

        def archivo(resultado):
            return {
                "legacy_id": resultado.legacy_id,
                "ticket_legacy_id": resultado.ticket_legacy_id,
                "estado": estado(resultado.estado),
                "existencia_declarada": resultado.existencia_declarada,
                "tipo_declarado": resultado.tipo_declarado,
                "tamano_declarado": resultado.tamano_declarado,
                "advertencias": lista(resultado.advertencias),
                "errores": lista(resultado.errores),
            }

        def hallazgo(resultado):
            return {
                "codigo": resultado.codigo,
                "seccion": resultado.seccion,
                "legacy_id": resultado.legacy_id,
                "indice": resultado.indice,
            }

        resumen = self.resumen
        return {
            "source": self.source,
            "dry_run": self.dry_run,
            "base_datos_modificada": self.base_datos_modificada,
            "resumen": {
                "usuarios_analizados": resumen.usuarios_analizados,
                "usuarios_match_existente": resumen.usuarios_match_existente,
                "usuarios_nuevos_propuestos": resumen.usuarios_nuevos_propuestos,
                "usuarios_revision": resumen.usuarios_revision,
                "usuarios_conflicto": resumen.usuarios_conflicto,
                "tickets_analizados": resumen.tickets_analizados,
                "tickets_listos": resumen.tickets_listos,
                "tickets_revision": resumen.tickets_revision,
                "tickets_bloqueados": resumen.tickets_bloqueados,
                "comentarios_analizados": resumen.comentarios_analizados,
                "historial_analizado": resumen.historial_analizado,
                "archivos_analizados": resumen.archivos_analizados,
                "errores": resumen.errores,
                "advertencias": resumen.advertencias,
            },
            "usuarios": [usuario(resultado) for resultado in self.usuarios],
            "tickets": [ticket(resultado) for resultado in self.tickets],
            "comentarios": [relacionado(resultado) for resultado in self.comentarios],
            "historial": [relacionado(resultado) for resultado in self.historial],
            "archivos": [archivo(resultado) for resultado in self.archivos],
            "errores": [hallazgo(resultado) for resultado in self.errores],
            "advertencias": [hallazgo(resultado) for resultado in self.advertencias],
        }
