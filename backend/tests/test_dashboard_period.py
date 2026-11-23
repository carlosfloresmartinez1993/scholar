"""Dashboard period endpoints: days validation, series shape, activity guard,
and KPI/chart window alignment."""
import uuid
from datetime import timedelta

from app.models import GroupEnrollment
from app.models.common import utcnow
from sqlmodel import select

from tests.conftest import login
from tests.test_academic_flow import build_catalog
from tests.test_treasury_documents import make_student


async def test_stats_accepts_only_known_windows(client, seed):
    await login(client)
    response = await client.get("/api/v1/dashboard/stats?days=7")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"]["days"] == 7
    assert {"current", "previous"} <= set(body["period"]["collected"])

    response = await client.get("/api/v1/dashboard/stats?days=5")
    assert response.status_code == 422


async def test_enrollments_series_shape(client, seed):
    await login(client)
    response = await client.get("/api/v1/dashboard/enrollments-series?days=14")
    assert response.status_code == 200
    series = response.json()
    assert len(series) == 14
    assert all({"date", "count"} <= set(point) for point in series)


async def test_series_total_matches_kpi_window(client, seed, session_factory):
    """The chart and the 'inscripciones nuevas' KPI share the same calendar-day
    window: their totals must agree."""
    # two real enrollments: one now (inside any window), one moved 40 days back
    await login(client)
    campus_id = str(seed["campus"].id)
    catalog = await build_catalog(client, campus_id)
    other = (await client.post("/api/v1/catalog/groups", json={
        "code": "LD-1B", "period_number": 1, "plan_version_id": catalog["plan"]["id"],
        "term_id": catalog["term"]["id"]})).json()
    student = await make_student(client, campus_id)
    for group_id in (catalog["group"]["id"], other["id"]):
        await client.post("/api/v1/students/group-enrollments", json={
            "student_id": student["id"], "group_id": group_id})
    async with session_factory() as session:
        old = (await session.exec(
            select(GroupEnrollment).where(GroupEnrollment.group_id == uuid.UUID(other["id"]))
        )).one()
        old.created_at = utcnow() - timedelta(days=40)
        session.add(old)
        await session.commit()

    for days in (1, 7, 14, 30):
        stats = (await client.get(f"/api/v1/dashboard/stats?days={days}")).json()
        series = (
            await client.get(f"/api/v1/dashboard/enrollments-series?days={days}")
        ).json()
        # today's enrollment is inside every window, the 40-day-old one never is
        current = stats["period"]["new_enrollments"]["current"]
        assert current == 1, f"unexpected window total for days={days}"
        assert sum(p["count"] for p in series) == current, f"mismatch for days={days}"


async def test_activity_visible_to_staff(client, seed):
    # staff (e.g. tesorería) can read the dashboard activity feed
    await login(client, "tesoreria@inue.edu.mx")
    response = await client.get("/api/v1/dashboard/activity?days=30")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    # a docente only captures grades and attendance: no dashboard
    await login(client, "docente@inue.edu.mx")
    assert (await client.get("/api/v1/dashboard/activity?days=30")).status_code == 403
