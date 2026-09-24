from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from uuid import uuid4
import unicodedata


# =========================================================
# CHOICES GENERALES
# =========================================================

class EstadoTicket(models.TextChoices):
    NUEVO = "NUEVO", "Nuevo"
    ASIGNADO = "ASIGNADO", "Asignado"
    EN_PROCESO = "EN_PROCESO", "En proceso"
    EN_ESPERA = "EN_ESPERA", "En espera"
    RESUELTO = "RESUELTO", "Resuelto"
    CERRADO = "CERRADO", "Cerrado"


class OrigenTicket(models.TextChoices):
    CAROBRA = "CAROBRA", "CAROBRA"
    BRADESCARD = "BRADESCARD", "Bradescard"


class PrioridadTicket(models.TextChoices):
    BAJA = "BAJA", "Baja"
    MEDIA = "MEDIA", "Media"
    ALTA = "ALTA", "Alta"
    CRITICA = "CRITICA", "Crítica"


class EstadoImportacion(models.TextChoices):
    PROCESANDO = "PROCESANDO", "Procesando"
    COMPLETADA = "COMPLETADA", "Completada"
    ERROR = "ERROR", "Error"


class AccionImportacion(models.TextChoices):
    NUEVO = "NUEVO", "Nuevo"
    ACTUALIZADO = "ACTUALIZADO", "Actualizado"
    SIN_CAMBIOS = "SIN_CAMBIOS", "Sin cambios"
    ERROR = "ERROR", "Error"


# =========================================================
# GRUPOS DE SOPORTE
# =========================================================

class GrupoSoporte(models.Model):
    nombre = models.CharField(max_length=160, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class SubgrupoSoporte(models.Model):
    grupo = models.ForeignKey(
        GrupoSoporte,
        on_delete=models.CASCADE,
        related_name="subgrupos",
    )

    nombre = models.CharField(max_length=160)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["grupo__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["grupo", "nombre"],
                name="uq_subgrupo_grupo_nombre",
            )
        ]

    def __str__(self):
        return f"{self.grupo} / {self.nombre}"


# =========================================================
# DEPENDENCIAS Y ESTATUS OPERATIVOS
# =========================================================

class Dependencia(models.Model):
    nombre = models.CharField(max_length=160, unique=True)
    descripcion = models.TextField(blank=True)

    pausa_sla_por_defecto = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)

    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class EstatusOperativo(models.Model):
    nombre = models.CharField(max_length=160, unique=True)
    descripcion = models.TextField(blank=True)

    cuenta_como_afectacion = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)

    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


# =========================================================
# CONFIGURACIÓN SLA
# =========================================================

class ConfiguracionSLA(models.Model):
    categoria = models.CharField(max_length=180)

    incidencia_general = models.CharField(
        max_length=255,
        blank=True,
    )

    limite_minutos = models.PositiveIntegerField(
        help_text="Tiempo máximo efectivo de atención en minutos."
    )

    prioridad = models.CharField(
        max_length=20,
        choices=PrioridadTicket.choices,
        default=PrioridadTicket.MEDIA,
    )

    activo = models.BooleanField(default=True)

    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria", "incidencia_general"]
        constraints = [
            models.UniqueConstraint(
                fields=["categoria", "incidencia_general"],
                name="uq_sla_categoria_incidencia",
            )
        ]

    def __str__(self):
        if self.incidencia_general:
            return f"{self.categoria} / {self.incidencia_general}"

        return self.categoria


# =========================================================
# EMPRESAS, ZONAS, TIENDAS Y PERSONAL
# =========================================================

class Empresa(models.Model):
    codigo = models.CharField(max_length=40, unique=True, db_index=True)
    nombre = models.CharField(max_length=180, unique=True)
    descripcion = models.TextField(blank=True)
    ubicacion = models.CharField("Ubicación", max_length=255, blank=True)
    activa = models.BooleanField(default=True)
    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Persona(models.Model):
    id_personal = models.CharField(max_length=60, unique=True, db_index=True)
    nombre = models.CharField(max_length=180)
    puesto = models.CharField(max_length=140, blank=True)
    horario = models.CharField(max_length=140, blank=True)
    descanso = models.CharField("día de descanso", max_length=140, blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    correo = models.EmailField(blank=True, db_index=True)
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="persona_operativa")
    activa = models.BooleanField(default=True)
    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    @property
    def whatsapp_url(self):
        digitos = "".join(caracter for caracter in self.telefono if caracter.isdigit())
        if len(digitos) == 10:
            digitos = "52" + digitos
        return f"https://wa.me/{digitos}" if len(digitos) >= 10 else ""


class Zona(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="zonas")
    codigo = models.CharField(max_length=60)
    nombre = models.CharField(max_length=180)
    estado = models.CharField(max_length=100, db_index=True)
    encargado_zonal = models.ForeignKey(Persona, on_delete=models.SET_NULL, null=True, blank=True, related_name="zonas_encargadas")
    distrital_nombre = models.CharField("Distrital de Activos", max_length=180, blank=True)
    distrital_telefono = models.CharField("Teléfono del distrital", max_length=40, blank=True)
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="distritos_asignados")
    partner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="distritos_partner")
    activa = models.BooleanField(default=True)
    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["empresa__nombre", "estado", "nombre"]
        constraints = [models.UniqueConstraint(fields=["empresa", "codigo"], name="uq_zona_empresa_codigo")]

    def __str__(self):
        return f"{self.empresa.nombre} / {self.nombre}"


class Tienda(models.Model):
    class Cadena(models.TextChoices):
        BODEGA = "BODEGA", "Bodega"
        PROMODA = "PROMODA", "Promoda"
        GCC = "GCC", "GCC"
        OTRA = "OTRA", "Otra"

    @classmethod
    def codigo_tipo_desde_socio(cls, socio):
        """Normaliza el valor operativo importado en la columna SOCIO."""
        texto = unicodedata.normalize("NFKD", str(socio or ""))
        texto = "".join(c for c in texto if not unicodedata.combining(c)).upper()
        for codigo in (cls.Cadena.BODEGA, cls.Cadena.PROMODA, cls.Cadena.GCC):
            if codigo in texto:
                return codigo
        return cls.Cadena.OTRA

    @property
    def tipo_tienda_codigo(self):
        codigo = self.codigo_tipo_desde_socio(self.socio)
        return codigo if codigo != self.Cadena.OTRA else self.cadena

    @property
    def tipo_tienda_nombre(self):
        return dict(self.Cadena.choices).get(self.tipo_tienda_codigo, self.socio or "Otra")

    cadena = models.CharField(max_length=12, choices=Cadena.choices, default=Cadena.OTRA)
    class EstadoGeocodificacion(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        LOCALIZADA = "LOCALIZADA", "Localizada"
        ERROR = "ERROR", "No localizada"

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="tiendas")
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name="tiendas")
    codigo = models.CharField(max_length=60, blank=True, editable=False)
    id_externo = models.CharField("ID de tienda", max_length=100, blank=True, db_index=True)
    clave = models.CharField("Key", max_length=140, blank=True, db_index=True)
    numero = models.CharField(max_length=60, blank=True, db_index=True)
    nombre = models.CharField(max_length=180)
    tipo = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=100, db_index=True)
    ciudad = models.CharField("Ciudad o localidad", max_length=140, blank=True, db_index=True)
    direccion = models.TextField(blank=True)
    agencia = models.CharField(max_length=180, blank=True, db_index=True)
    socio = models.CharField(max_length=180, blank=True, db_index=True)
    gerente_distrital = models.CharField(max_length=180, blank=True, db_index=True)
    coordinador = models.CharField(max_length=180, blank=True, db_index=True)
    tipo_coordinador = models.CharField(max_length=120, blank=True)
    encargado_soporte_nombre = models.CharField(max_length=180, blank=True, db_index=True)
    partner_nombre = models.CharField(max_length=180, blank=True, db_index=True)
    lider_actual_nombre = models.CharField(max_length=180, blank=True)
    encargado_soporte = models.ForeignKey(
        Persona,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tiendas_soporte_principal",
    )
    partner = models.ForeignKey(
        Persona,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tiendas_soporte_secundario",
    )
    lider = models.ForeignKey(Persona, on_delete=models.SET_NULL, null=True, blank=True, related_name="tiendas_lideradas")
    retiro = models.BooleanField(default=False, db_index=True)
    prioridad_operativa = models.CharField(max_length=60, blank=True, db_index=True)
    piloto = models.BooleanField(default=False, db_index=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    estado_geocodificacion = models.CharField(
        max_length=20,
        choices=EstadoGeocodificacion.choices,
        default=EstadoGeocodificacion.PENDIENTE,
        db_index=True,
    )
    detalle_geocodificacion = models.CharField(max_length=255, blank=True)
    geocodificada_at = models.DateTimeField(null=True, blank=True)
    activa = models.BooleanField(default=True)
    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["empresa__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "codigo"], name="uq_tienda_empresa_codigo"),
            models.UniqueConstraint(
                fields=["empresa", "id_externo"],
                condition=~models.Q(id_externo=""),
                name="uq_tienda_empresa_id_externo",
            ),
        ]

    def save(self, *args, **kwargs):
        generar_codigo = not self.codigo
        if generar_codigo:
            self.codigo = f"TMP-{uuid4().hex.upper()}"
        super().save(*args, **kwargs)
        if generar_codigo:
            self.codigo = f"TDA-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(codigo=self.codigo)

    def __str__(self):
        return self.nombre


class AsignacionPersonal(models.Model):
    class Alcance(models.TextChoices):
        ESTADO = "ESTADO", "Estado"
        ZONA = "ZONA", "Zona"
        TIENDA = "TIENDA", "Tienda"

    class Funcion(models.TextChoices):
        COORDINADOR_ESTATAL = "COORDINADOR_ESTATAL", "Coordinador estatal"
        ENCARGADO_ZONAL = "ENCARGADO_ZONAL", "Encargado zonal"
        LIDER_TIENDA = "LIDER_TIENDA", "Líder de tienda"
        PERSONAL = "PERSONAL", "Personal"

    persona = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="asignaciones")
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="asignaciones_personal")
    alcance = models.CharField(max_length=20, choices=Alcance.choices)
    funcion = models.CharField(max_length=30, choices=Funcion.choices)
    estado = models.CharField(max_length=100, blank=True)
    zona = models.ForeignKey(Zona, on_delete=models.CASCADE, null=True, blank=True, related_name="asignaciones_personal")
    tienda = models.ForeignKey(Tienda, on_delete=models.CASCADE, null=True, blank=True, related_name="asignaciones_personal")
    incidencias = models.ManyToManyField(
        ConfiguracionSLA,
        blank=True,
        related_name="coberturas_operativas",
        help_text="Si no se selecciona ninguna, la cobertura aplica a todas las incidencias.",
    )
    horario = models.CharField(max_length=140, blank=True)
    fecha_inicio = models.DateField(default=timezone.localdate)
    fecha_fin = models.DateField(null=True, blank=True)
    principal = models.BooleanField(default=False)
    activa = models.BooleanField(default=True)
    creado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["empresa__nombre", "alcance", "persona__nombre"]

    def __str__(self):
        return f"{self.persona} · {self.get_funcion_display()}"


class GrupoTrabajo(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="grupos_trabajo")
    nombre = models.CharField(max_length=160)
    descripcion = models.TextField(blank=True)
    actividades = models.CharField(max_length=255, blank=True, help_text="Ej. inventario, reparación, atención de tickets")
    atiende_tickets = models.BooleanField(default=True)
    incidencias = models.ManyToManyField(ConfiguracionSLA, blank=True, related_name="equipos_actividad")
    lider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="grupos_liderados")
    zonas = models.ManyToManyField(Zona, blank=True, related_name="grupos_trabajo")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["empresa__nombre", "nombre"]
        constraints = [models.UniqueConstraint(fields=["empresa", "nombre"], name="uq_grupo_empresa_nombre")]

    def __str__(self):
        return f"{self.empresa.nombre} / {self.nombre}"


class MembresiaGrupo(models.Model):
    class Nivel(models.TextChoices):
        N1 = "N1", "Nivel 1"
        N2 = "N2", "Nivel 2"
        N3 = "N3", "Nivel 3"

    grupo = models.ForeignKey(GrupoTrabajo, on_delete=models.CASCADE, related_name="miembros")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membresias_grupo")
    nivel = models.CharField(max_length=2, choices=Nivel.choices, default=Nivel.N1)
    principal = models.BooleanField(default=True)
    activa = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["grupo", "usuario"], name="uq_grupo_usuario")]


class ProgramacionTrabajo(models.Model):
    class Modalidad(models.TextChoices):
        OFICINA = "OFICINA", "Oficina"
        HOME_OFFICE = "HOME_OFFICE", "Home office"
        HIBRIDO = "HIBRIDO", "Híbrido"
        AUSENTE = "AUSENTE", "Ausente"
        DESCANSO = "DESCANSO", "Descanso"
        GUARDIA = "GUARDIA", "Guardia"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="programaciones_trabajo")
    grupo = models.ForeignKey(GrupoTrabajo, on_delete=models.SET_NULL, null=True, blank=True, related_name="programaciones")
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    modalidad = models.CharField(max_length=20, choices=Modalidad.choices, default=Modalidad.OFICINA)
    notas = models.CharField(max_length=255, blank=True)
    creado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_inicio", "hora_inicio"]


# =========================================================
# IMPORTACIONES
# =========================================================

class ImportacionTickets(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, null=True, blank=True, related_name="importaciones_tickets")
    archivo = models.FileField(
        upload_to="importaciones/%Y/%m/",
        null=True,
        blank=True,
    )

    nombre_archivo = models.CharField(max_length=255)

    hash_archivo = models.CharField(
        max_length=64,
        db_index=True,
    )

    estado = models.CharField(
        max_length=20,
        choices=EstadoImportacion.choices,
        default=EstadoImportacion.PROCESANDO,
    )

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="importaciones_tickets",
    )

    total_filas = models.PositiveIntegerField(default=0)
    nuevos = models.PositiveIntegerField(default=0)
    actualizados = models.PositiveIntegerField(default=0)
    sin_cambios = models.PositiveIntegerField(default=0)
    errores = models.PositiveIntegerField(default=0)

    mensaje_error = models.TextField(blank=True)

    iniciado_at = models.DateTimeField(auto_now_add=True)
    finalizado_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-iniciado_at"]
        constraints = [models.UniqueConstraint(fields=["empresa", "hash_archivo"], name="uq_importacion_empresa_hash")]

    def __str__(self):
        return f"{self.nombre_archivo} - {self.iniciado_at:%d/%m/%Y %H:%M}"


# =========================================================
# TICKET
# =========================================================

class Ticket(models.Model):
    suplente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets_suplencia")
    suplente_hasta = models.DateTimeField(null=True, blank=True)
    solicitud_admin = models.BooleanField(default=False, db_index=True)
    motivo_admin = models.TextField(blank=True)
    motivo_espera = models.TextField(blank=True)
    esperando_a = models.CharField(max_length=255, blank=True)
    siguiente_accion = models.TextField(blank=True)
    clasificacion_manual = models.BooleanField(default=False)

    # -----------------------------------------------------
    # Identidad
    # -----------------------------------------------------

    folio = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
    )

    origen = models.CharField(
        max_length=20,
        choices=OrigenTicket.choices,
        default=OrigenTicket.CAROBRA,
        db_index=True,
    )

    ticket_bradescard = models.CharField(
        max_length=120,
        null=True,
        blank=True,
        db_index=True,
    )

    # Identificadores conservados para la futura migración del sistema legacy.
    # No sustituyen los identificadores ni el origen de los flujos actuales.
    legacy_source = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
    )

    legacy_id = models.CharField(
        max_length=120,
        null=True,
        blank=True,
        db_index=True,
    )

    legacy_estado = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, null=True, blank=True, related_name="tickets")
    tienda_registrada = models.ForeignKey(Tienda, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")

    # -----------------------------------------------------
    # DATOS IMPORTADOS DEL EXCEL
    # -----------------------------------------------------

    tienda = models.CharField(
        max_length=180,
        blank=True,
        db_index=True,
    )

    estatus_externo = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
    )

    fecha_apertura_externa = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    dias_transcurridos_externo = models.CharField(
        max_length=80,
        blank=True,
    )

    categoria = models.CharField(
        max_length=180,
        blank=True,
        db_index=True,
    )

    incidencia_general = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
    )

    incidencia_especifica = models.TextField(blank=True)

    seguimientos_externos = models.TextField(blank=True)

    fecha_reporte = models.DateField(
        null=True,
        blank=True,
    )

    hora_reporte = models.TimeField(
        null=True,
        blank=True,
    )

    ultima_modificacion_externa = models.DateTimeField(
        null=True,
        blank=True,
    )

    dias_sin_comentar_externo = models.CharField(
        max_length=80,
        blank=True,
    )

    tiempo_transcurrido_externo = models.CharField(
        max_length=120,
        blank=True,
    )

    asignado_externo = models.CharField(
        max_length=180,
        blank=True,
    )

    tipo_externo = models.CharField(
        max_length=120,
        blank=True,
    )

    usuario_externo = models.CharField(
        max_length=180,
        blank=True,
    )

    tiempo_total_externo = models.CharField(
        max_length=120,
        blank=True,
    )

    soc_externo = models.CharField(
        max_length=120,
        blank=True,
    )

    tablet_externo = models.CharField(
        max_length=120,
        blank=True,
    )

    cierre_por_falta_externo = models.CharField(
        max_length=180,
        blank=True,
    )

    # Conserva la fila original por seguridad.
    datos_origen = models.JSONField(
        default=dict,
        blank=True,
    )

    # Hash de la fila para detectar si realmente cambió.
    hash_origen = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    # -----------------------------------------------------
    # GESTIÓN INTERNA
    # -----------------------------------------------------

    estado_interno = models.CharField(
        max_length=20,
        choices=EstadoTicket.choices,
        default=EstadoTicket.NUEVO,
        db_index=True,
    )

    prioridad = models.CharField(
        max_length=20,
        choices=PrioridadTicket.choices,
        default=PrioridadTicket.MEDIA,
        db_index=True,
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_creados",
    )

    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_asignados",
    )

    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_como_partner",
    )

    grupo = models.ForeignKey(
        GrupoSoporte,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    subgrupo = models.ForeignKey(
        SubgrupoSoporte,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    dependencia_actual = models.ForeignKey(
        Dependencia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_actuales",
    )

    estatus_operativo_actual = models.ForeignKey(
        EstatusOperativo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_actuales",
    )

    # -----------------------------------------------------
    # SLA
    # -----------------------------------------------------

    configuracion_sla = models.ForeignKey(
        ConfiguracionSLA,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    # Snapshot del SLA.
    # Si la configuración cambia mañana, este ticket conserva
    # el límite con el que fue evaluado originalmente.
    sla_limite_minutos = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    sla_segundos_acumulados = models.BigIntegerField(default=0)

    # Saldo efectivo anterior al corte de migración. Los SegmentoSLA siempre
    # representan solamente el tiempo registrado por Django.
    sla_legacy_segundos = models.PositiveBigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    sla_excedido = models.BooleanField(
        default=False,
        db_index=True,
    )

    sla_excedido_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # -----------------------------------------------------
    # FECHAS INTERNAS
    # -----------------------------------------------------

    primera_importacion = models.ForeignKey(
        ImportacionTickets,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_primera_importacion",
    )

    ultima_importacion = models.ForeignKey(
        ImportacionTickets,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_ultima_importacion",
    )

    asignado_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    primer_comentario_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    resuelto_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    cerrado_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    ultima_reapertura_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    numero_reaperturas = models.PositiveIntegerField(default=0)

    creado_at = models.DateTimeField(auto_now_add=True)
    actualizado_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_at"]

        constraints = [
            models.UniqueConstraint(fields=["empresa", "ticket_bradescard"], name="uq_ticket_empresa_externo"),
            models.UniqueConstraint(
                fields=["legacy_source", "legacy_id"],
                condition=(
                    models.Q(legacy_source__isnull=False)
                    & ~models.Q(legacy_source="")
                    & models.Q(legacy_id__isnull=False)
                    & ~models.Q(legacy_id="")
                ),
                name="uq_ticket_legacy_source_id",
            ),
            models.CheckConstraint(
                condition=models.Q(sla_legacy_segundos__gte=0),
                name="ck_ticket_sla_legacy_no_negativo",
            ),
        ]

        indexes = [
            models.Index(
                fields=["estado_interno", "prioridad"],
                name="idx_ticket_estado_pri",
            ),
            models.Index(
                fields=["tienda", "estado_interno"],
                name="idx_ticket_tienda_est",
            ),
            models.Index(
                fields=["categoria", "incidencia_general"],
                name="idx_ticket_cat_inc",
            ),
            models.Index(
                fields=["responsable", "estado_interno"],
                name="idx_ticket_resp_est",
            ),
        ]

    def __str__(self):
        return f"{self.folio or 'SIN FOLIO'} - {self.ticket_bradescard or 'MANUAL'}"

    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None

        super().save(*args, **kwargs)

        if es_nuevo and not self.folio:
            anio = self.creado_at.year

            folio = f"TK-{anio}-{self.pk:06d}"

            type(self).objects.filter(pk=self.pk).update(
                folio=folio
            )

            self.folio = folio


# =========================================================
# DETALLE DE IMPORTACIÓN
# =========================================================

class DetalleImportacion(models.Model):
    importacion = models.ForeignKey(
        ImportacionTickets,
        on_delete=models.CASCADE,
        related_name="detalles",
    )

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="detalles_importacion",
    )

    fila_excel = models.PositiveIntegerField()

    ticket_bradescard = models.CharField(
        max_length=120,
        blank=True,
    )

    accion = models.CharField(
        max_length=20,
        choices=AccionImportacion.choices,
    )

    cambios = models.JSONField(
        default=dict,
        blank=True,
    )

    error = models.TextField(blank=True)

    creado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fila_excel"]


# =========================================================
# COMENTARIOS
# =========================================================

class ComentarioTicket(models.Model):

    class Tipo(models.TextChoices):
        COMENTARIO = "COMENTARIO", "Comentario"
        INTERNO = "INTERNO", "Nota interna"
        SISTEMA = "SISTEMA", "Sistema"
        CIERRE = "CIERRE", "Cierre"
        REAPERTURA = "REAPERTURA", "Reapertura"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="comentarios",
    )

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comentarios_tickets",
    )

    comentario = models.TextField()

    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.COMENTARIO,
    )

    creado_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    editado_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["creado_at"]

    def __str__(self):
        return f"{self.ticket.folio} - {self.tipo}"


# =========================================================
# ARCHIVOS / EVIDENCIAS
# =========================================================

class ArchivoTicket(models.Model):

    class Tipo(models.TextChoices):
        APERTURA = "APERTURA", "Apertura"
        COMENTARIO = "COMENTARIO", "Comentario"
        CIERRE = "CIERRE", "Cierre"
        EVIDENCIA = "EVIDENCIA", "Evidencia"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="archivos",
    )

    comentario = models.ForeignKey(
        ComentarioTicket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archivos",
    )

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archivos_tickets",
    )

    archivo = models.FileField(
        upload_to="tickets/%Y/%m/",
    )

    nombre_original = models.CharField(max_length=255)

    mime_type = models.CharField(
        max_length=160,
        blank=True,
    )

    size_bytes = models.BigIntegerField(
        null=True,
        blank=True,
    )

    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.EVIDENCIA,
    )

    creado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creado_at"]


# =========================================================
# HISTORIAL COMPLETO
# =========================================================

class HistorialTicket(models.Model):

    class Evento(models.TextChoices):
        CREADO = "CREADO", "Ticket creado"
        IMPORTADO = "IMPORTADO", "Ticket importado"
        ACTUALIZADO_IMPORTACION = (
            "ACTUALIZADO_IMPORTACION",
            "Actualizado por importación",
        )
        ASIGNADO = "ASIGNADO", "Asignado"
        PRIMER_COMENTARIO = "PRIMER_COMENTARIO", "Primer comentario"
        COMENTARIO = "COMENTARIO", "Comentario"
        ARCHIVO = "ARCHIVO", "Archivo agregado"

        ESTADO = "ESTADO", "Cambio de estado"
        PRIORIDAD = "PRIORIDAD", "Cambio de prioridad"
        PARTNER = "PARTNER", "Cambio de partner"

        GRUPO = "GRUPO", "Cambio de grupo"
        SUBGRUPO = "SUBGRUPO", "Cambio de subgrupo"

        DEPENDENCIA = "DEPENDENCIA", "Cambio de dependencia"

        ESTATUS_OPERATIVO = (
            "ESTATUS_OPERATIVO",
            "Cambio de estatus operativo",
        )
        PAUSA_SLA = "PAUSA_SLA", "Pausa SLA"
        REANUDACION_SLA = "REANUDACION_SLA", "Reanudación SLA"
        SLA_EXCEDIDO = "SLA_EXCEDIDO", "SLA excedido"
        RESUELTO = "RESUELTO", "Resuelto"
        CERRADO = "CERRADO", "Cerrado"
        REABIERTO = "REABIERTO", "Reabierto"

    class Origen(models.TextChoices):
        USUARIO = "USUARIO", "Usuario"
        SISTEMA = "SISTEMA", "Sistema"
        IMPORTACION = "IMPORTACION", "Importación"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="historial",
    )

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historial_tickets",
    )

    evento = models.CharField(
        max_length=40,
        choices=Evento.choices,
        db_index=True,
    )

    origen = models.CharField(
        max_length=20,
        choices=Origen.choices,
        default=Origen.SISTEMA,
    )

    descripcion = models.TextField(blank=True)

    valor_anterior = models.JSONField(
        default=dict,
        blank=True,
    )

    valor_nuevo = models.JSONField(
        default=dict,
        blank=True,
    )

    creado_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    class Meta:
        ordering = ["creado_at"]


# =========================================================
# SEGMENTOS DE TIEMPO SLA
# =========================================================

class SegmentoSLA(models.Model):

    class Tipo(models.TextChoices):
        ATENCION = "ATENCION", "Atención de soporte"
        PAUSA = "PAUSA", "Pausa por tercero"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="segmentos_sla",
    )

    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segmentos_sla",
    )

    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.ATENCION,
    )

    dependencia = models.ForeignKey(
        Dependencia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segmentos_sla",
    )

    estatus_operativo = models.ForeignKey(
        EstatusOperativo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segmentos_sla",
    )

    inicio = models.DateTimeField(db_index=True)

    fin = models.DateTimeField(
        null=True,
        blank=True,
    )

    cuenta_sla = models.BooleanField(default=True)

    motivo = models.TextField(blank=True)

    creado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["inicio"]
        constraints = [models.UniqueConstraint(fields=["ticket"], condition=models.Q(fin__isnull=True), name="uq_sla_segmento_abierto")]

    @property
    def duracion_segundos(self):
        fin = self.fin or timezone.now()

        return max(
            0,
            int((fin - self.inicio).total_seconds())
        )

    def __str__(self):
        return f"{self.ticket.folio} - {self.tipo}"


class SegmentoOperacion(models.Model):
    """Periodo auditable de una condición operativa de la tienda."""
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="segmentos_operacion")
    estatus_operativo = models.ForeignKey(EstatusOperativo, on_delete=models.SET_NULL, null=True, blank=True, related_name="segmentos_operacion")
    dependencia = models.ForeignKey(Dependencia, on_delete=models.SET_NULL, null=True, blank=True, related_name="segmentos_operacion")
    inicio = models.DateTimeField(db_index=True)
    fin = models.DateTimeField(null=True, blank=True)
    creado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["inicio"]
        constraints = [models.UniqueConstraint(fields=["ticket"], condition=models.Q(fin__isnull=True), name="uq_operacion_segmento_abierto")]


class EvidenciaOperativa(models.Model):
    tienda = models.ForeignKey(Tienda, on_delete=models.SET_NULL, null=True, blank=True, related_name="evidencias_operativas")
    descripcion = models.TextField()
    archivo = models.FileField(upload_to="evidencias_operativas/%Y/%m/")
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="evidencias_operativas")
    creado_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_at"]
