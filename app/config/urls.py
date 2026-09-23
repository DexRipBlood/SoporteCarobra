from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("gestor/", include("gestor.urls")),

    path(
        "accounts/",
        include("allauth.urls"),
    ),

    path(
        "tickets/",
        include("tickets.urls"),
    ),

    path(
        "",
        include("usuarios.urls"),
    ),
]
