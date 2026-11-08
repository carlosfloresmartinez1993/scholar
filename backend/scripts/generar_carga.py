"""Base simulada para medir rendimiento: 7,000 alumnos con historial, 8,000 usuarios
y una bitácora grande. Inserta directo en la base; solo acepta una base cuyo nombre
termine en "_carga", para no tocar nunca la de trabajo.

    POSTGRES_DB=scholar_carga uv run python scripts/generar_carga.py
"""
import asyncio
import random
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import insert, text
from sqlmodel import select

from app.core.config import settings
from app.core.db import async_session_factory, engine
from app.core.security import get_password_hash
from app.models import (
    AuditLog,
    Campus,
    EvaluationComponent,
    Grade,
    Group,
    GroupEnrollment,
    GroupSubject,
    Institution,
    PlanChange,
    PlanSubject,
    PlanVersion,
    Program,
    Rvoe,
    Student,
    StudentPlanEnrollment,
    SubjectEnrollment,
    SubjectRecognition,
    Term,
    User,
)

STUDENTS = 7000
STAFF = 1000
PROGRAMS = 12
PERIODS = 9
SUBJECTS = 5
TERMS = 9
GROUPS_PER_PERIOD = 2
AUDIT_ROWS = 1_000_000
BATCH = 5000

assert settings.POSTGRES_DB.endswith("_carga"), "Solo sobre una base *_carga"
engine.echo = False
rng = random.Random(7)
uid = uuid.uuid4


def weights():
    return {"P1": 30, "P2": 30, "O": 40}


async def bulk(session, model, rows):
    for start in range(0, len(rows), BATCH):
        await session.execute(insert(model), rows[start:start + BATCH])
    print(f"  {model.__tablename__}: {len(rows):,}", flush=True)


async def main():
    async with async_session_factory() as session:
        institution = (await session.exec(select(Institution))).first()
        admin = (await session.exec(select(User))).first()
        first_campus = (await session.exec(select(Campus))).first()
        campuses = [first_campus.id]
        rows = [{"id": uid(), "institution_id": institution.id, "name": f"Campus {n}"} for n in (2, 3)]
        await bulk(session, Campus, rows)
        campuses += [r["id"] for r in rows]

        today = date.today()
        terms = []
        for i in range(TERMS):  # the last one is the current one
            start = today - timedelta(days=(TERMS - 1 - i) * 120 + 60)
            terms.append({
                "id": uid(), "institution_id": institution.id, "name": f"CARGA-{i + 1}",
                "period_type": "cuatrimestral", "start_date": start, "end_date": start + timedelta(days=105),
                "is_open": i == TERMS - 1, "grade_capture_open": i == TERMS - 1,
            })
        next_term = {
            "id": uid(), "institution_id": institution.id, "name": "CARGA-SIGUIENTE",
            "period_type": "cuatrimestral", "start_date": today + timedelta(days=5),
            "end_date": today + timedelta(days=110), "is_open": True, "grade_capture_open": False,
        }
        await bulk(session, Term, terms + [next_term])

        programs, rvoes, plans, subjects, components, groups, group_subjects = [], [], [], [], [], [], []
        plan_info = []
        for p in range(PROGRAMS):
            program_id, rvoe_id, plan_id = uid(), uid(), uid()
            campus = campuses[p % len(campuses)]
            programs.append({"id": program_id, "institution_id": institution.id, "code": f"C{p}", "name": f"Carrera {p}", "level": "licenciatura"})
            rvoes.append({"id": rvoe_id, "program_id": program_id, "campus_id": campus,
                          "agreement_number": f"RVOE-CARGA-{p}", "authority": "federal",
                          "modality": "escolarizada", "issue_date": date(2015, 1, 1)})
            plans.append({"id": plan_id, "rvoe_id": rvoe_id, "version_label": "2015",
                          "period_type": "cuatrimestral", "periods_count": PERIODS, "min_attendance_pct": 80})
            by_period, comps = {}, {}
            for period in range(1, PERIODS + 1):
                for s in range(1, SUBJECTS + 1):
                    subject_id = uid()
                    subjects.append({"id": subject_id, "plan_version_id": plan_id,
                                     "code": f"C{p}-{period}{s:02d}", "name": f"Materia {period}.{s} de C{p}",
                                     "period_number": period, "credits": 6})
                    by_period.setdefault(period, []).append(subject_id)
                    entry = {}
                    for key, kind, label, weight, seq, counts in [
                        ("P1", "parcial", "Parcial 1", 30, 1, True), ("P2", "parcial", "Parcial 2", 30, 2, True),
                        ("O", "ordinario", "Ordinario", 40, 3, True),
                        ("E1", "extraordinario", "Extraordinario", 0, 4, False),
                        ("E2", "titulo_suficiencia", "Título", 0, 5, False),
                    ]:
                        entry[key] = uid()
                        components.append({"id": entry[key], "plan_subject_id": subject_id, "kind": kind,
                                           "label": label, "weight_pct": weight, "sequence": seq,
                                           "counts_towards_final": counts})
                    comps[subject_id] = entry
            group_index, gs_index = {}, {}
            for t, term in enumerate(terms):
                for period in range(1, PERIODS + 1):
                    for letter in "AB"[:GROUPS_PER_PERIOD]:
                        group_id = uid()
                        groups.append({"id": group_id, "plan_version_id": plan_id, "term_id": term["id"],
                                       "campus_id": campus, "code": f"C{p}-{period}{letter}-{t}",
                                       "period_number": period, "is_active": True})
                        group_index[(t, period, letter)] = group_id
                        for subject_id in by_period[period]:
                            gs_id = uid()
                            group_subjects.append({"id": gs_id, "group_id": group_id, "plan_subject_id": subject_id})
                            gs_index[(group_id, subject_id)] = gs_id
            for period in range(1, PERIODS):  # the coming term, linked for the promotion
                for letter in "AB"[:GROUPS_PER_PERIOD]:
                    group_id = uid()
                    groups.append({"id": group_id, "plan_version_id": plan_id, "term_id": next_term["id"],
                                   "campus_id": campus, "code": f"C{p}-{period + 1}{letter}-N",
                                   "period_number": period + 1, "is_active": True,
                                   "promotes_from_group_id": group_index[(TERMS - 1, period, letter)]})
                    for subject_id in by_period[period + 1]:
                        group_subjects.append({"id": uid(), "group_id": group_id, "plan_subject_id": subject_id})
            plan_info.append({"id": plan_id, "campus": campus, "by_period": by_period, "comps": comps,
                              "groups": group_index, "gs": gs_index})
        await bulk(session, Program, programs)
        await bulk(session, Rvoe, rvoes)
        await bulk(session, PlanVersion, plans)
        await bulk(session, PlanSubject, subjects)
        await bulk(session, EvaluationComponent, components)
        await bulk(session, Group, groups)
        await bulk(session, GroupSubject, group_subjects)
        await session.commit()

        students, users, plan_enrollments, group_enrollments, subject_enrollments, grades = [], [], [], [], [], []
        recognitions, internal_groups, internal_gs, plan_changes = [], {}, {}, []
        password = get_password_hash("carga-no-es-real")
        now = datetime.utcnow()
        for n in range(STUDENTS):
            info = plan_info[n % PROGRAMS]
            entered = rng.randrange(TERMS)
            letter = "AB"[n % GROUPS_PER_PERIOD]
            student_id, plan_enrollment_id = uid(), uid()
            students.append({"id": student_id, "institution_id": institution.id, "campus_id": info["campus"],
                             "curp": f"CARG{n:06d}HBCRGA{n % 100:02d}", "enrollment_number": f"C{n:07d}",
                             "full_name": f"Alumno {rng.choice('ABCDEFGHIJKLMNOP')}{n:05d} Simulado"})
            users.append({"id": uid(), "email": f"alumno{n}@carga-simulada.mx", "full_name": f"Alumno {n}",
                          "role": "alumno", "hashed_password": password, "student_id": student_id})
            plan_enrollments.append({"id": plan_enrollment_id, "student_id": student_id, "plan_version_id": info["id"],
                                     "start_term_id": terms[entered]["id"]})
            seen = set()

            def group_enrollment(group_id):
                ge_id = uid()
                seen.add(group_id)
                group_enrollments.append({"id": ge_id, "student_id": student_id, "group_id": group_id,
                                          "plan_enrollment_id": plan_enrollment_id, "kind": "inscripcion"})
                return ge_id

            def take(ge_id, group_id, subject_id, attempt, passing, current):
                se_id = uid()
                value = None if current else (rng.choice([7, 8, 9, 10]) if passing else 5)
                subject_enrollments.append({
                    "id": se_id, "group_enrollment_id": ge_id, "group_subject_id": info["gs"][(group_id, subject_id)],
                    "student_id": student_id, "attempt_number": attempt,
                    "status": "cursando" if current else ("aprobada" if passing else "reprobada"),
                    "final_grade": value,
                })
                if not current:
                    for key in ("P1", "P2", "O"):
                        grades.append({"id": uid(), "subject_enrollment_id": se_id,
                                       "component_id": info["comps"][subject_id][key], "value": value,
                                       "captured_by": admin.id})

            recognizes = n % 10 < 4  # 40%: EQ/REV/CONV, some through a cambio de RVOE
            start_period = 1
            for t in range(entered, TERMS):
                period = min(PERIODS, start_period + t - entered)
                group_id = info["groups"][(t, period, letter)]
                ge_id = group_enrollment(group_id)
                for subject_id in info["by_period"][period]:
                    current = t == TERMS - 1
                    passing = current or rng.random() > 0.08
                    take(ge_id, group_id, subject_id, 1, passing, current)
                    if not passing and t + 1 < TERMS:  # recursamiento next term, in a lower group
                        other = "A" if letter == "B" else "B"
                        retake_group = info["groups"][(t + 1, period, other)]
                        if retake_group not in seen:
                            retake_ge = group_enrollment(retake_group)
                        else:
                            retake_ge = next(g["id"] for g in reversed(group_enrollments)
                                             if g["group_id"] == retake_group and g["student_id"] == student_id)
                        take(retake_ge, retake_group, subject_id, 2, True, t + 1 == TERMS - 1)
            if recognizes and entered > 0:
                # subjects ahead of where they stand, recognized from a certificate
                top = min(PERIODS, TERMS - entered + 1)
                if top <= PERIODS:
                    key = (info["id"], top)
                    if key not in internal_groups:
                        internal_groups[key] = {"id": uid(), "plan_version_id": info["id"],
                                                "term_id": terms[-1]["id"], "campus_id": info["campus"],
                                                "code": f"C{n % PROGRAMS}-INT{top}-EQ", "period_number": 1,
                                                "is_active": False}
                    internal = internal_groups[key]
                    ge_id = group_enrollment(internal["id"])
                    for subject_id in info["by_period"][top]:
                        if (internal["id"], subject_id) not in internal_gs:
                            internal_gs[(internal["id"], subject_id)] = {
                                "id": uid(), "group_id": internal["id"], "plan_subject_id": subject_id}
                        se_id = uid()
                        pending = rng.random() < 0.3
                        subject_enrollments.append({
                            "id": se_id, "group_enrollment_id": ge_id,
                            "group_subject_id": internal_gs[(internal["id"], subject_id)]["id"],
                            "student_id": student_id, "attempt_number": 1,
                            "status": "cursando" if pending else "aprobada",
                            "final_grade": None if pending else 8,
                        })
                        recognitions.append({"subject_enrollment_id": se_id,
                                             "origin": "Certificado parcial · Universidad simulada"})
            if n % 20 == 0:  # 5%: came from another plan
                previous = plan_info[(n + 1) % PROGRAMS]
                from_id = uid()
                plan_enrollments.append({"id": from_id, "student_id": student_id, "plan_version_id": previous["id"],
                                         "start_term_id": terms[0]["id"], "status": "baja"})
                plan_changes.append({"id": uid(), "student_id": student_id, "from_plan_enrollment_id": from_id,
                                     "to_plan_enrollment_id": plan_enrollment_id, "changed_by": "carga",
                                     "detail": {}, "created_at": now})
        for n in range(STAFF):
            users.append({"id": uid(), "email": f"staff{n}@carga-simulada.mx", "full_name": f"Docente {n}",
                          "role": "docente", "hashed_password": password})
        await bulk(session, Group, list(internal_groups.values()))
        await bulk(session, GroupSubject, list(internal_gs.values()))
        await bulk(session, Student, students)
        await bulk(session, User, users)
        await bulk(session, StudentPlanEnrollment, plan_enrollments)
        await bulk(session, GroupEnrollment, group_enrollments)
        await bulk(session, SubjectEnrollment, subject_enrollments)
        await bulk(session, Grade, grades)
        await bulk(session, SubjectRecognition, recognitions)
        await bulk(session, PlanChange, plan_changes)
        await session.commit()

        actions = ["grade.captured", "grade.updated", "subject_enrollment.added", "group_enrollment.created",
                   "charges.generated", "term.updated"]
        for start in range(0, AUDIT_ROWS, 50_000):
            await session.execute(insert(AuditLog), [
                {"id": uid(), "actor": "carga", "action": rng.choice(actions), "entity": "grade",
                 "entity_id": str(uid()), "detail": "registro simulado de la bitácora",
                 "created_at": now - timedelta(minutes=rng.randrange(60 * 24 * 900))}
                for _ in range(50_000)
            ])
            await session.commit()
        print(f"  audit_logs: {AUDIT_ROWS:,}", flush=True)
        await session.execute(text("ANALYZE"))
        await session.commit()


asyncio.run(main())
