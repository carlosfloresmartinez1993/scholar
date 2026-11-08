"""Mide las pantallas clave contra la base simulada, dentro de un solo proceso de la
app (producción usa 4): tiempo y número de consultas de cada una, y un pico simultáneo.

    POSTGRES_DB=scholar_carga uv run python scripts/medir_carga.py [concurrencia]
"""
import asyncio
import statistics
import sys
import time

import httpx
from sqlalchemy import event, text

from app.core.config import settings
from app.core.db import async_session_factory, engine
from app.main import app

assert settings.POSTGRES_DB.endswith("_carga"), "Solo sobre una base *_carga"
engine.echo = False
CONCURRENCY = int(sys.argv[1]) if len(sys.argv) > 1 else 100
API = "/api/v1"
counter = {"n": 0}


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _count(*_):
    counter["n"] += 1


async def measure(client, label, *paths, method="GET"):
    counter["n"] = 0
    start = time.perf_counter()
    for path in paths:
        response = await client.request(method, f"{API}{path}")
        assert response.status_code < 400, (path, response.status_code, response.text[:200])
    elapsed = (time.perf_counter() - start) * 1000
    print(f"{label:44} {elapsed:9.0f} ms {counter['n']:6} consultas", flush=True)


async def main():
    async with async_session_factory() as session:
        row = (await session.execute(text("""
            select g.id, g.term_id from groups g join terms t on t.id=g.term_id
            where t.is_open and t.name='CARGA-9' and g.period_number=1 limit 1"""))).first()
        group_id, term_id = row
        gs_ids = [r[0] for r in (await session.execute(
            text("select id from group_subjects where group_id=:g"), {"g": group_id}))]
        student_id = (await session.execute(text("""
            select pc.student_id from plan_changes pc join subject_enrollments se on se.student_id=pc.student_id
            group by 1 order by count(*) desc limit 1"""))).scalar()
        plan_version = (await session.execute(text(
            "select plan_version_id from student_plan_enrollments where student_id=:s and status='inscrito'"),
            {"s": student_id})).scalar()
        users = (await session.execute(text(
            "select email from users where student_id=:s"), {"s": student_id})).scalar()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://carga", timeout=600) as client:
        response = await client.post(f"{API}/auth/login", data={
            "username": settings.FIRST_SUPERUSER, "password": settings.FIRST_SUPERUSER_PASSWORD})
        response.raise_for_status()
        await measure(client, "Lista de alumnos", "/students")
        await measure(client, "Búsqueda de alumnos por nombre", "/students?q=Simulado%20A0")
        await measure(client, "Grupos del ciclo", f"/catalog/groups?term_id={term_id}")
        await measure(client, "Detalle de grupo (materias + listas)", f"/catalog/groups/{group_id}/subjects",
                      *[f"/grades/group-subjects/{g}/grid" for g in gs_ids])
        await measure(client, "Lista de calificaciones de una materia", f"/grades/group-subjects/{gs_ids[0]}/grid")
        await measure(client, "Kárdex completo", f"/grades/students/{student_id}/kardex-completo")
        await measure(client, "Grupo actual del alumno", f"/students/{student_id}/current-group")
        await measure(client, "Reconocer estudios previos (lista)",
                      f"/students/{student_id}/recognitions/candidates?plan_version_id={plan_version}")
        await measure(client, "Panel de inicio", "/dashboard/stats")
        await measure(client, "Bitácora", "/audit")
        await measure(client, "Promoción de ciclo (vista previa)", "/students/promote-cycle?dry_run=true", method="POST")

        # the peak: staff opening group lists and kárdex at once
        paths = [f"/grades/group-subjects/{gs_ids[i % len(gs_ids)]}/grid" if i % 2
                 else f"/grades/students/{student_id}/kardex-completo" for i in range(CONCURRENCY)]
        limit = asyncio.Semaphore(CONCURRENCY)
        times = []

        async def one(path):
            async with limit:
                start = time.perf_counter()
                response = await client.get(f"{API}{path}")
                times.append((time.perf_counter() - start) * 1000)
                return response.status_code

        start = time.perf_counter()
        codes = await asyncio.gather(*[one(p) for p in paths], return_exceptions=True)
        total = time.perf_counter() - start
        ok = sum(1 for c in codes if c == 200)
        times.sort()
        print(f"\nPico: {CONCURRENCY} a la vez · {ok} correctas · total {total:.1f} s · "
              f"mediana {statistics.median(times):.0f} ms · p95 {times[int(len(times) * .95) - 1]:.0f} ms")
        bad = [c for c in codes if c != 200]
        if bad:
            print("Errores:", repr(bad[0])[:300])


asyncio.run(main())
