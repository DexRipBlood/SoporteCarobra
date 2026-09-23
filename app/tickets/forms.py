from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from datetime import timedelta
from uuid import uuid4

from .models import (
    AsignacionPersonal,
    ArchivoTicket,
    ComentarioTicket,
    ConfiguracionSLA,
    Empresa,
    GrupoTrabajo,
    MembresiaGrupo,
    Persona,
    ProgramacionTrabajo,
    Ticket,
    Tienda,
    Zona,
    EstadoTicket,
    OrigenTicket,
)


User = get_user_model()


def _usuarios_operativos():
    return User.objects.filter(
        is_active=True,
        perfil__activo=True,
    ).order_by("first_name", "last_name", "username")


def _persona_para_usuario(usuario):
    """Puente temporal: la interfaz usa usuarios y conserva el modelo legado."""
    if not usuario:
        return None
    try:
        return usuario.persona_operativa
    except Persona.DoesNotExist:
        pass
    try:
        perfil = usuario.perfil
    except ObjectDoesNotExist:
        perfil = None
    nombre = usuario.get_full_name().strip() or usuario.username
    return Persona.objects.create(
        id_personal=f"USR-{usuario.pk}",
        nombre=nombre,
        puesto=getattr(perfil, "cargo", ""),
        telefono=getattr(perfil, "telefono", ""),
        correo=usuario.email,
        usuario=usuario,
        activa=True,
    )


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ["nombre", "ubicacion", "descripcion", "activa"]

    def save(self, commit=True):
        empresa = super().save(commit=False)
        if not empresa.codigo:
            empresa.codigo = f"EMP-{uuid4().hex[:12].upper()}"
        if commit:
            empresa.save()
        return empresa

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()


class ConfiguracionSLAForm(forms.ModelForm):
    class Meta:
        model = ConfiguracionSLA
        fields = [
            "categoria",
            "incidencia_general",
            "limite_minutos",
            "prioridad",
            "activo",
        ]
        labels = {
            "categoria": "Categoría",
            "incidencia_general": "Incidencia general",
            "limite_minutos": "Tiempo objetivo (minutos)",
            "prioridad": "Prioridad automática",
            "activo": "Regla activa",
        }
        help_texts = {
            "incidencia_general": (
                "Déjala vacía para usar esta regla como valor general de la categoría."
            ),
            "limite_minutos": "Ejemplos: 60 = 1 hora, 480 = 8 horas.",
        }

    def clean_categoria(self):
        return self.cleaned_data["categoria"].strip()

    def clean_incidencia_general(self):
        return self.cleaned_data["incidencia_general"].strip()

    def clean(self):
        datos = super().clean()
        categoria = datos.get("categoria")
        incidencia = datos.get("incidencia_general", "")
        if categoria:
            repetida = ConfiguracionSLA.objects.filter(
                categoria__iexact=categoria,
                incidencia_general__iexact=incidencia,
            ).exclude(pk=self.instance.pk)
            if repetida.exists():
                raise forms.ValidationError(
                    "Ya existe una regla para esta categoría e incidencia."
                )
        return datos


class ReporteIncidenciasForm(forms.Form):
    """Filtros compartidos por la vista previa y la exportación mensual."""

    PERIODO_CHOICES = (
        ("", "Rango personalizado"),
        ("semana_actual", "Esta semana"),
        ("mes_actual", "Este mes"),
    )

    periodo = forms.ChoiceField(
        label="Periodo rápido",
        choices=PERIODO_CHOICES,
        required=False,
    )
    fecha_inicio = forms.DateField(
        label="Desde",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    fecha_fin = forms.DateField(
        label="Hasta",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    tienda = forms.ModelChoiceField(queryset=Tienda.objects.none(), required=False, empty_label="Todas las tiendas")
    coordinador = forms.ModelChoiceField(queryset=User.objects.none(), required=False, empty_label="Todos los coordinadores")
    distrital = forms.ModelChoiceField(queryset=Zona.objects.none(), required=False, empty_label="Todos los distritales")
    incidencia = forms.CharField(label="Tipo de incidencia", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tienda"].queryset = Tienda.objects.filter(activa=True).order_by("nombre")
        self.fields["coordinador"].queryset = _usuarios_operativos()
        self.fields["distrital"].queryset = Zona.objects.filter(activa=True).order_by("nombre")
        if not self.is_bound:
            hoy = timezone.localdate()
            self.initial.update({"fecha_inicio": hoy.replace(day=1), "fecha_fin": hoy})

    def clean(self):
        datos = super().clean()
        hoy = timezone.localdate()
        if datos.get("periodo") == "semana_actual":
            datos["fecha_inicio"] = hoy - timedelta(days=hoy.weekday())
            datos["fecha_fin"] = datos["fecha_inicio"] + timedelta(days=6)
        elif datos.get("periodo") == "mes_actual":
            datos["fecha_inicio"] = hoy.replace(day=1)
            datos["fecha_fin"] = hoy
        if not datos.get("fecha_inicio"):
            self.add_error("fecha_inicio", "Selecciona una fecha inicial o un periodo rápido.")
        if not datos.get("fecha_fin"):
            self.add_error("fecha_fin", "Selecciona una fecha final o un periodo rápido.")
        if datos.get("fecha_inicio") and datos.get("fecha_fin") and datos["fecha_inicio"] > datos["fecha_fin"]:
            self.add_error("fecha_fin", "La fecha final debe ser igual o posterior a la inicial.")
        return datos


class PersonaForm(forms.ModelForm):
    class Meta:
        model = Persona
        fields = ["id_personal", "nombre", "puesto", "horario", "telefono", "correo", "usuario", "activa"]


class ZonaForm(forms.ModelForm):
    encargado_usuario = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Usuario encargado de la zona",
        empty_label="Sin encargado",
    )

    class Meta:
        model = Zona
        fields = ["empresa", "nombre", "estado", "distrital_nombre", "distrital_telefono", "responsable", "partner", "activa"]
        labels = {"nombre": "Distrito / zona (ej. D1)", "responsable": "Encargado de soporte"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("encargado_usuario", None)
        self.fields["responsable"].queryset = _usuarios_operativos()
        self.fields["partner"].queryset = _usuarios_operativos()

    def clean(self):
        datos = super().clean()
        if datos.get("responsable") and datos.get("responsable") == datos.get("partner"):
            self.add_error("partner", "El partner debe ser distinto del encargado.")
        if datos.get("empresa") and datos.get("nombre") and Zona.objects.filter(empresa=datos["empresa"], activa=True, nombre__iexact=datos["nombre"].strip()).exclude(pk=self.instance.pk).exists():
            self.add_error("nombre", "Ese distrito ya existe en la empresa.")
        return datos

    def save(self, commit=True):
        zona = super().save(commit=False)
        if not zona.codigo:
            zona.codigo = f"ZON-{uuid4().hex[:12].upper()}"
        if commit:
            zona.save()
        return zona


class TiendaForm(forms.ModelForm):
    socio = forms.ChoiceField(
        label="Tipo de tienda",
        choices=[
            ("Bodega", "Bodega"),
            ("Promoda", "Promoda"),
            ("GCC", "GCC"),
            ("Otra", "Otra"),
        ],
        help_text="Este valor corresponde a la columna SOCIO del catálogo de tiendas.",
    )
    responsable_usuario = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Usuario responsable de soporte",
        empty_label="Sin responsable",
    )
    partner_usuario = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Usuario partner",
        empty_label="Sin partner",
    )
    lider_usuario = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Usuario líder de tienda",
        empty_label="Sin líder",
    )

    class Meta:
        model = Tienda
        fields = [
            "empresa", "zona", "numero", "nombre", "socio",
            "estado", "ciudad", "direccion", "responsable_usuario", "partner_usuario",
            "latitud", "longitud", "activa",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        usuarios = _usuarios_operativos()
        self.fields["responsable_usuario"].help_text = "Déjalo vacío para heredar al encargado del distrito."
        self.fields["partner_usuario"].help_text = "Déjalo vacío para heredar al partner del distrito."
        self.fields["zona"].queryset = Zona.objects.filter(activa=True).select_related("empresa")
        self.fields.pop("lider_usuario", None)
        for campo in ("responsable_usuario", "partner_usuario"):
            self.fields[campo].queryset = usuarios
        if self.instance.pk:
            if self.instance.encargado_soporte_id:
                self.initial["responsable_usuario"] = self.instance.encargado_soporte.usuario_id
            if self.instance.partner_id:
                self.initial["partner_usuario"] = self.instance.partner.usuario_id
            if self.instance.lider_id:
                self.initial["lider_usuario"] = self.instance.lider.usuario_id

    def clean(self):
        datos = super().clean()
        empresa, zona = datos.get("empresa"), datos.get("zona")
        if empresa and zona and zona.empresa_id != empresa.pk:
            self.add_error("zona", "La zona no pertenece a la empresa seleccionada.")
        responsable = datos.get("responsable_usuario")
        partner = datos.get("partner_usuario")
        if responsable and partner and responsable == partner:
            self.add_error(
                "partner_usuario",
                "El partner debe ser distinto del responsable principal.",
            )
        return datos

    def save(self, commit=True):
        tienda = super().save(commit=False)
        tienda.cadena = Tienda.codigo_tipo_desde_socio(tienda.socio)
        tienda.encargado_soporte = _persona_para_usuario(
            self.cleaned_data.get("responsable_usuario")
        )
        tienda.partner = _persona_para_usuario(
            self.cleaned_data.get("partner_usuario")
        )
        if commit:
            tienda.save()
        return tienda


class AsignacionPersonalForm(forms.ModelForm):
    usuario = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Usuario",
        empty_label="Selecciona un usuario",
    )

    class Meta:
        model = AsignacionPersonal
        fields = [
            "usuario", "empresa", "alcance", "funcion", "estado", "zona",
            "tienda", "incidencias", "horario", "fecha_inicio", "fecha_fin",
            "principal", "activa",
        ]
        labels = {
            "incidencias": "Incidencias que puede atender",
        }
        help_texts = {
            "incidencias": "Sin selección significa cobertura para todas las incidencias.",
        }
        widgets = {
            "incidencias": forms.SelectMultiple(attrs={"size": 8}),
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = _usuarios_operativos()
        self.fields["incidencias"].queryset = ConfiguracionSLA.objects.filter(
            activo=True
        ).order_by("categoria", "incidencia_general")
        if self.instance.pk:
            self.initial["usuario"] = self.instance.persona.usuario_id

    def save(self, commit=True):
        asignacion = super().save(commit=False)
        asignacion.persona = _persona_para_usuario(self.cleaned_data["usuario"])
        if commit:
            asignacion.save()
            self.save_m2m()
        return asignacion

    def clean(self):
        datos = super().clean()
        empresa = datos.get("empresa")
        alcance = datos.get("alcance")
        zona = datos.get("zona")
        tienda = datos.get("tienda")
        estado = (datos.get("estado") or "").strip()
        if zona and empresa and zona.empresa_id != empresa.pk:
            self.add_error("zona", "La zona no pertenece a la empresa elegida.")
        if tienda and empresa and tienda.empresa_id != empresa.pk:
            self.add_error("tienda", "La tienda no pertenece a la empresa elegida.")
        if alcance == AsignacionPersonal.Alcance.ESTADO and not estado:
            self.add_error("estado", "Escribe el estado que cubrirá el usuario.")
        if alcance == AsignacionPersonal.Alcance.ZONA and not zona:
            self.add_error("zona", "Selecciona la zona que cubrirá el usuario.")
        if alcance == AsignacionPersonal.Alcance.TIENDA and not tienda:
            self.add_error("tienda", "Selecciona la tienda que cubrirá el usuario.")
        if datos.get("fecha_fin") and datos.get("fecha_inicio") and datos["fecha_fin"] < datos["fecha_inicio"]:
            self.add_error("fecha_fin", "La fecha final no puede ser anterior a la inicial.")
        return datos


class GrupoTrabajoForm(forms.ModelForm):
    class Meta:
        model = GrupoTrabajo
        fields = ["empresa", "nombre", "descripcion", "actividades", "atiende_tickets", "incidencias", "lider", "zonas", "activo"]

    def clean(self):
        datos = super().clean()
        empresa = datos.get("empresa")
        zonas = datos.get("zonas")
        if empresa and zonas:
            zonas_invalidas = zonas.exclude(empresa=empresa)
            if zonas_invalidas.exists():
                self.add_error(
                    "zonas",
                    "Todas las zonas deben pertenecer a la empresa del equipo.",
                )
        return datos


class MembresiaGrupoForm(forms.ModelForm):
    class Meta:
        model = MembresiaGrupo
        fields = ["grupo", "usuario", "nivel", "principal", "activa"]


class ProgramacionTrabajoForm(forms.ModelForm):
    class Meta:
        model = ProgramacionTrabajo
        fields = ["usuario", "grupo", "fecha_inicio", "fecha_fin", "hora_inicio", "hora_fin", "modalidad", "notas"]
        widgets = {"fecha_inicio": forms.DateInput(attrs={"type": "date"}), "fecha_fin": forms.DateInput(attrs={"type": "date"}), "hora_inicio": forms.TimeInput(attrs={"type": "time"}), "hora_fin": forms.TimeInput(attrs={"type": "time"})}

    def clean(self):
        datos = super().clean()
        if datos.get("grupo") and datos.get("usuario") and not datos["grupo"].miembros.filter(usuario=datos["usuario"], activa=True).exists():
            self.add_error("usuario", "El usuario debe ser integrante activo del grupo elegido.")
        if datos.get("fecha_inicio") and datos.get("fecha_fin") and datos["fecha_fin"] < datos["fecha_inicio"]:
            self.add_error("fecha_fin", "La fecha final no puede ser anterior a la inicial.")
        if datos.get("hora_inicio") and datos.get("hora_fin") and datos["hora_fin"] <= datos["hora_inicio"]:
            self.add_error("hora_fin", "La hora final debe ser posterior a la inicial.")
        campos = ("usuario", "fecha_inicio", "fecha_fin", "hora_inicio", "hora_fin")
        if all(datos.get(campo) for campo in campos):
            conflicto = ProgramacionTrabajo.objects.filter(
                usuario=datos["usuario"],
                fecha_inicio__lte=datos["fecha_fin"],
                fecha_fin__gte=datos["fecha_inicio"],
                hora_inicio__lt=datos["hora_fin"],
                hora_fin__gt=datos["hora_inicio"],
            ).exclude(pk=self.instance.pk)
            if conflicto.exists():
                raise forms.ValidationError(
                    "El usuario ya tiene una programación que se cruza con este horario."
                )
        return datos


class ImportacionCatalogoForm(forms.Form):
    TIPO_CHOICES = [
        ("TIENDAS", "Tiendas, zonas y personal"),
        ("COORDENADAS", "Actualizar coordenadas de tiendas"),
        ("USUARIOS", "Usuarios del sistema"),
        ("DIRECTORIO", "Directorio de Activos (RH)"),
    ]
    tipo = forms.ChoiceField(choices=TIPO_CHOICES)
    empresa = forms.ModelChoiceField(queryset=Empresa.objects.filter(activa=True), required=False)
    archivo = forms.FileField(widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}))

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if not archivo.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("El archivo debe tener formato .xlsx.")
        if archivo.size > 20 * 1024 * 1024:
            raise forms.ValidationError("El archivo supera el límite de 20 MB.")
        return archivo

    def clean(self):
        datos = super().clean()
        if datos.get("tipo") in {"TIENDAS", "COORDENADAS"} and not datos.get("empresa"):
            self.add_error("empresa", "Selecciona la empresa de las tiendas.")
        return datos


class CoordenadasTiendaForm(forms.Form):
    tienda = forms.ModelChoiceField(
        queryset=Tienda.objects.select_related("empresa").order_by("empresa__nombre", "nombre"),
        empty_label="Selecciona una tienda",
    )
    latitud = forms.DecimalField(max_digits=9, decimal_places=6, min_value=14, max_value=33.5)
    longitud = forms.DecimalField(max_digits=9, decimal_places=6, min_value=-119, max_value=-86)

    def clean(self):
        datos = super().clean()
        if (datos.get("latitud") is None) != (datos.get("longitud") is None):
            raise forms.ValidationError("Captura latitud y longitud juntas.")
        return datos


# =========================================================
# IMPORTACIÓN BRADESCARD
# =========================================================

class ImportacionBradescardForm(forms.Form):

    empresa = forms.ModelChoiceField(
        queryset=Empresa.objects.filter(activa=True),
        label="Empresa",
        empty_label="Selecciona una empresa",
        widget=forms.Select(attrs={"class": "ticket-control"}),
    )

    archivo = forms.FileField(
        label="Archivo de tickets",
        help_text=(
            "Selecciona la plantilla .xlsx de la empresa elegida."
        ),
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".xlsx",
                "class": "form-control",
            }
        ),
    )

    def clean_archivo(self):

        archivo = self.cleaned_data["archivo"]

        nombre = archivo.name.lower()

        if not nombre.endswith(".xlsx"):
            raise forms.ValidationError(
                "El archivo debe estar en formato Excel .xlsx."
            )

        # 20 MB máximo.
        if archivo.size > 20 * 1024 * 1024:
            raise forms.ValidationError(
                "El archivo supera el límite de 20 MB."
            )

        return archivo


# =========================================================
# RESPONSABLE CAROBRA
# =========================================================

class ResponsableChoiceField(forms.ModelChoiceField):
    """
    Muestra nombre completo + username.

    Ejemplo:
        Marco Paullini · admin

    Si el usuario no tiene nombre:
        admin
    """

    def label_from_instance(self, usuario):

        nombre = usuario.get_full_name().strip()

        if nombre:
            return f"{nombre} · {usuario.username}"

        return usuario.username


class AsignarResponsableForm(forms.Form):

    responsable = ResponsableChoiceField(
        queryset=User.objects.filter(
            is_active=True,
        ).order_by(
            "first_name",
            "last_name",
            "username",
        ),
        required=False,
        empty_label="Sin asignar",
        label="Responsable CAROBRA",
        widget=forms.Select(
            attrs={
                "class": "control",
                "id": "id_responsable",
            }
        ),
    )


class TicketCarobraForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            "tienda_registrada",
            "categoria",
            "incidencia_general",
            "incidencia_especifica",
        ]
        labels = {
            "tienda_registrada": "Empresa y tienda",
            "categoria": "Categoría",
            "incidencia_general": "Incidencia general",
            "incidencia_especifica": "Descripción detallada",
        }
        widgets = {
            "tienda_registrada": forms.Select(
                attrs={"class": "ticket-create-control"}
            ),
            "categoria": forms.TextInput(
                attrs={
                    "class": "ticket-create-control",
                    "placeholder": "Ej. Internet",
                    "list": "categorias-sla",
                }
            ),
            "incidencia_general": forms.TextInput(
                attrs={
                    "class": "ticket-create-control",
                    "placeholder": "Ej. Intermitencia",
                    "list": "incidencias-sla",
                }
            ),
            "incidencia_especifica": forms.Textarea(
                attrs={
                    "class": "ticket-create-control ticket-create-textarea",
                    "rows": 6,
                    "placeholder": (
                        "Describe qué sucede, desde cuándo y cómo afecta a la tienda."
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tienda_registrada"].queryset = (
            Tienda.objects
            .filter(activa=True, empresa__activa=True)
            .select_related("empresa", "zona")
            .order_by("empresa__nombre", "nombre")
        )
        self.fields["tienda_registrada"].empty_label = "Selecciona una tienda"

    def clean_categoria(self):
        categoria = self.cleaned_data["categoria"].strip()
        if not categoria:
            raise forms.ValidationError("Selecciona o escribe una categoría.")
        return categoria

    def clean_incidencia_general(self):
        incidencia = self.cleaned_data["incidencia_general"].strip()
        if not incidencia:
            raise forms.ValidationError("Selecciona o escribe una incidencia.")
        return incidencia

    def clean_incidencia_especifica(self):
        descripcion = self.cleaned_data["incidencia_especifica"].strip()
        if not descripcion:
            raise forms.ValidationError("Describe el problema reportado.")
        return descripcion

    def configuracion_sla(self):
        categoria = self.cleaned_data["categoria"]
        incidencia = self.cleaned_data["incidencia_general"]
        return (
            ConfiguracionSLA.objects.filter(
                activo=True,
                categoria__iexact=categoria,
                incidencia_general__iexact=incidencia,
            ).first()
            or ConfiguracionSLA.objects.filter(
                activo=True,
                categoria__iexact=categoria,
                incidencia_general="",
            ).first()
        )

    def save(self, commit=True, *, creado_por, responsable=None, partner=None):
        ticket = super().save(commit=False)
        tienda = self.cleaned_data["tienda_registrada"]
        configuracion = self.configuracion_sla()

        ticket.origen = OrigenTicket.CAROBRA
        ticket.empresa = tienda.empresa
        ticket.tienda = tienda.nombre
        ticket.creado_por = creado_por
        ticket.responsable = responsable
        ticket.partner = partner
        ticket.configuracion_sla = configuracion

        if configuracion:
            ticket.prioridad = configuracion.prioridad
            ticket.sla_limite_minutos = configuracion.limite_minutos

        if responsable:
            ticket.estado_interno = EstadoTicket.ASIGNADO

        if commit:
            ticket.save()

            from .services.operacion import iniciar_sla, seguimiento_actual
            iniciar_sla(ticket)
            ticket.solicitud_admin = seguimiento_actual(ticket)["requiere_admin"]
            if ticket.solicitud_admin:
                ticket.motivo_admin = "Revisar equipo y disponibilidad; requiere asignación administrativa."
            ticket.save(update_fields=["solicitud_admin", "motivo_admin"])

        return ticket


# =========================================================
# GESTIÓN COMPLETA DEL TICKET
# =========================================================

class GestionTicketForm(forms.ModelForm):
    """
    Formulario interno CAROBRA.

    Permite gestionar:

    - Estado
    - Prioridad
    - Responsable
    - Grupo
    - Subgrupo
    - Dependencia
    - Estatus operativo

    Los datos originales importados desde Bradescard
    NO se modifican desde este formulario.
    """

    responsable = ResponsableChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Sin asignar",
        label="Responsable CAROBRA",
        widget=forms.Select(
            attrs={
                "class": "ticket-control",
                "id": "id_gestion_responsable",
            }
        ),
    )

    partner = ResponsableChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label="Sin partner",
        label="Partner de soporte",
        widget=forms.Select(
            attrs={
                "class": "ticket-control",
                "id": "id_gestion_partner",
            }
        ),
    )

    class Meta:

        model = Ticket

        fields = [
            "estado_interno",
            "prioridad",
            "responsable",
            "partner",
            "grupo",
            "subgrupo",
            "dependencia_actual",
            "estatus_operativo_actual",
        ]

        labels = {
            "estado_interno": "Estado",
            "prioridad": "Prioridad",
            "responsable": "Responsable CAROBRA",
            "partner": "Partner de soporte",
            "grupo": "Grupo",
            "subgrupo": "Subgrupo",
            "dependencia_actual": "Dependencia",
            "estatus_operativo_actual": (
                "Estatus operativo"
            ),
        }

        widgets = {

            "estado_interno": forms.Select(
                attrs={
                    "class": "ticket-control",
                    "id": "id_estado_interno",
                }
            ),

            "prioridad": forms.Select(
                attrs={
                    "class": "ticket-control",
                    "id": "id_prioridad",
                }
            ),

            "grupo": forms.Select(
                attrs={
                    "class": "ticket-control",
                    "id": "id_grupo",
                }
            ),

            "subgrupo": forms.Select(
                attrs={
                    "class": "ticket-control",
                    "id": "id_subgrupo",
                }
            ),

            "dependencia_actual": forms.Select(
                attrs={
                    "class": "ticket-control",
                    "id": "id_dependencia_actual",
                }
            ),

            "estatus_operativo_actual": forms.Select(
                attrs={
                    "class": "ticket-control",
                    "id": "id_estatus_operativo_actual",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.estado_inicial = (
            kwargs.get("instance").estado_interno
            if kwargs.get("instance")
            else None
        )
        super().__init__(*args, **kwargs)

        if self.estado_inicial == EstadoTicket.CERRADO:
            self.fields["estado_interno"].choices = [
                (EstadoTicket.CERRADO, EstadoTicket.CERRADO.label)
            ]
        else:
            self.fields["estado_interno"].choices = [
                choice
                for choice in EstadoTicket.choices
                if choice[0] != EstadoTicket.CERRADO
            ]

        # ---------------------------------------------
        # Solo usuarios activos pueden ser responsables
        # ---------------------------------------------

        self.fields["responsable"].queryset = (
            User.objects
            .filter(
                is_active=True,
            )
            .order_by(
                "first_name",
                "last_name",
                "username",
            )
        )
        self.fields["partner"].queryset = self.fields[
            "responsable"
        ].queryset

        # ---------------------------------------------
        # Opciones vacías claras
        # ---------------------------------------------

        campos_opcionales = {
            "grupo": "Sin grupo",
            "subgrupo": "Sin subgrupo",
            "dependencia_actual": "Sin dependencia",
            "estatus_operativo_actual": "Sin definir",
        }

        for campo, etiqueta in campos_opcionales.items():

            field = self.fields.get(campo)

            if (
                field is not None
                and hasattr(field, "empty_label")
            ):
                field.empty_label = etiqueta

    def clean_estado_interno(self):
        estado = self.cleaned_data["estado_interno"]
        if estado == EstadoTicket.EN_ESPERA and self.estado_inicial != EstadoTicket.EN_ESPERA:
            raise forms.ValidationError("Registra la espera desde Seguimiento y disponibilidad, indicando tercero, motivo y siguiente acción.")

        if (
            estado == EstadoTicket.CERRADO
            and self.estado_inicial != EstadoTicket.CERRADO
        ):
            raise forms.ValidationError(
                "Utiliza la acción Cerrar ticket y adjunta comentario y evidencia."
            )

        if (
            self.estado_inicial == EstadoTicket.CERRADO
            and estado != EstadoTicket.CERRADO
        ):
            raise forms.ValidationError(
                "Utiliza la acción Reabrir ticket para registrar el motivo."
            )

        return estado

    def clean(self):
        datos = super().clean()
        categoria = (self.instance.categoria or "").casefold()
        es_red = any(texto in categoria for texto in ("internet", "red", "vpn", "sase", "fortinet", "global protect"))
        # Un ticket de conectividad no puede quedar sin condición operativa ni
        # tercero responsable: ambos datos alimentan la afectación mensual.
        if es_red and datos.get("estado_interno") not in (EstadoTicket.NUEVO, EstadoTicket.CERRADO):
            if not datos.get("estatus_operativo_actual"):
                self.add_error("estatus_operativo_actual", "En incidencias de red indica cómo opera la tienda.")
            if not datos.get("dependencia_actual"):
                self.add_error("dependencia_actual", "En incidencias de red indica la dependencia actual.")
        return datos


# =========================================================
# COMENTARIOS / SEGUIMIENTO
# =========================================================

class ComentarioTicketForm(forms.ModelForm):
    """
    Comentarios realizados manualmente por usuarios.

    SISTEMA, CIERRE y REAPERTURA se reservan
    para eventos creados desde el backend.
    """

    tipo = forms.ChoiceField(
        choices=[
            (
                ComentarioTicket.Tipo.COMENTARIO,
                "Comentario",
            ),
            (
                ComentarioTicket.Tipo.INTERNO,
                "Nota interna",
            ),
        ],
        initial=ComentarioTicket.Tipo.COMENTARIO,
        label="Tipo",
        widget=forms.Select(
            attrs={
                "class": "ticket-comment-select",
                "id": "id_tipo_comentario",
            }
        ),
    )

    class Meta:

        model = ComentarioTicket

        fields = [
            "comentario",
            "tipo",
        ]

        labels = {
            "comentario": "Comentario",
            "tipo": "Tipo",
        }

        widgets = {
            "comentario": forms.Textarea(
                attrs={
                    "class": "ticket-comment-textarea",
                    "id": "id_comentario_ticket",
                    "placeholder": (
                        "Escribe una actualización, "
                        "seguimiento o nota..."
                    ),
                    "rows": 4,
                    "maxlength": 5000,
                }
            ),
        }

    def __init__(self, *args, permitir_nota_interna=False, **kwargs):
        self.permitir_nota_interna = permitir_nota_interna
        super().__init__(*args, **kwargs)

        choices = [
            (
                ComentarioTicket.Tipo.COMENTARIO,
                "Comentario",
            ),
        ]

        if permitir_nota_interna:
            choices.append(
                (
                    ComentarioTicket.Tipo.INTERNO,
                    "Nota interna",
                )
            )

        self.fields["tipo"].choices = choices

    def clean_comentario(self):

        comentario = (
            self.cleaned_data
            .get("comentario", "")
            .strip()
        )

        if not comentario:
            raise forms.ValidationError(
                "Escribe un comentario."
            )

        if len(comentario) > 5000:
            raise forms.ValidationError(
                "El comentario no puede superar "
                "los 5,000 caracteres."
            )

        return comentario

    def clean_tipo(self):

        tipo = self.cleaned_data.get("tipo")

        permitidos = {ComentarioTicket.Tipo.COMENTARIO}

        if self.permitir_nota_interna:
            permitidos.add(ComentarioTicket.Tipo.INTERNO)

        if tipo not in permitidos:
            raise forms.ValidationError(
                "El tipo de comentario seleccionado "
                "no está permitido."
            )

        return tipo


# =========================================================
# ARCHIVOS / EVIDENCIAS
# =========================================================

class ArchivoTicketForm(forms.ModelForm):
    """
    Archivo opcional asociado a un ticket
    o a un comentario.
    """

    archivo = forms.FileField(
        required=False,
        label="Adjuntar archivo",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "ticket-file-input",
                "id": "id_archivo_ticket",
                "accept": (
                    ".jpg,.jpeg,.png,.webp,"
                    ".pdf,.xlsx,.xls,.doc,.docx,"
                    ".txt,.csv"
                ),
            }
        ),
    )

    class Meta:

        model = ArchivoTicket

        fields = [
            "archivo",
        ]

    def clean_archivo(self):

        archivo = self.cleaned_data.get(
            "archivo"
        )

        if not archivo:
            return archivo

        # ---------------------------------------------
        # Máximo 15 MB
        # ---------------------------------------------

        limite = 15 * 1024 * 1024

        if archivo.size > limite:
            raise forms.ValidationError(
                "El archivo supera el límite "
                "de 15 MB."
            )

        # ---------------------------------------------
        # Extensiones permitidas
        # ---------------------------------------------

        extensiones_permitidas = {
            "jpg",
            "jpeg",
            "png",
            "webp",
            "pdf",
            "xlsx",
            "xls",
            "doc",
            "docx",
            "txt",
            "csv",
        }

        nombre = archivo.name.lower().strip()

        if "." not in nombre:
            raise forms.ValidationError(
                "El archivo no tiene una "
                "extensión válida."
            )

        extension = (
            nombre
            .rsplit(".", 1)[-1]
            .strip()
        )

        if extension not in extensiones_permitidas:
            raise forms.ValidationError(
                "Ese tipo de archivo no está permitido."
            )

        return archivo


class CerrarTicketForm(forms.Form):
    comentario_cierre = forms.CharField(
        label="Comentario de cierre",
        max_length=5000,
        widget=forms.Textarea(
            attrs={
                "class": "ticket-comment-textarea",
                "rows": 4,
                "placeholder": (
                    "Describe la solución aplicada y el resultado final..."
                ),
            }
        ),
    )
    evidencia_cierre = forms.FileField(
        label="Evidencia de cierre",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "ticket-file-input",
                "accept": (
                    ".jpg,.jpeg,.png,.webp,"
                    ".pdf,.xlsx,.xls,.doc,.docx,.txt,.csv"
                ),
            }
        ),
    )

    def clean_comentario_cierre(self):
        comentario = self.cleaned_data["comentario_cierre"].strip()
        if not comentario:
            raise forms.ValidationError(
                "Escribe el comentario que justifica el cierre."
            )
        return comentario

    def clean_evidencia_cierre(self):
        archivo = self.cleaned_data["evidencia_cierre"]
        validador = ArchivoTicketForm(files={"archivo": archivo})
        if not validador.is_valid():
            raise forms.ValidationError(
                validador.errors["archivo"].as_text().replace("* ", "")
            )
        return archivo


class ReabrirTicketForm(forms.Form):
    motivo_reapertura = forms.CharField(
        label="Motivo de reapertura",
        max_length=5000,
        widget=forms.Textarea(
            attrs={
                "class": "ticket-comment-textarea",
                "rows": 3,
                "placeholder": "Explica por qué el ticket debe volver a atención...",
            }
        ),
    )

    def clean_motivo_reapertura(self):
        motivo = self.cleaned_data["motivo_reapertura"].strip()
        if not motivo:
            raise forms.ValidationError(
                "Escribe el motivo de la reapertura."
            )
        return motivo
