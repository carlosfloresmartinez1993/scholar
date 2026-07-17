"""Dashboard period endpoints: days validation, series shape, activity guard,
and KPI/chart window alignment."""
import uuid
from datetime import timedelta

from app.models import GroupEnrollment
from app.models.common import utcnow
from tests.conftest import login


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
    # seed enrollments directly: one now (inside any window) and one far outside
    async with session_factory() as session:
        for created_at in (utcnow(), utcnow() - timedelta(days=40)):
            session.add(
                GroupEnrollment(
                    student_id=uuid.uuid4(),
                    group_id=uuid.uuid4(),
                    plan_enrollment_id=uuid.uuid4(),
                    created_at=created_at,
                )
            )
        await session.commit()

    await login(client)
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
    # any staff (e.g. docente) can read the dashboard activity feed
    await login(client, "docente@inue.edu.mx")
    response = await client.get("/api/v1/dashboard/activity?days=30")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
