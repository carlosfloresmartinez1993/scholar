"""Uploaded-file storage on local disk (mount a Railway volume at UPLOADS_DIR).
RF-D08: retention is handled at the infrastructure level (volume + DB backups)."""
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}


async def save_upload(file: UploadFile, subdir: str) -> str:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Solo se aceptan PDF o imágenes")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Archivo mayor a 20 MB")
    directory = Path(settings.UPLOADS_DIR) / subdir
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "archivo").name.replace(" ", "_")
    path = directory / f"{uuid.uuid4().hex}-{safe_name}"
    path.write_bytes(content)
    return str(path)
