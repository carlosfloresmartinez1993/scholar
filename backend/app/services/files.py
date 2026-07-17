"""Uploaded-file storage on local disk (mount a Railway volume at UPLOADS_DIR).
RF-D08: retention is handled at the infrastructure level (volume + DB backups)."""
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}


async def save_upload(
    file: UploadFile,
    subdir: str,
    *,
    allowed_types: set[str] = ALLOWED_TYPES,
    max_bytes: int = MAX_UPLOAD_BYTES,
    type_error_detail: str = "Solo se aceptan PDF o imágenes",
) -> str:
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=415, detail=type_error_detail)
    # read at most max_bytes + 1: enough to detect oversize without buffering
    # an arbitrarily large body in memory
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo mayor a {max_bytes // (1024 * 1024)} MB",
        )
    directory = Path(settings.UPLOADS_DIR) / subdir
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "archivo").name.replace(" ", "_")
    path = directory / f"{uuid.uuid4().hex}-{safe_name}"
    path.write_bytes(content)
    return str(path)
