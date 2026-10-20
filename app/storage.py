"""Encrypted file storage. Every uploaded file is encrypted at rest with Fernet (AES-128-CBC + HMAC)."""
from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from .config import get_settings
from .db import get_db, now_iso
from .security import decrypt_bytes, encrypt_bytes


def save_file(user_id: int, kind: str, filename: str, data: bytes, mime: str = "") -> dict:
    settings = get_settings()
    folder = settings.files_dir / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.bin"
    path.write_bytes(encrypt_bytes(data))
    safe_name = Path(filename).name[:180] or "file"
    file_id = get_db().insert("files", {
        "user_id": user_id,
        "kind": kind,
        "filename": safe_name,
        "mime": mime,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "storage_path": str(path.relative_to(settings.files_dir)),
        "encrypted": 1,
        "created_at": now_iso(),
    })
    return get_file_row(file_id)


def get_file_row(file_id: int) -> dict | None:
    return get_db().fetchone("SELECT * FROM files WHERE id = ?", (file_id,))


def read_file(row: dict) -> bytes:
    path = get_settings().files_dir / row["storage_path"]
    raw = path.read_bytes()
    return decrypt_bytes(raw) if row.get("encrypted") else raw


def delete_file(row: dict) -> None:
    path = get_settings().files_dir / row["storage_path"]
    path.unlink(missing_ok=True)
    get_db().execute("DELETE FROM files WHERE id = ?", (row["id"],))


def delete_user_files(user_id: int) -> int:
    rows = get_db().fetchall("SELECT * FROM files WHERE user_id = ?", (user_id,))
    for row in rows:
        delete_file(row)
    folder = get_settings().files_dir / str(user_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return len(rows)
