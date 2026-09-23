from django import template

register = template.Library()


@register.filter
def nombre_usuario(usuario):
    return (usuario.get_full_name() or usuario.username) if usuario else "Sin asignar"


@register.filter
def tiempo(segundos):
    if segundos is None:
        return "Sin definir"
    minutos = max(0, int(segundos)) // 60
    horas, minutos = divmod(minutos, 60)
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h {minutos} min" if dias else f"{horas} h {minutos} min"
