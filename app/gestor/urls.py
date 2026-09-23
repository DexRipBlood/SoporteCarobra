from django.urls import path

from . import views

app_name = "gestor"
urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.crear, name="crear"),
    path("<str:folio>/", views.detalle, name="detalle"),
    path("<str:folio>/editar/", views.editar, name="editar"),
    path("<str:folio>/cancelar/", views.cancelar, name="cancelar"),
]
