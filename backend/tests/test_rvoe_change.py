"""Cambio de RVOE: propuesta materia por materia, aplicación (cierra el plan
anterior, inscribe al grupo destino, convalida / EQ / cursar ahora / pendiente) y un
solo historial en el kárdex, incluso al cambiar de carrera."""
from httpx import AsyncClient

from tests.conftest import login
from tests.test_academic_flow import CURP_A

API = "/api/v1"


async def post(client: AsyncClient, path: str, **body) -> dict:
    response = await client.post(f"{API}{path}", json=body)
    assert response.status_code in (200, 201), f"{path}: {response.text}"
    return response.json()


async def plan(client, campus_id, code, name, agreement, subjects):
    program = await post(client, "/catalog/programs", code=code, name=name, level="licenciatura")
    rvoe = await post(client, "/catalog/rvoes", program_id=program["id"], campus_id=campus_id,
                      agreement_number=agreement, authority="estatal", modality="escolarizada",
                      issue_date="2020-01-01")
    version = await post(client, "/catalog/plan-versions", rvoe_id=rvoe["id"], version_label="2020",
                         period_type="cuatrimestral", periods_count=9, min_attendance_pct=80)
    ids = {}
    for subject_code, subject_name, period in subjects:
        subject = await post(client, "/catalog/plan-subjects", plan_version_id=version["id"],
                             code=subject_code, name=subject_name, period_number=period, credits=6)
        component = await post(client, "/catalog/evaluation-components", plan_subject_id=subject["id"],
                               kind="parcial", label="Final", weight_pct=100)
        ids[subject_code] = (subject["id"], component["id"])
    return version, ids


async def term(client, name, start, end):
    t = await post(client, "/catalog/terms", name=name, period_type="cuatrimestral",
                   start_date=start, end_date=end)
    await client.patch(f"{API}/catalog/terms/{t['id']}", json={"grade_capture_open": True})
    return t


async def studied_old_plan(client, seed):
    """Old plan: 1.º and 2.º studied; everything approved except Física."""
    await login(client)
    campus_id = str(seed["campus"].id)
    old, old_ids = await plan(client, campus_id, "BP", "Bachillerato Presencial", "RVOE-PRES-01", [
        ("P101", "Matemáticas I", 1), ("P102", "Química I", 1),
        ("P201", "Matemáticas II", 2), ("P202", "Física I", 2),
    ])
    student = await post(client, "/students", curp=CURP_A, full_name="Ana Cambio", campus_id=campus_id)
    grades = {"P101": 9, "P102": 8, "P201": 10, "P202": 5}
    for period, name, start, end in [(1, "2025-1", "2025-01-01", "2025-04-30"),
                                     (2, "2025-2", "2025-05-01", "2025-08-31")]:
        t = await term(client, name, start, end)
        group = await post(client, "/catalog/groups", code=f"BP-{period}", period_number=period,
                           plan_version_id=old["id"], term_id=t["id"])
        await post(client, "/students/group-enrollments", student_id=student["id"], group_id=group["id"],
                   override_prerequisites=True)
        for code, value in grades.items():
            subject_id, component_id = old_ids[code]
            gs = next((x for x in (await client.get(f"{API}/catalog/groups/{group['id']}/subjects")).json()
                       if x["plan_subject_id"] == subject_id), None)
            if gs is None:
                continue
            row = (await client.get(f"{API}/grades/group-subjects/{gs['id']}/grid")).json()["rows"][0]
            await post(client, "/grades/capture", subject_enrollment_id=row["subject_enrollment_id"],
                       component_id=component_id, value=value)
    return campus_id, student, old


async def new_plan_and_group(client, campus_id):
    """Another carrera and RVOE (online): accents and names differ a little."""
    new, new_ids = await plan(client, campus_id, "BO", "Bachillerato Online", "RVOE-ONL-02", [
        ("O101", "MATEMATICAS I", 1), ("O102", "Quimica I", 1),
        ("O201", "Matemáticas II", 2), ("O202", "Física I", 2), ("O203", "Ética", 2),
        ("O301", "Matemáticas III", 3),
    ])
    t = await term(client, "2025-3", "2025-09-01", "2025-12-31")
    group = await post(client, "/catalog/groups", code="BO-3", period_number=3,
                       plan_version_id=new["id"], term_id=t["id"])
    return new, new_ids, group


async def test_proposal_matches_by_name(client, seed):
    campus_id, student, old = await studied_old_plan(client, seed)
    new, new_ids, group = await new_plan_and_group(client, campus_id)

    response = await client.get(f"{API}/students/{student['id']}/rvoe-change/proposal", params={
        "from_plan_version_id": old["id"], "target_group_id": group["id"],
    })
    assert response.status_code == 200, response.text
    items = {i["code"]: i for i in response.json()["items"]}
    assert set(items) == {"O101", "O102", "O201", "O202", "O203"}  # below 3.º only
    assert items["O101"]["action"] == "conv" and items["O101"]["grade"] == 9.0  # accents ignored
    assert items["O102"]["action"] == "conv" and items["O102"]["grade"] == 8.0
    assert items["O201"]["grade"] == 10.0
    assert items["O202"]["action"] == "cursar"  # Física was failed: nothing to recognize
    assert items["O203"]["action"] == "cursar"  # no equivalent at all
    assert len(response.json()["approved"]) == 3


async def test_apply_change_one_history(client, seed):
    campus_id, student, old = await studied_old_plan(client, seed)
    new, new_ids, group = await new_plan_and_group(client, campus_id)
    proposal = (await client.get(f"{API}/students/{student['id']}/rvoe-change/proposal", params={
        "from_plan_version_id": old["id"], "target_group_id": group["id"],
    })).json()
    assert [s["status"] for s in proposal["old_subjects"]] == ["aprobada", "aprobada", "aprobada", "reprobada"]
    proposal_source = next(i for i in proposal["items"] if i["code"] == "O201")["source_subject_enrollment_id"]

    decisions = [
        {"plan_subject_id": new_ids["O101"][0], "action": "conv", "grade": 9},
        {"plan_subject_id": new_ids["O102"][0], "action": "eq"},  # official grade not in yet
        {"plan_subject_id": new_ids["O201"][0], "action": "conv", "grade": 10,
         "source_subject_enrollment_id": proposal_source},
        {"plan_subject_id": new_ids["O202"][0], "action": "cursar"},  # in the destination group
        {"plan_subject_id": new_ids["O203"][0], "action": "pendiente"},
    ]
    result = await post(client, f"/students/{student['id']}/rvoe-change",
                        from_plan_version_id=old["id"], target_group_id=group["id"], decisions=decisions)
    assert result["summary"]["conv"] == ["O101", "O201"]

    plans = {p["plan_version_id"]: p["status"]
             for p in (await client.get(f"{API}/students/{student['id']}/plan-enrollments")).json()}
    assert plans == {old["id"]: "baja", new["id"]: "inscrito"}  # never two RVOE at once

    k = (await client.get(f"{API}/grades/students/{student['id']}/kardex-completo")).json()
    assert [p["name"] for p in k["programs"]] == ["Bachillerato Online"]  # one history
    assert {p["rvoe"] for p in k["periods"]} == {"RVOE-ONL-02"}  # certificate's RVOE
    rows = {r["code"]: r for r in k["rows"]}
    # the final plan, complete: recognitions with their origin, plus what is owed
    assert set(rows) == {"O101", "O102", "O201", "O202", "O203", "O301"}
    assert rows["O101"]["recognition"] == "conv" and rows["O101"]["final_grade"] == 9.0
    assert rows["O101"]["origin"] == "RVOE-PRES-01"  # no source picked: just the RVOE
    assert rows["O201"]["origin"] == "RVOE-PRES-01 · P201 Matemáticas II"
    assert rows["O102"]["recognition"] == "eq" and rows["O102"]["final_grade"] is None  # EQ pendiente
    assert rows["O202"]["status"] == "cursando" and rows["O202"]["group_code"] == "BO-3"
    assert rows["O203"]["status"] == "pendiente"
    assert rows["O301"]["status"] == "cursando"
    # what was studied under the old RVOE, as the backing
    [previous] = k["previous"]
    assert previous["rvoe"] == "RVOE-PRES-01"
    assert {r["code"]: r["status"] for r in previous["rows"]} == {
        "P101": "aprobada", "P102": "aprobada", "P201": "aprobada", "P202": "reprobada",
    }
    assert k["progress"]["passed_subjects"] == 2  # O101 + O201 convalidadas
    assert k["progress"]["total_subjects"] == 6

    # the internal convalidación group stays out of the group lists
    codes = {g["code"] for g in (await client.get(f"{API}/catalog/groups")).json()}
    assert "BO-3" in codes and not any(c.endswith(("-CONV", "-EQ")) for c in codes)
    internal = {g["code"] for g in (await client.get(
        f"{API}/catalog/groups", params={"include_internal": True})).json()}
    assert {"BO-3-CONV", "BO-3-EQ"} <= internal


async def test_change_requires_grade_and_current_plan(client, seed):
    campus_id, student, old = await studied_old_plan(client, seed)
    new, new_ids, group = await new_plan_and_group(client, campus_id)
    no_grade = await client.post(f"{API}/students/{student['id']}/rvoe-change", json={
        "from_plan_version_id": old["id"], "target_group_id": group["id"],
        "decisions": [{"plan_subject_id": new_ids["O101"][0], "action": "conv"}],
    })
    assert no_grade.status_code == 400
    wrong_plan = await client.post(f"{API}/students/{student['id']}/rvoe-change", json={
        "from_plan_version_id": new["id"], "target_group_id": group["id"], "decisions": [],
    })
    assert wrong_plan.status_code == 404  # not enrolled in that plan


async def test_prior_studies_pending_then_official_grade(client, seed):
    """A new student enters 2.º with a partial certificate: 1.º marked EQ, pending
    until the authority's grade is recorded."""
    await login(client)
    campus_id = str(seed["campus"].id)
    version, ids = await plan(client, campus_id, "LX", "Licenciatura X", "RVOE-X-01", [
        ("X101", "Matemáticas I", 1), ("X102", "Química I", 1), ("X201", "Física", 2),
    ])
    t = await term(client, "2026-1", "2026-01-01", "2026-04-30")
    group = await post(client, "/catalog/groups", code="LX-2", period_number=2,
                       plan_version_id=version["id"], term_id=t["id"])
    student = await post(client, "/students", curp=CURP_A, full_name="Nuevo Ingreso", campus_id=campus_id)
    await post(client, "/students/group-enrollments", student_id=student["id"], group_id=group["id"],
               override_prerequisites=True)

    candidates = (await client.get(f"{API}/students/{student['id']}/recognitions/candidates",
                                   params={"plan_version_id": version["id"]})).json()
    assert candidates["group_code"] == "LX-2"
    assert [s["code"] for s in candidates["subjects"]] == ["X101", "X102"]

    created = await post(client, f"/students/{student['id']}/recognitions", plan_version_id=version["id"], items=[
        {"plan_subject_id": ids["X101"][0], "kind": "eq", "origin": "Certificado parcial · Prepa Norte"},
        {"plan_subject_id": ids["X102"][0], "kind": "rev", "grade": 8, "origin": "Dictamen SEP 123"},
    ])
    eq_id = next(c["id"] for c in created if c["status"] == "cursando")

    k = (await client.get(f"{API}/grades/students/{student['id']}/kardex-completo")).json()
    rows = {r["code"]: r for r in k["rows"]}
    assert rows["X101"]["recognition"] == "eq" and rows["X101"]["final_grade"] is None
    assert rows["X101"]["origin"] == "Certificado parcial · Prepa Norte"
    assert rows["X102"]["recognition"] == "rev" and rows["X102"]["final_grade"] == 8.0

    again = await client.post(f"{API}/students/{student['id']}/recognitions", json={
        "plan_version_id": version["id"],
        "items": [{"plan_subject_id": ids["X101"][0], "kind": "eq"}],
    })
    assert again.status_code == 409  # already recognized

    # the authority's document arrives
    graded = await post(client, f"/students/subject-enrollments/{eq_id}/official-grade", grade=9)
    assert graded["final_grade"] == 9.0 and graded["status"] == "aprobada"
    rows = {r["code"]: r for r in (await client.get(
        f"{API}/grades/students/{student['id']}/kardex-completo")).json()["rows"]}
    assert rows["X101"]["final_grade"] == 9.0

    # only recognized subjects take an official grade
    regular = rows["X201"]
    refused = await client.post(
        f"{API}/students/subject-enrollments/{regular['subject_enrollment_id']}/official-grade",
        json={"grade": 9})
    assert refused.status_code == 400
