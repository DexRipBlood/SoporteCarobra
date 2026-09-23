import calendar
from datetime import date, datetime, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from usuarios.models import PerfilUsuario
from usuarios.permisos import administrador_required, es_administrador
from .forms import EmpresaForm, ZonaForm, TiendaForm, GrupoTrabajoForm, MembresiaGrupoForm, ProgramacionTrabajoForm, ConfiguracionSLAForm
from .models import Empresa, Zona, Tienda, GrupoTrabajo, MembresiaGrupo, ProgramacionTrabajo, ConfiguracionSLA, Ticket, EstadoTicket
from .permisos import tickets_visibles_para, participa_en_ticket
from .services.operacion import equipo_tienda, seguimiento_actual, cambiar_seguimiento, evento, requieren_administracion
from .services.operacion import sincronizar_sla, resumen_sla


def _entero(valor):
    try:
        return int(valor)
    except (ValueError, TypeError):
        return None


@administrador_required
def territorio(request):
    empresas = Empresa.objects.annotate(total=Count("tiendas", distinct=True)).order_by("nombre")
    empresa = get_object_or_404(Empresa, pk=_entero(request.GET.get("empresa"))) if request.GET.get("empresa") else empresas.first()
    zonas = Zona.objects.filter(empresa=empresa, activa=True).select_related("responsable", "partner").annotate(total=Count("tiendas")).order_by("nombre")
    distrito = get_object_or_404(zonas, pk=_entero(request.GET.get("distrito"))) if request.GET.get("distrito") else None
    tiendas = Tienda.objects.filter(empresa=empresa).select_related("zona__responsable", "zona__partner", "encargado_soporte__usuario", "partner__usuario").annotate(abiertos=Count("tickets", filter=~Q(tickets__estado_interno="CERRADO")))
    if distrito:
        tiendas = tiendas.filter(zona=distrito)
    q = request.GET.get("q", "").strip()
    filtro_tipo = request.GET.get("socio", "").strip()
    filtro_estado = request.GET.get("estado", "").strip()
    filtro_ciudad = request.GET.get("ciudad", "").strip()
    if q:
        tiendas = tiendas.filter(Q(nombre__icontains=q) | Q(numero__icontains=q) | Q(zona__nombre__icontains=q) | Q(ciudad__icontains=q))
    if filtro_tipo:
        tiendas = tiendas.filter(socio=filtro_tipo)
    if filtro_estado:
        tiendas = tiendas.filter(estado=filtro_estado)
    if filtro_ciudad == "__SIN_CIUDAD__":
        tiendas = tiendas.filter(ciudad="")
    elif filtro_ciudad:
        tiendas = tiendas.filter(ciudad=filtro_ciudad)
    opciones_tienda = {
        "socio": Tienda.objects.filter(empresa=empresa).exclude(socio="").values_list("socio", flat=True).distinct().order_by("socio"),
        "estado": Tienda.objects.filter(empresa=empresa).exclude(estado="").values_list("estado", flat=True).distinct().order_by("estado"),
        "ciudad": Tienda.objects.filter(empresa=empresa).exclude(ciudad="").values_list("ciudad", flat=True).distinct().order_by("ciudad"),
    }
    pagina = Paginator(tiendas.order_by("nombre"), 24).get_page(request.GET.get("page"))
    parametros_paginacion = request.GET.copy()
    parametros_paginacion.pop("page", None)
    query_paginacion = parametros_paginacion.urlencode()
    for tienda in pagina:
        tienda.equipo_responsable, tienda.equipo_partner = equipo_tienda(tienda)
    seleccion = get_object_or_404(tiendas, pk=_entero(request.GET.get("tienda"))) if request.GET.get("tienda") else None
    tickets = seleccion.tickets.order_by("-creado_at")[:10] if seleccion else []
    mapa = [{"nombre": t.nombre, "lat": float(t.latitud), "lng": float(t.longitud), "cadena": t.tipo_tienda_codigo,
             "url": f"?empresa={empresa.pk}&tienda={t.pk}", "ciudad": t.ciudad, "estado": t.estado} for t in tiendas if t.latitud is not None and t.longitud is not None]
    return render(request, "tickets/operacion/territorio.html", locals())


CATALOGOS = {
    "empresa": (Empresa, EmpresaForm, "Empresa", "territorio"),
    "distrito": (Zona, ZonaForm, "Distrito y equipo de soporte", "territorio"),
    "tienda": (Tienda, TiendaForm, "Tienda", "territorio"),
    "grupo": (GrupoTrabajo, GrupoTrabajoForm, "Grupo de actividades", "calendario"),
    "miembro": (MembresiaGrupo, MembresiaGrupoForm, "Integrante del grupo", "calendario"),
    "incidencia": (ConfiguracionSLA, ConfiguracionSLAForm, "Categoría e incidencia", "incidencias"),
}


@administrador_required
def editar_catalogo(request, tipo, pk=None):
    if tipo not in CATALOGOS:
        raise Http404
    modelo, formulario, titulo, destino = CATALOGOS[tipo]
    instancia = get_object_or_404(modelo, pk=pk) if pk else None
    form = formulario(request.POST if request.method == "POST" else None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            registro = form.save()
            # Cambiar el catálogo no reasigna tickets que ya están en seguimiento.
        messages.success(request, "Configuración guardada. Se utilizará en nuevas asignaciones.")
        return redirect(f"tickets:{destino}")
    return render(request, "tickets/operacion/editor.html", {"form": form, "titulo": titulo, "destino": destino})


@administrador_required
def calendario(request):
    hoy = timezone.localdate()
    try:
        fecha = date.fromisoformat(request.GET.get("fecha", hoy.isoformat()))
    except ValueError:
        fecha = hoy
    semana = request.GET.get("vista") == "semana"
    inicio = fecha - timedelta(days=fecha.weekday()) if semana else fecha.replace(day=1)
    dias = [inicio + timedelta(days=i) for i in range(7)] if semana else list(calendar.Calendar(firstweekday=0).itermonthdates(fecha.year, fecha.month))
    grupos = GrupoTrabajo.objects.select_related("empresa", "lider").prefetch_related("miembros__usuario", "incidencias").order_by("nombre")
    usuarios = get_user_model().objects.filter(is_active=True).order_by("first_name", "username")
    usuario_id = _entero(request.GET.get("usuario"))
    grupo_id = _entero(request.GET.get("grupo"))
    turnos = ProgramacionTrabajo.objects.filter(fecha_inicio__lte=dias[-1], fecha_fin__gte=dias[0]).select_related("usuario", "grupo")
    if usuario_id:
        turnos = turnos.filter(usuario_id=usuario_id)
    if grupo_id:
        turnos = turnos.filter(grupo_id=grupo_id)
    turnos = list(turnos)
    celdas = [{"fecha": dia, "hoy": dia == hoy, "otro_mes": dia.month != fecha.month,
               "turnos": [t for t in turnos if t.fecha_inicio <= dia <= t.fecha_fin]} for dia in dias]
    anterior = inicio - timedelta(days=7 if semana else 1)
    siguiente = inicio + timedelta(days=7) if semana else (inicio.replace(day=28) + timedelta(days=4)).replace(day=1)
    edicion = get_object_or_404(ProgramacionTrabajo, pk=_entero(request.GET.get("editar"))) if request.GET.get("editar") else None
    form = ProgramacionTrabajoForm(request.POST if request.method == "POST" else None, instance=edicion,
        initial={"fecha_inicio": fecha, "fecha_fin": fecha, "usuario": usuario_id, "grupo": grupo_id, "hora_inicio": "09:00", "hora_fin": "18:00"})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # Serializa las programaciones del usuario para validar cruces concurrentes.
            get_user_model().objects.select_for_update().get(pk=form.cleaned_data["usuario"].pk)
            segunda = ProgramacionTrabajoForm(request.POST, instance=edicion)
            if segunda.is_valid():
                segunda.save()
                messages.success(request, "Horario guardado. La disponibilidad ya se refleja en el seguimiento de tickets.")
                return redirect(request.get_full_path().split("&editar=")[0] if not request.GET.get("editar") else "tickets:calendario")
            form = segunda
    pendientes_admin = requieren_administracion(Ticket.objects.all()).order_by("-creado_at")[:15]
    return render(request, "tickets/operacion/calendario.html", locals())


@administrador_required
def incidencias(request):
    q = request.GET.get("q", "").strip()
    reglas = ConfiguracionSLA.objects.annotate(total=Count("tickets", distinct=True)).order_by("categoria", "incidencia_general")
    if q:
        reglas = reglas.filter(Q(categoria__icontains=q) | Q(incidencia_general__icontains=q))
    pagina = Paginator(reglas, 30).get_page(request.GET.get("page"))
    return render(request, "tickets/operacion/incidencias.html", locals())


class PermisosForm(forms.ModelForm):
    class Meta:
        model = PerfilUsuario
        fields = ["puede_seguimiento", "puede_cerrar", "puede_reasignar", "puede_ver_todos"]


@administrador_required
def permisos(request):
    usuarios = get_user_model().objects.select_related("perfil").order_by("first_name", "username")
    usuario = get_object_or_404(usuarios, pk=_entero(request.GET.get("usuario"))) if request.GET.get("usuario") else None
    form = None
    if usuario:
        perfil, _ = PerfilUsuario.objects.get_or_create(user=usuario)
        form = PermisosForm(request.POST if request.method == "POST" else None, instance=perfil)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Permisos de tickets actualizados.")
            return redirect("tickets:permisos")
    return render(request, "tickets/operacion/permisos.html", locals())


class SeguimientoForm(forms.Form):
    estado = forms.ChoiceField(choices=[(v, label) for v, label in EstadoTicket.choices if v in ("ASIGNADO", "EN_PROCESO", "EN_ESPERA", "RESUELTO")])
    siguiente_accion = forms.CharField(label="Siguiente acción", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    motivo_espera = forms.CharField(label="Motivo de espera externa", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    esperando_a = forms.CharField(label="Persona / área / tercero que debe responder", max_length=255, required=False)


@login_required
def tiempos(request, folio):
    ticket = get_object_or_404(tickets_visibles_para(request.user).prefetch_related("segmentos_sla"), folio=folio)
    respuesta = JsonResponse(resumen_sla(ticket))
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@login_required
@require_POST
def seguimiento(request, folio):
    ticket = get_object_or_404(tickets_visibles_para(request.user), folio=folio)
    form = SeguimientoForm(request.POST)
    if form.is_valid():
        try:
            cambiar_seguimiento(ticket.pk, request.user, form.cleaned_data)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Seguimiento y tiempos actualizados.")
    else:
        messages.error(request, "Revisa los datos del seguimiento.")
    return redirect("tickets:detalle", folio=folio)


@login_required
@require_POST
def escalar(request, folio):
    ticket = get_object_or_404(tickets_visibles_para(request.user), folio=folio)
    if not participa_en_ticket(request.user, ticket):
        raise PermissionDenied
    motivo = request.POST.get("motivo", "").strip()
    if not motivo:
        messages.error(request, "Explica qué necesitas de administración.")
    else:
        with transaction.atomic():
            ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
            if ticket.estado_interno == EstadoTicket.CERRADO:
                messages.error(request, "El ticket debe estar abierto para escalarlo.")
            else:
                ticket.solicitud_admin = True
                ticket.motivo_admin = motivo
                ticket.save(update_fields=["solicitud_admin", "motivo_admin", "actualizado_at"])
                evento(ticket, request.user, "ESCALADO", "Solicitud a administración.", despues={"motivo": motivo})
                messages.success(request, "Administración verá la solicitud. El SLA continúa.")
    return redirect("tickets:detalle", folio=folio)


class SuplenciaForm(forms.Form):
    usuario = forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True, perfil__activo=True))
    hasta = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    motivo = forms.CharField(max_length=1000)


@administrador_required
@require_POST
def suplencia(request, folio):
    form = SuplenciaForm(request.POST)
    if form.is_valid() and form.cleaned_data["hasta"] > timezone.now():
        with transaction.atomic():
            ticket = get_object_or_404(Ticket.objects.select_for_update(), folio=folio)
            if ticket.estado_interno == EstadoTicket.CERRADO:
                messages.error(request, "No se puede asignar suplencia a un ticket cerrado.")
                return redirect("tickets:detalle", folio=folio)
            antes = {"suplente": ticket.suplente_id}
            ticket.suplente = form.cleaned_data["usuario"]
            ticket.suplente_hasta = form.cleaned_data["hasta"]
            ticket.solicitud_admin = False
            ticket.save(update_fields=["suplente", "suplente_hasta", "solicitud_admin", "actualizado_at"])
            evento(ticket, request.user, "SUPLENCIA", form.cleaned_data["motivo"], antes,
                   {"suplente": ticket.suplente.get_full_name() or ticket.suplente.username, "hasta": ticket.suplente_hasta.isoformat()})
        messages.success(request, "Suplente asignado. Se conservan el encargado y partner habituales.")
    else:
        messages.error(request, "Selecciona usuario, motivo y una fecha futura para el fin de la suplencia.")
    return redirect("tickets:detalle", folio=folio)


@administrador_required
@require_POST
def clasificar(request, folio):
    regla = get_object_or_404(ConfiguracionSLA, pk=_entero(request.POST.get("regla")), activo=True)
    with transaction.atomic():
        ticket = get_object_or_404(Ticket.objects.select_for_update(), folio=folio)
        if ticket.estado_interno == EstadoTicket.CERRADO:
            messages.error(request, "Reabre el ticket antes de cambiar su clasificación.")
            return redirect("tickets:detalle", folio=folio)
        antes = {"categoria": ticket.categoria, "incidencia": ticket.incidencia_general, "limite_minutos": ticket.sla_limite_minutos}
        if resumen_sla(ticket)["excedido"]:
            ticket.sla_excedido = True
            ticket.sla_excedido_at = ticket.sla_excedido_at or timezone.now()
        ticket.categoria = regla.categoria
        ticket.incidencia_general = regla.incidencia_general
        ticket.configuracion_sla = regla
        ticket.clasificacion_manual = True
        ticket.sla_limite_minutos = regla.limite_minutos
        ticket.prioridad = regla.prioridad
        ticket.save()
        sincronizar_sla(ticket, request.user)
        evento(ticket, request.user, "CLASIFICACION", "Categoría y SLA actualizados; se conserva el tiempo consumido.", antes,
               {"categoria": ticket.categoria, "incidencia": ticket.incidencia_general, "limite_minutos": ticket.sla_limite_minutos})
    messages.success(request, "Clasificación aplicada sin reiniciar los tiempos.")
    return redirect("tickets:detalle", folio=folio)
