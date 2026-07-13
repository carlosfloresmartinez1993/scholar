import os

os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-not-used")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("FIRST_SUPERUSER", "admin@inue.edu.mx")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "testpassword1")
os.environ.setdefault("ENV_FILE", "/dev/null")
os.environ.setdefault("UPLOADS_DIR", "/tmp/scholar-test-uploads")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.security import get_password_hash
from app.main import app
from app.models import Campus, Institution, User, UserRole

SUPERUSER_EMAIL = "admin@inue.edu.mx"
PASSWORD = "testpassword1"


@pytest.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def seed(session_factory):
    """Institution + campus + users for every role."""
    async with session_factory() as session:
        institution = Institution(
            name="Instituto Universitario Ensenada", short_name="INUE",
            late_fee_pct=10.0, late_fee_grace_days=0,
        )
        session.add(institution)
        await session.flush()
        campus = Campus(institution_id=institution.id, name="Campus Ensenada")
        session.add(campus)
        hashed = get_password_hash(PASSWORD)
        users = {}
        for email, role, is_super in [
            (SUPERUSER_EMAIL, UserRole.admin_sistema, True),
            ("escolares@inue.edu.mx", UserRole.servicios_escolares, False),
            ("tesoreria@inue.edu.mx", UserRole.tesoreria, False),
            ("docente@inue.edu.mx", UserRole.docente, False),
        ]:
            user = User(email=email, full_name=email.split("@")[0],
                        role=role, is_superuser=is_super, hashed_password=hashed)
            session.add(user)
            users[role] = user
        await session.commit()
        for user in users.values():
            await session.refresh(user)
        return {"institution": institution, "campus": campus, "users": users}


@pytest.fixture
async def client(session_factory, seed):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def login(client: AsyncClient, email: str = SUPERUSER_EMAIL) -> None:
    response = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
