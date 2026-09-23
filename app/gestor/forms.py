from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from tickets.models import Tienda

from .models import Pendiente
from .services import CAMPOS_EDITABLES


class UsuarioChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, usuario):
        return usuario.get_full_name() or usuario.username


class TiendaChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, tienda):
        return f"{tienda.nombre} · {tienda.empresa.nombre}"


def usuarios_activos():
    return get_user_model().objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(perfil__activo=True)
    ).order_by("first_name", "last_name", "username")


class PendienteForm(forms.ModelForm):
    responsable = UsuarioChoiceField(queryset=get_user_model().objects.none(), required=False, empty_label="Sin responsable")
    tda = TiendaChoiceField(queryset=Tienda.objects.none(), required=False, label="TDA", empty_label="Sin tienda / actividad general")
    version = forms.DateTimeField(widget=forms.HiddenInput, required=False)
    comentario = forms.CharField(label="Comentario para el historial", required=False,
                                widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = Pendiente
        fields = list(CAMPOS_EDITABLES)
        widgets = {
            "detalle": forms.Textarea(attrs={"rows": 4}),
            "siguiente_accion": forms.Textarea(attrs={"rows": 2}),
            "fecha_compromiso": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        usuarios = usuarios_activos()
        tiendas = Tienda.objects.filter(activa=True)
        if self.instance.pk:
            # Se puede conservar al responsable o tienda actuales aunque sean desactivados.
            usuarios = get_user_model().objects.filter(Q(pk__in=usuarios) | Q(pk=self.instance.responsable_id))
            tiendas = Tienda.objects.filter(Q(activa=True) | Q(pk=self.instance.tda_id))
            self.fields["version"].required = True
            self.initial["version"] = self.instance.ultima_actualizacion.isoformat()
        else:
            for campo in ("estado", "bloqueo", "bloqueado_por", "frecuencia", "comentario", "version"):
                self.fields.pop(campo)
        self.fields["responsable"].queryset = usuarios.order_by("first_name", "username")
        self.fields["tda"].queryset = tiendas.select_related("empresa").order_by("nombre")
        self.fields["solicitante"].help_text = "Nombre de quien solicita; puede ser una persona externa."
        if "frecuencia" in self.fields:
            self.fields["frecuencia"].help_text = "Referencia de periodicidad; todavía no genera copias automáticas."
        self.fields["fecha_compromiso"].help_text = "Se considera vencido al día siguiente, según la hora de Ciudad de México."


class FiltrosPendienteForm(forms.Form):
    q = forms.CharField(label="Buscar", required=False, max_length=200,
                        widget=forms.TextInput(attrs={"placeholder": "Folio, tarea, detalle o persona que bloquea…"}))
    estado = forms.ChoiceField(choices=[("", "Todos los estados"), *Pendiente.Estado.choices], required=False)
    responsable = UsuarioChoiceField(queryset=get_user_model().objects.none(), required=False, empty_label="Todos los responsables")
    area = forms.ChoiceField(label="Área", choices=[("", "Todas las áreas"), *Pendiente.Area.choices], required=False)
    prioridad = forms.ChoiceField(choices=[("", "Todas las prioridades"), *Pendiente.Prioridad.choices], required=False)
    categoria = forms.ChoiceField(label="Categoría", choices=[("", "Todas las categorías"), *Pendiente.Categoria.choices], required=False)
    bloqueo = forms.ChoiceField(choices=[("", "Todos los bloqueos"), *Pendiente.Bloqueo.choices], required=False)
    tipo_trabajo = forms.ChoiceField(label="Tipo de trabajo", choices=[("", "Todos los tipos"), *Pendiente.TipoTrabajo.choices], required=False)
    frecuencia = forms.ChoiceField(choices=[("", "Todas las frecuencias"), *Pendiente.Frecuencia.choices], required=False)
    tda = TiendaChoiceField(queryset=Tienda.objects.none(), label="TDA", required=False, empty_label="Todas las tiendas")
    fecha_desde = forms.DateField(label="Compromiso desde", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    fecha_hasta = forms.DateField(label="Compromiso hasta", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsable"].queryset = get_user_model().objects.order_by("first_name", "username")
        self.fields["tda"].queryset = Tienda.objects.select_related("empresa").order_by("nombre")

    def clean(self):
        datos = super().clean()
        if datos.get("fecha_desde") and datos.get("fecha_hasta") and datos["fecha_desde"] > datos["fecha_hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


class CancelarPendienteForm(forms.Form):
    version = forms.DateTimeField(widget=forms.HiddenInput)
    comentario = forms.CharField(label="Motivo de cancelación", widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)
