"""Registro de egresados y su dashboard: quién egresó, de qué plan, en qué
periodo, y si el título quedó registrado (RF-C09).

Nothing writes an egreso date today, so the period is derived from the last term
the student was enrolled in — these tests pin that derivation down.
"""
from httpx import AsyncClient

from tests.conftest import login
from tests.test_academic_flow import CURP_A, CURP_B, build_catalog


async def _student(client: AsyncClient, campus_id: str, curp: str, name: str) -> dict:
    response = await client.post("/api/v1/students", json={
        "curp": curp, "full_name": name, "campus_id": campus_id,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _enroll(client: AsyncClient, student_id: str, group_id: str) -> dict:
    response = await client.post("/api/v1/students/group-enrollments", json={
        "student_id": student_id, "group_id": group_id, "waive_enrollment_fee": True,
        # these tests care about which term someone was in, not about seriación
        "override_prerequisites": True,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _graduate(client: AsyncClient, student_id: str) -> None:
    response = await client.patch(
        f"/api/v1/students/{student_id}", json={"status": "egresado"}
    )
    assert response.status_code == 200, response.text


async def _alumni(client: AsyncClient, **params) -> list[dict]:
    response = await client.get("/api/v1/alumni", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _stats(client: AsyncClient, **params) -> dict:
    response = await client.get("/api/v1/alumni/stats", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_graduate_is_listed_with_derived_period_and_plan(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await _student(client, campus_id, CURP_A, "Ana Egresada")
    await _enroll(client, student["id"], catalog["group"]["id"])
    await _graduate(client, student["id"])

    rows = await _alumni(client)
    assert len(rows) == 1
    row = rows[0]
    assert row["student_id"] == student["id"]
    assert row["program_name"] == catalog["program"]["name"]
    assert row["level"] == "licenciatura"
    assert row["plan_version_label"] == catalog["plan"]["version_label"]
    assert row["rvoe"] == catalog["rvoe"]["agreement_number"]
    # the period is derived from the last term they were enrolled in
    assert row["egreso_term_id"] == catalog["term"]["id"]
    assert row["egreso_term_name"] == catalog["term"]["name"]
    assert row["egreso_date"] == catalog["term"]["end_date"]
    assert row["titulado"] is False
    assert row["degree"] is None


async def test_active_student_is_not_an_alumnus(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await _student(client, campus_id, CURP_A, "Beto Cursando")
    await _enroll(client, student["id"], catalog["group"]["id"])

    assert await _alumni(client) == []
    assert (await _stats(client))["egresados"] == 0


async def test_period_is_the_last_term_not_the_first(client, seed):
    """Someone who studied two cuatrimestres egresó in the second one."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    later_term = (await client.post("/api/v1/catalog/terms", json={
        "name": "2027-1", "period_type": "cuatrimestral",
        "start_date": "2027-01-10", "end_date": "2027-04-30",
    })).json()
    later_group = (await client.post("/api/v1/catalog/groups", json={
        "code": "LD-2A", "period_number": 2,
        "plan_version_id": catalog["plan"]["id"], "term_id": later_term["id"],
    })).json()

    student = await _student(client, campus_id, CURP_A, "Ana Egresada")
    await _enroll(client, student["id"], catalog["group"]["id"])
    await _enroll(client, student["id"], later_group["id"])
    await _graduate(client, student["id"])

    row = (await _alumni(client))[0]
    assert row["egreso_term_id"] == later_term["id"]
    assert row["egreso_date"] == later_term["end_date"]


async def test_registered_degree_marks_the_row_titulado(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await _student(client, campus_id, CURP_A, "Ana Titulada")
    await _enroll(client, student["id"], catalog["group"]["id"])
    await _graduate(client, student["id"])

    # program_name is free text on the libro de títulos — matched by folded name
    degree = await client.post("/api/v1/grades/degree-records", json={
        "student_id": student["id"], "kind": "titulo",
        "program_name": "licenciatura EN derecho",  # same program, different casing
        "issue_date": "2027-06-01",
    })
    assert degree.status_code == 201, degree.text

    row = (await _alumni(client))[0]
    assert row["titulado"] is True
    assert row["degree"]["folio"] == degree.json()["folio"]
    assert row["degree"]["kind"] == "titulo"

    stats = await _stats(client)
    assert stats["egresados"] == 1
    assert stats["titulados"] == 1
    assert stats["titulacion_pct"] == 100.0


async def test_graduate_without_plan_enrollment_is_kept_not_dropped(client, seed):
    """Marked egresado by hand, never enrolled: the row is incomplete, not
    missing — dropping it would quietly shrink the count."""
    await login(client)
    campus_id = str(seed["campus"].id)
    student = await _student(client, campus_id, CURP_A, "Carlos Sin Plan")
    await _graduate(client, student["id"])

    rows = await _alumni(client)
    assert len(rows) == 1
    assert rows[0]["student_id"] == student["id"]
    assert rows[0]["program_id"] is None
    assert rows[0]["egreso_term_id"] is None

    stats = await _stats(client)
    assert stats["egresados"] == 1
    assert stats["sin_plan"] == 1
    assert stats["sin_periodo"] == 1
    assert [b["term_name"] for b in stats["by_term"]] == ["Sin periodo"]
    assert [b["program_name"] for b in stats["by_program"]] == ["Sin plan"]


async def test_stats_count_students_and_bucket_by_period(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    for curp, name in ((CURP_A, "Ana"), (CURP_B, "Bruno")):
        student = await _student(client, campus_id, curp, name)
        await _enroll(client, student["id"], catalog["group"]["id"])
        await _graduate(client, student["id"])

    stats = await _stats(client)
    assert stats["egresados"] == 2
    assert stats["titulados"] == 0
    assert stats["titulacion_pct"] == 0.0
    assert len(stats["by_term"]) == 1
    assert stats["by_term"][0]["term_id"] == catalog["term"]["id"]
    assert stats["by_term"][0]["egresados"] == 2
    assert stats["by_program"][0]["egresados"] == 2


async def test_filters_narrow_both_the_list_and_the_cards(client, seed):
    """The cards describe the table below them, so both take the same filters."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    titulado = await _student(client, campus_id, CURP_A, "Ana Titulada")
    await _enroll(client, titulado["id"], catalog["group"]["id"])
    await _graduate(client, titulado["id"])
    await client.post("/api/v1/grades/degree-records", json={
        "student_id": titulado["id"], "kind": "titulo",
        "program_name": catalog["program"]["name"], "issue_date": "2027-06-01",
    })
    pasante = await _student(client, campus_id, CURP_B, "Bruno Pasante")
    await _enroll(client, pasante["id"], catalog["group"]["id"])
    await _graduate(client, pasante["id"])

    assert [r["student_id"] for r in await _alumni(client, titulado=True)] == [titulado["id"]]
    assert [r["student_id"] for r in await _alumni(client, titulado=False)] == [pasante["id"]]
    assert (await _stats(client, titulado=True))["egresados"] == 1
    assert (await _stats(client))["egresados"] == 2

    assert len(await _alumni(client, term_id=catalog["term"]["id"])) == 2
    assert await _alumni(client, q="Bruno") == [
        r for r in await _alumni(client) if r["student_id"] == pasante["id"]
    ]


async def test_alumni_are_confined_to_the_members_campuses(client, seed):
    """A member of one campus must not read another campus' graduates."""
    await login(client)
    campus_a = str(seed["campus"].id)
    campus_b = (await client.post("/api/v1/catalog/campuses", json={
        "name": "Campus Tijuana",
    })).json()["id"]
    for campus_id, curp, name in (
        (campus_a, CURP_A, "Ana Ensenada"),
        (campus_b, CURP_B, "Bruno Tijuana"),
    ):
        student = await _student(client, campus_id, curp, name)
        await _graduate(client, student["id"])
    assert len(await _alumni(client)) == 2  # superuser sees both

    await client.post("/api/v1/users", json={
        "email": "member@inue.edu.mx", "full_name": "Member A",
        "role": "servicios_escolares", "password": "memberpass1",
        "campuses": [campus_a],
    })
    await login(client, "member@inue.edu.mx", "memberpass1")

    rows = await _alumni(client)
    assert [r["full_name"] for r in rows] == ["Ana Ensenada"]
    assert (await _stats(client))["egresados"] == 1

    # asking for a campus outside membership is 403, not a silent empty list
    assert (await client.get("/api/v1/alumni", params={"campus_id": campus_b})).status_code == 403


# --- regressions found in review ------------------------------------------------

async def _second_plan(client: AsyncClient, campus_id: str) -> dict:
    """A second program + RVOE + plan + later term + group, for the students who
    finish one program and start another."""
    program = (await client.post("/api/v1/catalog/programs", json={
        "code": "MF", "name": "Maestría en Fiscal", "level": "maestria",
    })).json()
    rvoe = (await client.post("/api/v1/catalog/rvoes", json={
        "program_id": program["id"], "campus_id": campus_id,
        "agreement_number": "20260002", "authority": "federal",
        "modality": "escolarizada", "issue_date": "2026-01-15",
    })).json()
    plan = (await client.post("/api/v1/catalog/plan-versions", json={
        "rvoe_id": rvoe["id"], "version_label": "2026", "period_type": "cuatrimestral",
        "periods_count": 6, "min_attendance_pct": 80,
    })).json()
    await client.post("/api/v1/catalog/plan-subjects", json={
        "plan_version_id": plan["id"], "code": "FIS101",
        "name": "Derecho Fiscal I", "period_number": 1, "credits": 8,
    })
    term = (await client.post("/api/v1/catalog/terms", json={
        "name": "2028-1", "period_type": "cuatrimestral",
        "start_date": "2028-01-10", "end_date": "2028-04-30",
    })).json()
    group = (await client.post("/api/v1/catalog/groups", json={
        "code": "MF-1A", "period_number": 1,
        "plan_version_id": plan["id"], "term_id": term["id"],
    })).json()
    return {"program": program, "plan": plan, "term": term, "group": group}


async def test_period_belongs_to_the_plan_not_to_the_person(client, seed):
    """A graduate who is now studying a maestría must not have their licenciatura
    dated by the maestría's current term."""
    await login(client)
    campus_id = str(seed["campus"].id)
    lic = await build_catalog(client, campus_id)
    mae = await _second_plan(client, campus_id)

    student = await _student(client, campus_id, CURP_A, "Ana Continúa")
    await _enroll(client, student["id"], lic["group"]["id"])   # term 2026-2
    await _enroll(client, student["id"], mae["group"]["id"])   # term 2028-1
    await _graduate(client, student["id"])

    rows = await _alumni(client)
    by_program = {r["program_name"]: r for r in rows}
    assert by_program[lic["program"]["name"]]["egreso_term_name"] == lic["term"]["name"]
    assert by_program[mae["program"]["name"]]["egreso_term_name"] == mae["term"]["name"]


async def _mark_plan_graduated(session_factory, plan_version_id: str) -> None:
    """Set StudentPlanEnrollment.status directly. Nothing in the API writes it
    today — the graduated plan states arrive by legacy import — and that is
    precisely the population the alumni registry exists to surface."""
    import uuid as _uuid

    from sqlmodel import select as _select

    from app.models import PlanEnrollmentStatus, StudentPlanEnrollment

    async with session_factory() as session:
        enrollment = (
            await session.exec(
                _select(StudentPlanEnrollment).where(
                    StudentPlanEnrollment.plan_version_id == _uuid.UUID(plan_version_id)
                )
            )
        ).first()
        enrollment.status = PlanEnrollmentStatus.egresado
        session.add(enrollment)
        await session.commit()


async def test_program_filter_cannot_invent_a_graduate(client, seed, session_factory):
    """Filtering by a program the student is only ENROLLED in must not turn that
    enrollment into an alumni row the unfiltered registry never contained."""
    await login(client)
    campus_id = str(seed["campus"].id)
    lic = await build_catalog(client, campus_id)
    mae = await _second_plan(client, campus_id)

    student = await _student(client, campus_id, CURP_A, "Ana Continúa")
    await _enroll(client, student["id"], lic["group"]["id"])
    await _enroll(client, student["id"], mae["group"]["id"])
    # finished the licenciatura, still studying the maestría
    await _mark_plan_graduated(session_factory, lic["plan"]["id"])
    await _graduate(client, student["id"])  # Student.status also says egresado

    unfiltered = await _alumni(client)
    assert [r["program_name"] for r in unfiltered] == [lic["program"]["name"]]

    # the maestría is not something she egresó from — filtering by it finds nobody
    assert await _alumni(client, program_id=mae["program"]["id"]) == []
    assert (await _stats(client, program_id=mae["program"]["id"]))["egresados"] == 0

    filtered = await _alumni(client, program_id=lic["program"]["id"])
    assert [r["plan_enrollment_id"] for r in filtered] == [
        unfiltered[0]["plan_enrollment_id"]
    ]


async def test_an_unrelated_degree_does_not_certify_a_program(client, seed):
    """A diplomado in the libro de títulos is not a título in the program the
    student actually finished."""
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    student = await _student(client, campus_id, CURP_A, "Ana Pasante")
    await _enroll(client, student["id"], catalog["group"]["id"])
    await _graduate(client, student["id"])

    await client.post("/api/v1/grades/degree-records", json={
        "student_id": student["id"], "kind": "diploma",
        "program_name": "Diplomado en Juicios Orales",  # matches no plan
        "issue_date": "2027-06-01",
    })

    row = (await _alumni(client))[0]
    assert row["titulado"] is False
    assert row["degree"] is None
    assert (await _stats(client))["titulados"] == 0


async def test_a_degree_for_one_program_does_not_certify_the_other(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    lic = await build_catalog(client, campus_id)
    mae = await _second_plan(client, campus_id)
    student = await _student(client, campus_id, CURP_A, "Ana Dos Planes")
    await _enroll(client, student["id"], lic["group"]["id"])
    await _enroll(client, student["id"], mae["group"]["id"])
    await _graduate(client, student["id"])

    await client.post("/api/v1/grades/degree-records", json={
        "student_id": student["id"], "kind": "titulo",
        "program_name": lic["program"]["name"], "issue_date": "2027-06-01",
    })

    by_program = {r["program_name"]: r for r in await _alumni(client)}
    assert by_program[lic["program"]["name"]]["titulado"] is True
    assert by_program[mae["program"]["name"]]["titulado"] is False
    assert by_program[mae["program"]["name"]]["degree"] is None


async def test_sin_periodo_counts_students_like_egresados_does(client, seed):
    """Both numbers are printed one under the other, so they have to be in the
    same unit — 'Egresados 1' above '2 sin periodo' contradicts itself."""
    await login(client)
    campus_id = str(seed["campus"].id)
    lic = await build_catalog(client, campus_id)
    mae = await _second_plan(client, campus_id)
    student = await _student(client, campus_id, CURP_A, "Ana Sin Grupos")
    # two plan enrollments, no group enrollment in either
    for plan_id in (lic["plan"]["id"], mae["plan"]["id"]):
        response = await client.post("/api/v1/students/plan-enrollments", json={
            "student_id": student["id"], "plan_version_id": plan_id,
            "start_term_id": lic["term"]["id"],
        })
        assert response.status_code == 201, response.text
    await _graduate(client, student["id"])

    stats = await _stats(client)
    assert len(await _alumni(client)) == 2  # two rows, one person
    assert stats["egresados"] == 1
    assert stats["rows"] == 2
    assert stats["sin_periodo"] == 1  # students, not rows
