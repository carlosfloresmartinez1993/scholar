"""Reglamento: a student moves on to the next cuatrimestre with up to N failed
subjects of the one that ends (Configuración → Académico). Seriación still applies:
a next subject that needs a failed one is left out."""
from datetime import date, timedelta

from tests.conftest import login
from tests.test_academic_flow import CURP_A, CURP_B, build_catalog
from tests.test_treasury_documents import make_student

API = "/api/v1"
CURP_C = "LOPE030303HBCXNS07"


async def _setup(client, seed):
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    plan_id = catalog["plan"]["id"]
    # 1st cuatrimestre: subject_a + two more; 2nd: subject_b (needs subject_a) + one free
    extra_1 = []
    for code in ("DER102", "DER103"):
        extra_1.append((await client.post(f"{API}/catalog/plan-subjects", json={
            "plan_version_id": plan_id, "code": code, "name": code, "period_number": 1,
            "credits": 6})).json())
    free_2 = (await client.post(f"{API}/catalog/plan-subjects", json={
        "plan_version_id": plan_id, "code": "DER202", "name": "Libre", "period_number": 2,
        "credits": 6})).json()
    term1 = catalog["term"]
    group1 = (await client.post(f"{API}/catalog/groups", json={
        "code": "LD-1B", "period_number": 1, "plan_version_id": plan_id,
        "term_id": term1["id"]})).json()
    today = date.today()
    term2 = (await client.post(f"{API}/catalog/terms", json={
        "name": "2027-1 ENE-ABR", "period_type": "cuatrimestral",
        "start_date": (today + timedelta(days=5)).isoformat(),
        "end_date": (today + timedelta(days=120)).isoformat()})).json()
    await client.post(f"{API}/catalog/groups", json={
        "code": "LD-2B", "period_number": 2, "plan_version_id": plan_id,
        "term_id": term2["id"], "promotes_from_group_id": group1["id"]})
    return catalog, group1, free_2


async def _student_with(client, campus_id, group_id, curp, grades: dict):
    """Enrolled in the group; each subject code gets its final grade."""
    student = await make_student(client, campus_id, curp=curp)
    await client.post(f"{API}/students/group-enrollments", json={
        "student_id": student["id"], "group_id": group_id})
    kardex = (await client.get(f"{API}/grades/students/{student['id']}/kardex-completo")).json()
    for row in kardex["rows"]:
        if row["code"] in grades and row["subject_enrollment_id"]:
            await client.post(f"{API}/grades/subject-enrollments/{row['subject_enrollment_id']}/correct",
                              json={"final_grade": grades[row["code"]], "reason": "prueba"})
    return student


async def test_reglamento_allows_some_failed_subjects(client, seed):
    catalog, group1, free_2 = await _setup(client, seed)
    campus_id = str(seed["campus"].id)
    all_passed = await _student_with(client, campus_id, group1["id"], CURP_A,
                                     {"DER101": 9, "DER102": 9, "DER103": 9})
    two_failed = await _student_with(client, campus_id, group1["id"], CURP_B,
                                     {"DER101": 5, "DER102": 4, "DER103": 9})
    three_failed = await _student_with(client, campus_id, group1["id"], CURP_C,
                                       {"DER101": 5, "DER102": 5, "DER103": 5})

    # by default (0) only who passed everything moves on
    preview = (await client.post(f"{API}/students/promote-cycle?dry_run=true")).json()
    assert {p["matricula"] for p in preview["promoted"]} == {all_passed["enrollment_number"]}

    # the reglamento: up to 2 failed
    saved = await client.patch(f"{API}/catalog/institution", json={"max_failed_to_promote": 2})
    assert saved.status_code == 200 and saved.json()["max_failed_to_promote"] == 2
    preview = (await client.post(f"{API}/students/promote-cycle?dry_run=true")).json()
    promoted = {p["matricula"]: p for p in preview["promoted"]}
    assert set(promoted) == {all_passed["enrollment_number"], two_failed["enrollment_number"]}
    assert "avanza con 2 reprobada" in promoted[two_failed["enrollment_number"]]["reason"]
    assert "seriación" in promoted[two_failed["enrollment_number"]]["reason"]
    skipped = {s["matricula"]: s for s in preview["skipped"]}
    assert "reprobó 3 (se permiten 2)" in skipped[three_failed["enrollment_number"]]["reason"]

    # promoted for real: the subject that needs DER101 is left out, the free one is taken
    run = (await client.post(f"{API}/students/promote-cycle?dry_run=false")).json()
    assert run["promoted_count"] == 2
    kardex = (await client.get(f"{API}/grades/students/{two_failed['id']}/kardex-completo")).json()
    status = {r["code"]: r["status"] for r in kardex["rows"]}
    assert status["DER202"] == "cursando"
    assert status["DER201"] == "pendiente"  # seriación: needs DER101
    assert status["DER101"] == "reprobada"

    # out of range
    assert (await client.patch(f"{API}/catalog/institution", json={"max_failed_to_promote": -1})).status_code == 422
