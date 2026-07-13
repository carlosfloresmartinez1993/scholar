from fastapi import APIRouter

from app.api.routes import (
    attendance,
    audit,
    auth,
    catalog,
    documents,
    grades,
    health,
    integration,
    students,
    treasury,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(catalog.router)
api_router.include_router(students.router)
api_router.include_router(grades.router)
api_router.include_router(attendance.router)
api_router.include_router(documents.router)
api_router.include_router(treasury.router)
api_router.include_router(integration.router)
api_router.include_router(audit.router)
