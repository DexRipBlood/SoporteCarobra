def categoria_fila(fila):
    return str(fila.get("categoria") or "Sin categoría").strip()


def filtrar_categorias(filas, categorias=None):
    if categorias is None:
        return filas
    permitidas = {c.strip().casefold() for c in categorias}
    return [fila for fila in filas if categoria_fila(fila).casefold() in permitidas]
