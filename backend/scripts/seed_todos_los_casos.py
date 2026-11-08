"""Datos de demostración: un programa de Software (9 cuatrimestres × 5 materias) y UN
alumno que pasa por todos los casos del control de estudiantes. Todo se hace por la
API, con las mismas reglas que la app.

    uv run python scripts/seed_todos_los_casos.py [url] [correo] [contraseña]

Espera una base limpia; solo es para el ambiente local."""
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8800"
EMAIL = sys.argv[2] if len(sys.argv) > 2 else "admin@inue.edu.mx"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "localdev123"
API = f"{BASE}/api/v1"
REASON = "Corrección de captura (demostración)"

NAMES = [
    ["Fundamentos de Programación", "Matemáticas Discretas", "Introducción a la Ingeniería de Software",
     "Comunicación Oral y Escrita", "Álgebra Lineal"],
    ["Programación Orientada a Objetos", "Cálculo Diferencial", "Arquitectura de Computadoras",
     "Inglés Técnico I", "Ética Profesional"],
    ["Estructuras de Datos", "Cálculo Integral", "Bases de Datos I", "Sistemas Operativos", "Probabilidad y Estadística"],
    ["Algoritmos", "Bases de Datos II", "Redes de Computadoras", "Ingeniería de Requerimientos", "Inglés Técnico II"],
    ["Desarrollo Web", "Análisis y Diseño de Software", "Seguridad Informática", "Investigación de Operaciones", "Administración de Proyectos"],
    ["Desarrollo Móvil", "Patrones de Diseño", "Pruebas de Software", "Cómputo en la Nube", "Interacción Humano-Computadora"],
    ["Inteligencia Artificial", "Arquitectura de Software", "Calidad de Software", "DevOps", "Sistemas Distribuidos"],
    ["Aprendizaje Automático", "Ciencia de Datos", "Emprendimiento Tecnológico", "Seminario de Titulación I", "Optativa I"],
    ["Proyecto Terminal", "Seminario de Titulación II", "Optativa II", "Legislación Informática", "Estancia Profesional"],
]
# el plan anterior comparte nombres en 1.º y 2.º (el asistente propone convalidar)
SERIADAS = {"SW201": ["SW101"], "SW303": ["SW105"], "SW401": ["SW301"], "SW601": ["SW501"], "SW702": ["SW602"]}

client = httpx.Client(timeout=60)


def call(method, path, expect=(200, 201, 204), **kwargs):
    response = client.request(method, f"{API}{path}", **kwargs)
    if response.status_code not in expect:
        raise SystemExit(f"{method} {path} -> {response.status_code}: {response.text}")
    return response.json() if response.content else None


def post(path, **body):
    return call("POST", path, json=body)


response = client.post(f"{API}/auth/login", data={"username": EMAIL, "password": PASSWORD})
response.raise_for_status()

campus_id = call("GET", "/catalog/campuses")[0]["id"]
program = post("/catalog/programs", code="ISW", name="Ingeniería en Software", level="licenciatura")


def make_plan(agreement, label, prefix, issue, seriadas):
    rvoe = post("/catalog/rvoes", program_id=program["id"], campus_id=campus_id, agreement_number=agreement,
                authority="federal", modality="escolarizada", issue_date=issue)
    plan = post("/catalog/plan-versions", rvoe_id=rvoe["id"], version_label=label,
                period_type="cuatrimestral", periods_count=9, min_attendance_pct=80)
    subjects, components = {}, {}
    for period, names in enumerate(NAMES, start=1):
        for index, name in enumerate(names, start=1):
            code = f"{prefix}{period}{index:02d}"
            # en el plan viejo solo 1.º y 2.º se llaman igual
            shown = name if prefix == "SW" or period <= 2 else f"{name} (plan {label})"
            subject = post("/catalog/plan-subjects", plan_version_id=plan["id"], code=code, name=shown,
                           period_number=period, credits=6,
                           prerequisite_ids=[subjects[c]["id"] for c in seriadas.get(code, [])])
            subjects[code] = subject
            comps = {}
            for key, kind, label_, weight, seq, counts in [
                ("P1", "parcial", "Parcial 1", 30, 1, True), ("P2", "parcial", "Parcial 2", 30, 2, True),
                ("O", "ordinario", "Ordinario", 40, 3, True),
                ("E1", "extraordinario", "Extraordinario", 0, 4, False),
                ("E2", "titulo_suficiencia", "Título de suficiencia", 0, 5, False),
            ]:
                comps[key] = post("/catalog/evaluation-components", plan_subject_id=subject["id"], kind=kind,
                                  label=label_, weight_pct=weight, sequence=seq,
                                  counts_towards_final=counts)["id"]
            components[code] = comps
    return plan, subjects, components


print("Creando planes…")
old_plan, old_subjects, old_comps = make_plan("RVOE-BC-ISW-M1/18", "2018", "IS", "2018-08-01", {})
plan, subjects, comps = make_plan("RVOE-BC-ISW-M2/25", "2025", "SW", "2025-01-15", SERIADAS)
comps = {**old_comps, **comps}


def term(name, start, end):
    t = post("/catalog/terms", name=name, period_type="cuatrimestral", start_date=start, end_date=end)
    call("PATCH", f"/catalog/terms/{t['id']}", json={"grade_capture_open": True, "is_open": True})
    return t


terms = {
    "24-3": term("2024-3 SEP-DIC", "2024-09-02", "2024-12-13"),
    "25-1": term("2025-1 ENE-ABR", "2025-01-06", "2025-04-25"),
    "25-2": term("2025-2 MAY-AGO", "2025-05-05", "2025-08-22"),
    "25-3": term("2025-3 SEP-DIC", "2025-09-01", "2025-12-12"),
    "26-1": term("2026-1 ENE-ABR", "2026-01-05", "2026-04-24"),
    "26-2": term("2026-2 MAY-AGO", "2026-05-04", "2026-08-21"),
    "26-3": term("2026-3 SEP-DIC", "2026-09-01", "2026-12-11"),
}


def group(code, period, term_key, plan_=None):
    return post("/catalog/groups", code=code, period_number=period,
                plan_version_id=(plan_ or plan)["id"], term_id=terms[term_key]["id"])


student = post("/students", curp="CAST000101HBCSDS09", full_name="ALUMNO TODOS LOS CASOS", campus_id=campus_id)
sid = student["id"]


def enroll(group_, *codes, override=False):
    source = {**old_subjects, **subjects}
    return post("/students/group-enrollments", student_id=sid, group_id=group_["id"],
                plan_subject_ids=[source[c]["id"] for c in codes], override_prerequisites=override)


def add(group_, *codes, override=False):
    return post("/students/group-enrollments/subjects", student_id=sid, group_id=group_["id"],
                plan_subject_ids=[subjects[c]["id"] for c in codes], override_prerequisites=override)


def kardex():
    return call("GET", f"/grades/students/{sid}/kardex-completo")


def row(code, group_code=None):
    k = kardex()
    rows = k["rows"] + [r for p in k["previous"] for r in p["rows"]]
    found = [r for r in rows if r["code"] == code and r["subject_enrollment_id"]
             and (group_code is None or r["group_code"] == group_code)]
    if not found:
        raise SystemExit(f"No está en el kárdex: {code} {group_code}")
    return found[-1]


def grade(code, group_code=None, **values):
    se = row(code, group_code)["subject_enrollment_id"]
    for key in ("P1", "P2", "O", "E1", "E2"):
        if key in values:
            post("/grades/capture", subject_enrollment_id=se, component_id=comps[code][key], value=values[key])
    return se


def ordinary(code, value, group_code=None):
    return grade(code, group_code, P1=value, P2=value, O=value)


def recognize(plan_id, *items):
    return post(f"/students/{sid}/recognitions", plan_version_id=plan_id, items=list(items))


def eq(code, kind, value=None, origin=""):
    return {"plan_subject_id": subjects[code]["id"], "kind": kind, "grade": value, "origin": origin}


CERT = "Certificado parcial · Universidad Ejemplo · RVOE 2015-77"
DICT = "Dictamen SEP 123/2026"

print("Plan anterior…")
g = group("IS18-1A", 1, "24-3", old_plan)
enroll(g)
for code, value in [("IS101", 9), ("IS102", 8), ("IS103", 10), ("IS105", 9)]:
    ordinary(code, value)
grade("IS104", P1=5, P2=5, O=5, E1=8)  # plan anterior: aprobada en extraordinario

g = group("IS18-2A", 2, "25-1", old_plan)
enroll(g)
for code, value in [("IS201", 9), ("IS202", 8), ("IS204", 7), ("IS205", 9)]:
    ordinary(code, value)
ordinary("IS203", 5)  # plan anterior: reprobada, se queda así

g = group("IS18-3A", 3, "25-2", old_plan)
enroll(g)  # en curso al cambiar de RVOE: esas materias quedan de baja
grade("IS301", P1=8)

print("Cambio de RVOE equivocado y su reversa…")
g2 = group("SW-2A", 2, "25-2")
g3a = group("SW-3A", 3, "25-2")
post(f"/students/{sid}/rvoe-change", from_plan_version_id=old_plan["id"], target_group_id=g3a["id"], decisions=[
    {"plan_subject_id": subjects["SW105"]["id"], "action": "eq"},  # SW303 la pide (seriación)
])
post(f"/students/{sid}/rvoe-change/revert", change_id=kardex()["rvoe_change"]["change_id"],
     reason="Se aplicó sin convalidar (demostración)")

print("Cambio de RVOE correcto…")
sources = {a["code"]: a for a in call(
    "GET", f"/students/{sid}/rvoe-change/proposal",
    params={"from_plan_version_id": old_plan["id"], "target_group_id": g3a["id"]})["approved"]}


def decide(code, action, source=None, value=None, group_id=None):
    return {"plan_subject_id": subjects[code]["id"], "action": action, "grade": value, "group_id": group_id,
            "source_subject_enrollment_id": sources[source]["subject_enrollment_id"] if source else None}


post(f"/students/{sid}/rvoe-change", from_plan_version_id=old_plan["id"], target_group_id=g3a["id"], decisions=[
    decide("SW101", "conv", "IS101", 9),
    decide("SW102", "eq", "IS102", 8),
    decide("SW103", "rev", "IS103", 10),
    decide("SW104", "eq", "IS104"),   # EQ sin nota, pendiente de la autoridad
    decide("SW105", "rev", "IS105"),  # REV sin nota; cumple la seriación de SW303
    decide("SW201", "conv", "IS201", 9),
    decide("SW202", "cursar", group_id=g2["id"]),  # cursar ahora, en otro grupo
    decide("SW203", "pendiente"),
    decide("SW204", "pendiente"),
    decide("SW205", "pendiente"),
    decide("SW801", "conv", "IS205", 9),  # adelantada: de 8.º, reconocida desde el otro RVOE
])

print("Reconocimientos externos…")
recognize(plan["id"],
          eq("SW204", "eq", None, CERT),   # se corrige después a CONV con nota
          eq("SW205", "rev", 5, CERT),     # reconocida reprobada; se recursa después
          eq("SW802", "eq", None, DICT),   # adelantadas, sin estar en esos cuatrimestres
          eq("SW803", "rev", 9, DICT),
          eq("SW901", "eq", 8, CERT),
          eq("SW902", "conv", None, DICT),
          eq("SW905", "eq", None, "Marcada por error"))
call("PATCH", f"/students/subject-enrollments/{row('SW204')['subject_enrollment_id']}/recognition",
     json={"kind": "conv", "grade": 8.5, "origin": DICT, "reason": "Era convalidación (demostración)"})
post(f"/students/subject-enrollments/{row('SW905')['subject_enrollment_id']}/recognition/undo",
     reason="No debía reconocerse (demostración)")

print("3.er cuatrimestre…")
ordinary("SW202", 8)
ordinary("SW301", 9)
grade("SW302", P1=5, P2=5, O=5, E1=8)        # aprobada en extraordinario
grade("SW303", P1=4, P2=4, O=4, E1=5, E2=7)  # aprobada en título de suficiencia
ordinary("SW304", 5)                          # reprobada; recursa en su propio grupo
grade("SW305", P1=3, P2=3, O=3, E1=4, E2=5)   # reprobada en todo; recursa en otro grupo

print("4.º cuatrimestre…")
g = group("SW-4A", 4, "25-3")
enroll(g)
se401 = ordinary("SW401", 6)
post(f"/grades/subject-enrollments/{se401}/correct", reason=REASON, components=[
    {"component_id": comps["SW401"][k], "value": 9} for k in ("P1", "P2", "O")])  # nota corregida
post("/students/subject-enrollments/drop", subject_enrollment_ids=[row("SW402")["subject_enrollment_id"]],
     reason="Baja a petición del alumno")  # la debe: sigue pendiente en su periodo
post("/students/subject-enrollments/drop", subject_enrollment_ids=[row("SW403")["subject_enrollment_id"]],
     reason="Baja por error")
add(g, "SW403")  # se reinscribe en el mismo grupo
ordinary("SW403", 8)
post(f"/grades/subject-enrollments/{row('SW404')['subject_enrollment_id']}/correct",
     reason="Historial cargado, sin parciales", final_grade=7.5)
se405 = ordinary("SW405", 4)
refused = client.post(f"{API}/students/{sid}/recognitions", json={
    "plan_version_id": plan["id"], "items": [eq("SW405", "eq", 8, DICT)]})
assert refused.status_code == 409 and "evaluaciones registradas" in refused.text, refused.text
post(f"/grades/subject-enrollments/{se405}/correct", reason="Se dictaminó por equivalencia", components=[
    {"component_id": comps["SW405"][k], "value": None} for k in ("P1", "P2", "O")])
recognize(plan["id"], eq("SW405", "eq", 8, DICT))  # ya sin evaluaciones sí se puede

print("5.º cuatrimestre, con cambio de grupo…")
g5a, g5b = group("SW-5A", 5, "26-1"), group("SW-5B", 5, "26-1")
enroll(g5a)
grade("SW501", P1=8)
post(f"/students/{sid}/group-change", from_group_id=g5a["id"], to_group_id=g5b["id"], reason="Cambio de turno")
grade("SW501", P2=8, O=8)  # conserva el parcial capturado en el grupo anterior
ordinary("SW502", 9)
ordinary("SW503", 7)
grade("SW504", P1=5, P2=5, O=5, E1=7)
ordinary("SW505", 5)  # reprobada, sin recursar todavía
add(g5b, "SW304", "SW205")  # recursamiento en su propio grupo
ordinary("SW304", 8, "SW-5B")
ordinary("SW205", 8, "SW-5B")

print("6.º cuatrimestre, con recursamiento en otro grupo…")
g = group("SW-6A", 6, "26-2")
enroll(g)
ordinary("SW601", 9)
grade("SW602", P1=4, P2=4, O=4, E1=5)  # reprobada; es seriada de SW702
ordinary("SW603", 10)
ordinary("SW604", 8)
grade("SW605", P1=5, P2=5, O=5, E1=4, E2=9)
g3b = group("SW-3B", 3, "26-2")
enroll(g3b, "SW305")  # recursamiento en un grupo más bajo
ordinary("SW305", 5, "SW-3B")  # vuelve a reprobar

print("7.º cuatrimestre, el actual…")
g7 = group("SW-7A", 7, "26-3")
enroll(g7, override=True)  # SW702 pide SW602, reprobada: seriación omitida
grade("SW702", P1=8)
grade("SW703", P1=7, P2=9)
recognize(plan["id"], eq("SW704", "eq", None, DICT))  # la llevaba en su grupo: se reemplaza
post("/students/subject-enrollments/drop", subject_enrollment_ids=[row("SW705", "SW-7A")["subject_enrollment_id"]],
     reason="Baja en el periodo actual")
add(g7, "SW203")  # materia anterior nunca tomada: primer intento, no recursamiento
g3c = group("SW-3C", 3, "26-3")
enroll(g3c, "SW305")  # tercer intento, en curso

for key, t in terms.items():
    current = key == "26-3"
    call("PATCH", f"/catalog/terms/{t['id']}", json={"grade_capture_open": current, "is_open": current})

k = kardex()
current = call("GET", f"/students/{sid}/current-group")
print(f"\nAlumno {student['enrollment_number']} · grupo {current['code']} ({current['period_number']}.º)")
print(k["progress"])
for r in k["rows"]:
    print(f"{r['period_number']}.º {r['code']} {str(r['group_code'] or '-'):16} int.{r['attempt_number'] or '-'} "
          f"{r['status']:10} CF={r['cf']} E1={r['e1']} E2={r['e2']} final={r['final_grade']} "
          f"{(r['recognition'] or '').upper():4} {r['origin'] or ''}")
for p in k["previous"]:
    print(f"\nAnterior {p['rvoe']}")
    for r in p["rows"]:
        print(f"  {r['code']} {r['group_code']} {r['status']} final={r['final_grade']}")
