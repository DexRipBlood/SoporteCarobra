from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from usuarios.permisos import administrador_required

from .forms import CancelarPendienteForm, FiltrosPendienteForm, PendienteForm
from .models import Pendiente
from .services import actualizar_pendiente, crear_pendiente


VISTAS_RAPIDAS = (
    ("todos", "Todos"), ("abiertos", "Abiertos"), ("mis", "Mis pendientes"), ("hoy", "Hoy"),
    ("vencidos", "Vencidos"), ("semana", "Esta semana"), ("espera", "En espera"),
    ("criticos", "Críticos"), ("sin_responsable", "Sin responsable"), ("completados", "Completados"),
)


@administrador_required
@require_http_methods(["GET"])
def lista(request):
    hoy = timezone.localdate()
    base = Pendiente.objects.all()
    abiertos = ~Q(estado__in=Pendiente.ESTADOS_TERMINALES)
    kpis = base.aggregate(
        abiertos=Count("pk", filter=abiertos),
        vencidos=Count("pk", filter=abiertos & Q(fecha_compromiso__lt=hoy)),
        hoy=Count("pk", filter=abiertos & Q(fecha_compromiso=hoy)),
        espera=Count("pk", filter=Q(estado=Pendiente.Estado.EN_ESPERA)),
        criticos=Count("pk", filter=abiertos & Q(prioridad=Pendiente.Prioridad.CRITICA)),
        sin_responsable=Count("pk", filter=abiertos & Q(responsable__isnull=True)),
    )
    form = FiltrosPendienteForm(request.GET)
    queryset = base.select_related("responsable", "tda")
    if form.is_valid():
        datos = form.cleaned_data
        for campo in ("estado", "responsable", "area", "prioridad", "categoria", "bloqueo", "tipo_trabajo", "frecuencia", "tda"):
            if datos.get(campo):
                queryset = queryset.filter(**{campo: datos[campo]})
        if datos.get("q"):
            q = datos["q"]
            queryset = queryset.filter(Q(folio__icontains=q) | Q(titulo__icontains=q) |
                                       Q(detalle__icontains=q) | Q(bloqueado_por__icontains=q) |
                                       Q(siguiente_accion__icontains=q))
        if datos.get("fecha_desde"):
            queryset = queryset.filter(fecha_compromiso__gte=datos["fecha_desde"])
        if datos.get("fecha_hasta"):
            queryset = queryset.filter(fecha_compromiso__lte=datos["fecha_hasta"])
    else:
        queryset = queryset.none()

    vista = request.GET.get("vista", "todos")
    reglas = {
        "todos": Q(), "abiertos": abiertos, "mis": abiertos & Q(responsable=request.user),
        "hoy": abiertos & Q(fecha_compromiso=hoy),
        "vencidos": abiertos & Q(fecha_compromiso__lt=hoy),
        "semana": abiertos & Q(fecha_compromiso__range=(hoy - timedelta(days=hoy.weekday()), hoy + timedelta(days=6 - hoy.weekday()))),
        "espera": Q(estado=Pendiente.Estado.EN_ESPERA),
        "criticos": abiertos & Q(prioridad=Pendiente.Prioridad.CRITICA),
        "sin_responsable": abiertos & Q(responsable__isnull=True),
        "completados": Q(estado=Pendiente.Estado.COMPLETADO),
    }
    if vista not in reglas:
        vista = "todos"
    queryset = queryset.filter(reglas[vista])
    pagina = Paginator(queryset, 25).get_page(request.GET.get("page"))
    parametros = request.GET.copy()
    parametros.pop("page", None)
    accesos = []
    for clave, etiqueta in VISTAS_RAPIDAS:
        parametros["vista"] = clave
        accesos.append({"clave": clave, "etiqueta": etiqueta, "query": parametros.urlencode()})
    parametros["vista"] = vista
    return render(request, "gestor/lista.html", {
        "form": form, "kpis": kpis, "pagina": pagina, "vista": vista,
        "accesos": accesos, "parametros": parametros.urlencode(),
    })


def _errores_servicio(form, error):
    if hasattr(error, "message_dict"):
        for campo, errores in error.message_dict.items():
            form.add_error(campo if campo in form.fields else None, errores)
    else:
        form.add_error(None, error)


@administrador_required
@require_http_methods(["GET", "POST"])
def crear(request):
    form = PendienteForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            pendiente = crear_pendiente(usuario=request.user, datos=form.cleaned_data)
        except ValidationError as error:
            _errores_servicio(form, error)
        else:
            messages.success(request, f"{pendiente.folio} creado correctamente.")
            return redirect("gestor:detalle", folio=pendiente.folio)
    return render(request, "gestor/formulario.html", {"form": form})


@administrador_required
@require_http_methods(["GET", "POST"])
def editar(request, folio):
    pendiente = get_object_or_404(Pendiente.objects.select_related("responsable", "tda"), folio=folio)
    form = PendienteForm(request.POST if request.method == "POST" else None, instance=pendiente)
    if request.method == "POST" and form.is_valid():
        try:
            pendiente = actualizar_pendiente(
                pendiente_id=pendiente.pk, usuario=request.user, datos=form.cleaned_data,
                comentario=form.cleaned_data["comentario"], version=form.cleaned_data["version"],
            )
        except ValidationError as error:
            _errores_servicio(form, error)
        else:
            messages.success(request, "Pendiente actualizado. Los cambios quedaron en el historial.")
            for recomendacion in pendiente.recomendaciones:
                messages.warning(request, recomendacion)
            return redirect("gestor:detalle", folio=pendiente.folio)
    return render(request, "gestor/formulario.html", {"form": form, "pendiente": pendiente})


@administrador_required
@require_http_methods(["GET"])
def detalle(request, folio):
    pendiente = get_object_or_404(Pendiente.objects.select_related("responsable", "creado_por", "tda"), folio=folio)
    historial = Paginator(pendiente.historial.select_related("usuario"), 40).get_page(request.GET.get("page"))
    return render(request, "gestor/detalle.html", {"pendiente": pendiente, "historial": historial})


@administrador_required
@require_http_methods(["GET", "POST"])
def cancelar(request, folio):
    pendiente = get_object_or_404(Pendiente, folio=folio)
    form = CancelarPendienteForm(
        request.POST if request.method == "POST" else None,
        initial={"version": pendiente.ultima_actualizacion.isoformat()},
    )
    if request.method == "POST" and form.is_valid():
        try:
            actualizar_pendiente(
                pendiente_id=pendiente.pk, usuario=request.user,
                datos={"estado": Pendiente.Estado.CANCELADO},
                comentario=form.cleaned_data["comentario"], version=form.cleaned_data["version"],
            )
        except ValidationError as error:
            _errores_servicio(form, error)
        else:
            messages.success(request, "Pendiente cancelado. Se conserva todo su historial.")
            return redirect("gestor:detalle", folio=folio)
    return render(request, "gestor/cancelar.html", {"form": form, "pendiente": pendiente})
