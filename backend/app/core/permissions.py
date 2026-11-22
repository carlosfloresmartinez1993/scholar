"""Permission catalog. Etapa 1: which views a role may open. Etapa 2: per view, «ver»
(the view code) and «editar» («<view>.editar»), plus delicate actions with their own
sign-off. A role grants a set of these codes; the server checks them on every
request (deps.require_view) and the menu shows the screens the user may open. The
roles themselves live in the database (Administración → Roles)."""

# (code, label, section) — the order is the menu's
VIEWS: list[tuple[str, str, str]] = [
    ("inicio", "Inicio (tablero)", "Escolar"),
    ("alumnos", "Alumnos", "Escolar"),
    ("profesores", "Profesores", "Escolar"),
    ("inscripciones", "Inscripciones", "Escolar"),
    ("programas", "Programas académicos", "Escolar"),
    ("grupos", "Grupos", "Escolar"),
    ("egresados", "Egresados", "Escolar"),
    ("calificaciones", "Calificaciones", "Académico"),
    ("asistencias", "Asistencias", "Académico"),
    ("tesoreria", "Tesorería", "Gestión"),
    ("reportes", "Reportes", "Gestión"),
    ("periodos", "Periodos", "Gestión"),
    ("planteles", "Planteles", "Gestión"),
    ("configuracion", "Configuración", "Gestión"),
    ("usuarios", "Usuarios", "Administración"),
    ("auditoria", "Auditoría", "Administración"),
    ("roles", "Roles", "Administración"),
]
# views where something can be changed: they get a «<view>.editar» permission
EDITABLE: list[str] = [
    "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
    "calificaciones", "asistencias", "tesoreria", "periodos", "planteles", "configuracion",
    "usuarios", "roles",
]


def edit(view: str) -> str:
    return f"{view}.editar"


# delicate actions, each its own sign-off (they need the view to reach the screen)
SPECIAL: list[tuple[str, str, str]] = [
    ("kardex_corregir", "Corregir kárdex y reconocer estudios", "Acciones especiales"),
    ("rvoe_cambio", "Cambio de RVOE", "Acciones especiales"),
    ("promocion_ciclo", "Promoción de ciclo", "Acciones especiales"),
    ("actas", "Generar y firmar actas", "Acciones especiales"),
    ("pagos_cancelar", "Cancelar pagos y condonar adeudos", "Acciones especiales"),
    ("becas_autorizar", "Autorizar becas", "Acciones especiales"),
]
ALL_PERMISSIONS = (
    {code for code, _, _ in VIEWS} | {edit(v) for v in EDITABLE} | {code for code, _, _ in SPECIAL}
)

# the role that always has everything (it can't lock itself out)
ADMIN_ROLE = "admin_sistema"


def _with_edit(views: set[str]) -> set[str]:
    return views | {edit(v) for v in views if v in EDITABLE}


# The roles the system starts with, granting what each one could already do.
# (code, name, own_subjects_only, permissions)
DEFAULT_ROLES: list[tuple[str, str, bool, set[str]]] = [
    (ADMIN_ROLE, "Administrador de sistema", False, set(ALL_PERMISSIONS)),
    ("direccion", "Dirección", False, _with_edit({
        "inicio", "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
        "calificaciones", "asistencias", "tesoreria", "reportes", "periodos", "planteles",
        "configuracion",
    }) | {"becas_autorizar", "kardex_corregir", "rvoe_cambio", "promocion_ciclo", "actas",
          "pagos_cancelar"}),
    ("servicios_escolares", "Servicios Escolares", False, _with_edit({
        "inicio", "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
        "calificaciones", "asistencias", "periodos", "planteles", "configuracion",
    }) | {"kardex_corregir", "rvoe_cambio", "promocion_ciclo", "actas"}),
    ("coordinador_academico", "Coordinación académica", False, _with_edit({
        "inicio", "alumnos", "grupos", "egresados", "calificaciones", "asistencias",
    }) | {"kardex_corregir", "rvoe_cambio", "promocion_ciclo", "actas"}),
    ("tesoreria", "Tesorería", False, _with_edit({"inicio", "tesoreria", "reportes"}) | {"pagos_cancelar"}),
    # a docente captures grades and takes attendance of their own materias only
    ("docente", "Docente", True, _with_edit({"calificaciones", "asistencias"})),
]
