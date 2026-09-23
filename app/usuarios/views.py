import mimetypes

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AdministrarUsuarioForm, PerfilUsuarioForm
from .correos import enviar_invitacion_usuario
from .models import PerfilUsuario
from .permisos import administrador_required
from tickets.permisos import tickets_visibles_para
from tickets.services.dashboard import resumen_dashboard


User = get_user_model()


@login_required
def dashboard(request):
    """
    Punto de entrada después del login.
    Redirige según el rol del usuario.
    """

    perfil, _ = PerfilUsuario.objects.get_or_create(
        user=request.user
    )

    if request.user.is_superuser or (
        perfil.activo and perfil.rol == PerfilUsuario.Rol.ADMIN
    ):
        return redirect("admin_panel")

    return redirect("mi_panel")


@administrador_required
def admin_panel(request):
    """
    Dashboard exclusivo para administradores.
    """

    perfil, _ = PerfilUsuario.objects.get_or_create(user=request.user)

    tickets = tickets_visibles_para(request.user)
    return render(
        request,
        "usuarios/admin_panel.html",
        {
            "perfil": perfil,
            "dashboard": resumen_dashboard(tickets),
        },
    )


@administrador_required
def usuarios_lista(request):
    missing_profile_ids = User.objects.filter(
        perfil__isnull=True
    ).values_list("pk", flat=True)
    PerfilUsuario.objects.bulk_create(
        [
            PerfilUsuario(user_id=user_id)
            for user_id in missing_profile_ids
        ],
        ignore_conflicts=True,
    )

    search = request.GET.get("q", "").strip()
    role = request.GET.get("rol", "").strip()
    status = request.GET.get("estado", "").strip()

    users = User.objects.select_related("perfil").order_by(
        "first_name",
        "last_name",
        "username",
    )

    if search:
        users = users.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(perfil__numero_empleado__icontains=search)
            | Q(perfil__area__icontains=search)
            | Q(perfil__cargo__icontains=search)
        )

    if role == PerfilUsuario.Rol.ADMIN:
        users = users.filter(
            Q(is_superuser=True) | Q(perfil__rol=PerfilUsuario.Rol.ADMIN)
        ).distinct()
    elif role == PerfilUsuario.Rol.USUARIO:
        users = users.filter(
            is_superuser=False,
            perfil__rol=PerfilUsuario.Rol.USUARIO,
        )

    if status == "activos":
        users = users.filter(is_active=True, perfil__activo=True)
    elif status == "inactivos":
        users = users.filter(
            Q(is_active=False) | Q(perfil__activo=False)
        ).distinct()

    paginator = Paginator(users, 18)
    page = paginator.get_page(request.GET.get("page"))
    query_without_page = request.GET.copy()
    query_without_page.pop("page", None)

    administrator_filter = Q(is_superuser=True) | (
        Q(perfil__rol=PerfilUsuario.Rol.ADMIN)
        & Q(perfil__activo=True)
    )
    total_users = User.objects.count()
    active_users = User.objects.filter(
        is_active=True,
        perfil__activo=True,
    ).count()

    return render(
        request,
        "usuarios/lista_usuarios.html",
        {
            "pagina": page,
            "busqueda": search,
            "rol_actual": role,
            "estado_actual": status,
            "roles": PerfilUsuario.Rol.choices,
            "query_without_page": query_without_page.urlencode(),
            "estadisticas": {
                "total": total_users,
                "activos": active_users,
                "administradores": User.objects.filter(
                    administrator_filter,
                    is_active=True,
                ).distinct().count(),
                "inactivos": total_users - active_users,
            },
        },
    )


@administrador_required
def usuario_crear(request):
    form = AdministrarUsuarioForm(
        request.POST or None,
        request.FILES or None,
        actor=request.user,
    )

    if request.method == "POST" and form.is_valid():
        user = form.save()
        nombre = user.get_full_name() or user.username
        if enviar_invitacion_usuario(user, request):
            messages.success(
                request,
                f"La cuenta de {nombre} fue creada y la invitación fue enviada.",
            )
        else:
            messages.warning(
                request,
                f"La cuenta de {nombre} fue creada, pero no se pudo enviar la invitación.",
            )
        return redirect("usuarios_lista")

    if request.method == "POST":
        messages.error(
            request,
            "Revisa los campos marcados antes de crear la cuenta.",
        )

    return render(
        request,
        "usuarios/form_usuario.html",
        {
            "form": form,
            "usuario_editado": None,
            "es_creacion": True,
        },
    )


@administrador_required
def usuario_editar(request, user_id):
    user = get_object_or_404(User, pk=user_id)

    if user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied

    PerfilUsuario.objects.get_or_create(user=user)
    form = AdministrarUsuarioForm(
        request.POST or None,
        request.FILES or None,
        actor=request.user,
        instance=user,
    )

    if request.method == "POST" and form.is_valid():
        updated_user = form.save()
        messages.success(
            request,
            f"La cuenta de {updated_user.get_full_name() or updated_user.username} fue actualizada.",
        )
        return redirect("usuarios_lista")

    if request.method == "POST":
        messages.error(
            request,
            "Revisa los campos marcados antes de guardar.",
        )

    return render(
        request,
        "usuarios/form_usuario.html",
        {
            "form": form,
            "usuario_editado": user,
            "es_creacion": False,
        },
    )


@login_required
def mi_panel(request):
    """
    Dashboard para usuarios / analistas.
    """

    perfil, _ = PerfilUsuario.objects.get_or_create(
        user=request.user
    )

    tickets = tickets_visibles_para(request.user)
    return render(
        request,
        "usuarios/mi_panel.html",
        {
            "perfil": perfil,
            "dashboard": resumen_dashboard(tickets),
        },
    )


@login_required
def perfil(request):
    """
    Perfil del usuario autenticado.
    """

    perfil_usuario, _ = PerfilUsuario.objects.get_or_create(
        user=request.user
    )

    form = PerfilUsuarioForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        perfil=perfil_usuario,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Tu perfil se actualizó correctamente.")
        return redirect("perfil")

    if request.method == "POST" and form.errors:
        messages.error(
            request,
            "Revisa los campos marcados antes de guardar.",
        )

    profile_values = [
        request.user.first_name,
        request.user.last_name,
        request.user.email,
        perfil_usuario.numero_empleado,
        perfil_usuario.telefono,
        perfil_usuario.area,
        perfil_usuario.cargo,
        perfil_usuario.foto.name if perfil_usuario.foto else "",
    ]
    completed_values = sum(bool(value.strip()) for value in profile_values)
    completion_percentage = round(
        completed_values / len(profile_values) * 100
    )

    return render(
        request,
        "usuarios/perfil.html",
        {
            "perfil": perfil_usuario,
            "form": form,
            "completion_percentage": completion_percentage,
        },
    )


@login_required
def usuario_foto(request, user_id):
    usuario = get_object_or_404(
        User.objects.select_related("perfil"),
        pk=user_id,
    )
    foto = usuario.perfil.foto

    if not foto:
        raise Http404("Este usuario no tiene foto de perfil.")

    try:
        archivo = foto.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("La foto de perfil no está disponible.")

    content_type = mimetypes.guess_type(foto.name)[0] or "image/webp"
    respuesta = FileResponse(archivo, content_type=content_type)
    respuesta["Content-Disposition"] = "inline"
    respuesta["Cache-Control"] = "private, max-age=3600"
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta
