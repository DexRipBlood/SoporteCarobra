from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class PendienteQuerySet(models.QuerySet):
    def abiertos(self):
        return self.exclude(estado__in=Pendiente.ESTADOS_TERMINALES)

    def vencidos(self):
        return self.abiertos().filter(fecha_compromiso__lt=timezone.localdate())


class Pendiente(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        EN_CURSO = "EN_CURSO", "En curso"
        EN_ESPERA = "EN_ESPERA", "En espera"
        COMPLETADO = "COMPLETADO", "Completado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Prioridad(models.TextChoices):
        CRITICA = "CRITICA", "Crítica"
        ALTA = "ALTA", "Alta"
        MEDIA = "MEDIA", "Media"
        BAJA = "BAJA", "Baja"

    class Categoria(models.TextChoices):
        INCIDENCIA = "INCIDENCIA", "Incidencia"
        SOLICITUD = "SOLICITUD", "Solicitud"
        MEJORA = "MEJORA", "Mejora"
        TAREA = "TAREA", "Tarea"

    class TipoTrabajo(models.TextChoices):
        GESTION = "GESTION", "Gestión"
        PROYECTO = "PROYECTO", "Proyecto"
        RECURRENTE = "RECURRENTE", "Recurrente"
        SOPORTE = "SOPORTE", "Soporte"

    class Bloqueo(models.TextChoices):
        SIN_BLOQUEO = "SIN_BLOQUEO", "Sin bloqueo"
        PERSONA = "PERSONA", "Persona"
        AREA = "AREA", "Área"
        BRADESCARD = "BRADESCARD", "Bradescard"
        FINANZAS = "FINANZAS", "Finanzas"
        VALIDACION = "VALIDACION", "Validación"
        OTRO = "OTRO", "Otro"

    class Frecuencia(models.TextChoices):
        UNICA = "UNICA", "Única"
        DIARIA = "DIARIA", "Diaria"
        SEMANAL = "SEMANAL", "Semanal"
        QUINCENAL = "QUINCENAL", "Quincenal"
        MENSUAL = "MENSUAL", "Mensual"

    class Area(models.TextChoices):
        COMERCIAL = "COMERCIAL", "Comercial"
        MESA_DE_CONTROL = "MESA_DE_CONTROL", "Mesa de control"
        FINANZAS = "FINANZAS", "Finanzas"
        BRADESCARD = "BRADESCARD", "Bradescard"
        DIRECCION = "DIRECCION", "Dirección"
        SOPORTE = "SOPORTE", "Soporte"
        RH = "RH", "Recursos humanos"
        SISTEMAS = "SISTEMAS", "Sistemas"

    class Canal(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        JUNTA = "JUNTA", "Junta"
        MEET = "MEET", "Meet"
        LLAMADA = "LLAMADA", "Llamada"
        COMUNICADO = "COMUNICADO", "Comunicado"
        SISTEMA = "SISTEMA", "Sistema"
        REVISION_SHEET = "REVISION_SHEET", "Revisión de hoja"
        OTRO = "OTRO", "Otro"

    ESTADOS_TERMINALES = (Estado.COMPLETADO, Estado.CANCELADO)
    folio = models.CharField(max_length=40, unique=True, editable=False)
    titulo = models.CharField("tarea", max_length=240)
    detalle = models.TextField(blank=True)
    area = models.CharField("área", max_length=30, choices=Area.choices, default=Area.SISTEMAS)
    tda = models.ForeignKey("tickets.Tienda", verbose_name="TDA", on_delete=models.PROTECT,
                            null=True, blank=True, related_name="pendientes")
    categoria = models.CharField("categoría", max_length=20, choices=Categoria.choices, default=Categoria.TAREA)
    tipo_trabajo = models.CharField("tipo de trabajo", max_length=20, choices=TipoTrabajo.choices, default=TipoTrabajo.GESTION)
    prioridad = models.CharField(max_length=10, choices=Prioridad.choices, default=Prioridad.MEDIA, db_index=True)
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="pendientes_asignados")
    solicitante = models.CharField(max_length=200, blank=True)
    canal = models.CharField(max_length=20, choices=Canal.choices, default=Canal.SISTEMA)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    bloqueo = models.CharField(max_length=20, choices=Bloqueo.choices, default=Bloqueo.SIN_BLOQUEO)
    bloqueado_por = models.CharField("bloqueado por / explicación", max_length=255, blank=True)
    siguiente_accion = models.TextField("siguiente acción", blank=True)
    fecha_compromiso = models.DateField("fecha de compromiso", null=True, blank=True, db_index=True)
    fecha_atencion_inicial = models.DateTimeField(null=True, blank=True, editable=False)
    fecha_cierre = models.DateTimeField(null=True, blank=True, editable=False)
    frecuencia = models.CharField(max_length=15, choices=Frecuencia.choices, default=Frecuencia.UNICA)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pendientes_creados", editable=False)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    ultima_actualizacion = models.DateTimeField(auto_now=True)

    objects = PendienteQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha_creacion", "-pk"]
        verbose_name = "pendiente"
        verbose_name_plural = "pendientes"
        # La baja normal es cancelación; no se concede borrado desde la interfaz.
        default_permissions = ("add", "change", "view")
        indexes = [models.Index(fields=["estado", "fecha_compromiso"], name="gestor_estado_compromiso")]

    def __str__(self):
        return f"{self.folio} · {self.titulo}"

    def save(self, *args, **kwargs):
        if self._state.adding:
            # La secuencia de la PK evita colisiones entre creaciones concurrentes.
            self.folio = f"TMP-{uuid4().hex}"
            with transaction.atomic():
                super().save(*args, **kwargs)
                self.folio = f"GST-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(folio=self.folio)
        else:
            super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.titulo.strip():
            raise ValidationError({"titulo": "Escribe el título de la tarea."})
        if self.estado == self.Estado.EN_ESPERA:
            errores = {}
            if self.bloqueo == self.Bloqueo.SIN_BLOQUEO:
                errores["bloqueo"] = "Selecciona el motivo del bloqueo."
            if not self.bloqueado_por.strip():
                errores["bloqueado_por"] = "Indica a quién esperas o explica el bloqueo."
            if not self.siguiente_accion.strip():
                errores["siguiente_accion"] = "Indica la siguiente acción."
            if errores:
                raise ValidationError(errores)

    @property
    def abierto(self):
        return self.estado not in self.ESTADOS_TERMINALES

    @property
    def vencido(self):
        return bool(self.abierto and self.fecha_compromiso and self.fecha_compromiso < timezone.localdate())

    @property
    def dias_atraso(self):
        return (timezone.localdate() - self.fecha_compromiso).days if self.vencido else 0

    @property
    def tiempo_abierto(self):
        fin = self.fecha_cierre if self.estado == self.Estado.COMPLETADO and self.fecha_cierre else timezone.now()
        return fin - self.fecha_creacion

    @property
    def tiempo_atencion_inicial(self):
        return self.fecha_atencion_inicial - self.fecha_creacion if self.fecha_atencion_inicial else None

    @property
    def tiempo_resolucion(self):
        return self.fecha_cierre - self.fecha_creacion if self.fecha_cierre else None

    @property
    def recomendaciones(self):
        if self.estado != self.Estado.EN_CURSO:
            return []
        return [etiqueta for falta, etiqueta in (
            (not self.responsable_id, "Asigna un responsable."),
            (not self.fecha_compromiso, "Define una fecha de compromiso."),
            (not self.siguiente_accion.strip(), "Define la siguiente acción."),
        ) if falta]

    @property
    def semaforo(self):
        if not self.abierto:
            return "GRIS"
        if self.vencido:
            return "ROJO"
        if (self.fecha_compromiso and self.fecha_compromiso <= timezone.localdate() + timedelta(days=2)) or (
            self.prioridad == self.Prioridad.CRITICA or self.estado == self.Estado.EN_ESPERA or self.recomendaciones
        ):
            return "AMARILLO"
        return "VERDE"


class PendienteHistorial(models.Model):
    class Evento(models.TextChoices):
        CREACION = "CREACION", "Creación"
        ESTADO = "ESTADO", "Cambio de estado"
        RESPONSABLE = "RESPONSABLE", "Cambio de responsable"
        COMPROMISO = "COMPROMISO", "Cambio de compromiso"
        PRIORIDAD = "PRIORIDAD", "Cambio de prioridad"
        BLOQUEO = "BLOQUEO", "Cambio de bloqueo"
        SIGUIENTE_ACCION = "SIGUIENTE_ACCION", "Cambio de siguiente acción"
        CIERRE = "CIERRE", "Cierre"
        REAPERTURA = "REAPERTURA", "Reapertura"
        CANCELACION = "CANCELACION", "Cancelación"
        EDICION = "EDICION", "Edición"
        COMENTARIO = "COMENTARIO", "Comentario"

    pendiente = models.ForeignKey(Pendiente, on_delete=models.PROTECT, related_name="historial")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now, editable=False)
    tipo_evento = models.CharField(max_length=30, choices=Evento.choices)
    valor_anterior = models.TextField(blank=True)
    valor_nuevo = models.TextField(blank=True)
    comentario = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha", "-pk"]
        default_permissions = ("view",)
        verbose_name = "historial de pendiente"
        verbose_name_plural = "historial de pendientes"

