"""Permission catalog (Etapa 1: views). A role grants a set of these codes; the
server checks them on every request (deps.require_view) and the menu shows the
screens the user may open. The roles themselves live in the database and are
edited in Administración → Roles."""

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
# actions that are not a whole screen but need their own sign-off
SPECIAL: list[tuple[str, str, str]] = [
    ("becas_autorizar", "Autorizar becas", "Acciones especiales"),
]
ALL_PERMISSIONS = {code for code, _, _ in VIEWS + SPECIAL}

# the role that always has everything (it can't lock itself out)
ADMIN_ROLE = "admin_sistema"

# The roles the system starts with, granting what each one could already do.
# (code, name, own_subjects_only, permissions)
DEFAULT_ROLES: list[tuple[str, str, bool, set[str]]] = [
    (ADMIN_ROLE, "Administrador de sistema", False, set(ALL_PERMISSIONS)),
    ("direccion", "Dirección", False, {
        "inicio", "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
        "calificaciones", "asistencias", "tesoreria", "reportes", "periodos", "planteles",
        "configuracion", "becas_autorizar",
    }),
    ("servicios_escolares", "Servicios Escolares", False, {
        "inicio", "alumnos", "profesores", "inscripciones", "programas", "grupos", "egresados",
        "calificaciones", "asistencias", "periodos", "planteles", "configuracion",
    }),
    ("coordinador_academico", "Coordinación académica", False, {
        "inicio", "alumnos", "grupos", "egresados", "calificaciones", "asistencias",
    }),
    ("tesoreria", "Tesorería", False, {"inicio", "tesoreria", "reportes"}),
    # a docente captures grades and takes attendance of their own materias only
    ("docente", "Docente", True, {"calificaciones", "asistencias"}),
]
