# INUE Scholar

Sistema de administración escolar del Instituto Universitario Ensenada
(scholar.inue.online). Reemplaza el flujo de servoescolar.mx con una
arquitectura desacoplada (API + SPA) y modelo de datos multi-RVOE listo para
multi-plantel. Hermano del sistema de horarios (calendar.inue.online /
timetable-engine), con el que se integrará vía la API de integración.

## Módulos (primera iteración)

- **Catálogo académico** — programas, RVOE por programa+modalidad+plantel
  (RT-01/02) con bloqueo de operación si el RVOE no está vigente (RT-03),
  versiones de plan de estudios (RT-04), materias con seriación y esquema de
  evaluación configurable, ciclos escolares y grupos.
- **Alumnos** — registro por CURP (RT-09), inscripción a plan (fija el RVOE del
  historial, RF-C04), inscripción a grupo/materias con validación de seriación
  (RF-C07), exportación SEP de inscritos/reinscritos (RT-10).
- **Calificaciones** — captura por docente asignado dentro de la ventana
  habilitada (RF-C01), calificación final ponderada, actas con folio (RF-C03),
  kardex y avance curricular (RF-C05/C08), libro de títulos (RF-C09).
- **Asistencias** — pase de lista por sesión (RF-A01), % mínimo por plan
  (RF-A02), derecho a examen, justificantes con flujo de aprobación (RF-A04),
  alertas de riesgo por correo (RF-A03).
- **Expediente / Documentación** — checklist de ingreso (RF-D02), carga y
  revisión de documentos con versiones (RF-D03), constancias/kardex/
  certificados con folio único y auditable (RF-D04/D05), reglamento con
  aceptación (RF-D06), expedientes docentes (RF-D07).
- **Tesorería** (control interno, sin pasarela) — conceptos por programa
  (RF-T01), planes de pago (RF-T02), captura manual de pagos con folio de
  recibo (RF-T03/T09), estado de cuenta (RF-T04), becas (RF-T05), recargos
  (RF-T06), bloqueo de trámites por adeudo con liberación automática (RF-T07),
  reportes de cobranza/cartera y exportación contable (RF-T08/T10).
- **Auditoría** — bitácora con valor anterior/nuevo en calificaciones, folios,
  pagos y expediente (RT-08).

## Stack

- **Backend**: FastAPI (async) + SQLModel + Alembic + PostgreSQL — `backend/`
- **Frontend**: Vite + React 19 + Tailwind v4 + shadcn/ui + TanStack — `frontend/`
- **Local**: `docker compose up` (db en :5434)
- **Deploy**: Railway (Dockerfile builder, proyecto compartido con
  timetabling-engine)

## Desarrollo

```bash
docker compose up -d db mailcatcher
cd backend && uv sync
ENV_FILE=../.env.local uv run alembic upgrade head
ENV_FILE=../.env.local uv run python -m app.initial_data   # institución + superusuario
ENV_FILE=../.env.local uv run fastapi dev                  # :8000
cd ../frontend && pnpm install && pnpm dev                 # :5173 (proxy /api → :8000)
```

Tests: `cd backend && uv run pytest`

`.env.local` mínimo:

```
POSTGRES_SERVER=localhost
POSTGRES_PORT=5434
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=scholar
FIRST_SUPERUSER=admin@inue.edu.mx
FIRST_SUPERUSER_PASSWORD=localdev123
```

## RBAC (RT-07)

Roles de staff: `admin_sistema`, `direccion`, `servicios_escolares`,
`coordinador_academico`, `tesoreria`, `docente`. El superusuario administra
cuentas; los docentes solo capturan calificaciones/asistencia de sus materias
asignadas. (El portal de alumnos queda para una iteración futura.)

## API de integración con el calendario (RT-11, RF-I01/I02)

Endpoints de solo lectura autenticados con header `X-API-Key`
(`INTEGRATION_API_KEY`):

- `GET /api/v1/integration/terms` — ciclos y ventanas de evaluación
- `GET /api/v1/integration/groups?term_id=` — grupos con materias, docentes,
  RVOE y `schedule_text`
- `GET /api/v1/integration/groups/{id}/enrollments` — alumnos inscritos por
  materia

SSO OAuth2/OIDC entre ambos sistemas (RF-I03) queda para la fase de
integración.

## Variables (Railway)

`SECRET_KEY`, `POSTGRES_*`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`,
`INTEGRATION_API_KEY`, `RESEND_API_KEY`, `FRONTEND_URL`, `UPLOADS_DIR`
(montar volumen), `ENVIRONMENT=production`.
