# Gestor de pendientes — fase 1

Módulo independiente de tickets, integrado con los usuarios, el catálogo de tiendas,
la navegación y los temas claro/oscuro existentes. No cambia los flujos ni el SLA
de los tickets.

## Acceso

Esta fase es **exclusiva para administradores**, conforme a la indicación del proyecto
previa a los requerimientos. Se reutiliza `usuarios.permisos.administrador_required`
(incluye inicio de sesión), y los servicios también verifican `es_administrador`.
Un usuario regular no entra aunque sea responsable o tenga un permiso Django aislado.
"Mis pendientes" muestra las tareas abiertas del administrador conectado.

La migración crea los permisos Django `add_pendiente`, `change_pendiente`,
`view_pendiente` y `view_pendientehistorial`. No concede roles nuevos ni permisos
de eliminación. El admin técnico es de solo lectura. La interfaz normal usa
cancelación en lugar de borrado y permite reabrir mediante edición.

## Archivos

App nueva: `gestor/apps.py`, `models.py`, `services.py`, `forms.py`, `views.py`,
`urls.py`, `admin.py`, `tests.py`, `templatetags/gestor_tags.py`, inicializadores,
este documento y `migrations/0001_initial.py`.

Templates nuevos: `templates/gestor/base.html`, `estilos.html`, `lista.html`,
`formulario.html`, `detalle.html`, `cancelar.html`.

Integración: `config/settings.py`, `config/urls.py`,
`templates/components/sidebar.html` y `templates/components/topbar.html`.

## Rutas

| Ruta | Métodos | Función |
| --- | --- | --- |
| `/gestor/` | GET | Dashboard, indicadores, filtros y listado paginado |
| `/gestor/nuevo/` | GET, POST | Alta rápida |
| `/gestor/GST-000001/` | GET | Detalle e historial con scroll y paginación |
| `/gestor/GST-000001/editar/` | GET, POST | Edición, seguimiento, cierre y reapertura |
| `/gestor/GST-000001/cancelar/` | GET, POST | Confirmación y cancelación con motivo |

Los folios se generan usando la secuencia de la clave primaria; son únicos incluso
con altas simultáneas. Pueden existir saltos en la numeración, como en cualquier
secuencia transaccional. No son editables desde los formularios.

## Reglas y decisiones

- `responsable`: usuario Django existente; se ofrecen usuarios activos. Si el
  responsable actual fue desactivado, se permite conservarlo al editar.
- `tda`: tienda existente, opcional para actividades generales. Se muestra el nombre.
- `solicitante`: texto libre para admitir solicitudes externas.
- Áreas, categorías y otros catálogos son `TextChoices`, siguiendo el patrón del
  proyecto. Agregar opciones requiere actualizar el enum y generar la migración.
- Compromiso: fecha, con días naturales y zona `America/Mexico_City`; vence al día
  siguiente, no a una hora arbitraria del día de compromiso.
- Primera atención: primera transición de Pendiente a En curso o En espera.
  No se reinicia al reabrir.
- Cierre: fecha automática al pasar a Completado. En una reapertura se limpia el
  cierre vigente y se conservan todos los eventos de cierre previos.
- En espera: exige tipo de bloqueo, bloqueado por/explicación y siguiente acción.
- En curso: recomienda responsable, compromiso y siguiente acción sin impedir guardar.
- Tiempo abierto: creación a cierre para completados; creación a ahora para los
  demás estados, según el requerimiento. Cancelados no cuentan como abiertos en
  indicadores ni acumulan atraso. Tiempo de resolución solo existe con cierre vigente.
- Semáforo: gris para estados terminales; rojo para vencidos; amarillo con compromiso
  a dos días naturales o menos, prioridad crítica, espera o recomendaciones faltantes
  en curso; verde en los otros casos.
- KPIs globales: no cambian con filtros. Los filtros y vistas rápidas se combinan
  sobre la tabla. "Esta semana" es de lunes a domingo. "Todos" incluye terminales.
- Escrituras mediante `crear_pendiente` / `actualizar_pendiente`: validación,
  autorización, transacción y auditoría. Bloqueo de fila y versión del formulario
  evitan sobrescribir ediciones concurrentes. No usar `QuerySet.update()` ni
  `bulk_create()` para operaciones normales que deban generar historial.
- El historial captura valores anteriores/nuevos y comentarios. Su FK protegida
  evita borrar pendientes con historial; las relaciones de usuario preservan autores.

## Verificación

Desde la raíz del proyecto:

```bash
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py test -v 1
```

Las pruebas cubren creación y folio, transiciones, atención inicial, bloqueo,
cierre, reapertura, métricas, auditoría, ediciones obsoletas, permisos en vistas y
servicios, CSRF, escape de contenido, filtros, KPIs, paginación y consultas sin N+1.

## Segunda fase

- Importador CSV/JSON de los aproximadamente 24 registros externos, con vista previa
  y control de duplicados; sin dependencia de Notion.
- Recurrencia automática y notificaciones, únicamente al definir sus reglas.
- Evaluar acceso de usuarios regulares y permisos delegados si se autoriza ampliar
  el alcance actual de administradores.
- Catálogos editables desde interfaz si se necesita que las áreas/categorías se
  administren sin cambios de código.

La frecuencia se almacena como referencia; no genera tareas ni mensajes automáticos.
