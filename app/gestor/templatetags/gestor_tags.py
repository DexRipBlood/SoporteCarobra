from django import template

register = template.Library()


@register.filter
def duracion(valor):
    if valor is None:
        return "Sin registrar"
    minutos = max(0, int(valor.total_seconds()) // 60)
    dias, resto = divmod(minutos, 1440)
    horas, minutos = divmod(resto, 60)
    return f"{dias} d · {horas} h · {minutos} min" if dias else f"{horas} h · {minutos} min"
