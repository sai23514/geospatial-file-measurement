"""Safe handling of untrusted uploads and ZIP archives."""
from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi import UploadFile

from app.errors import EmptyUpload, ProcessingError, UploadTooLarge

_CHUNK = 1024 * 1024


def save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> int:
    """Stream the upload to disk, enforcing a size limit without buffering it in memory."""
    size = 0
    with dest.open("wb") as out:
        while chunk := upload.file.read(_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise UploadTooLarge()
            out.write(chunk)
    if size == 0:
        raise EmptyUpload()
    return size


def extract_zip(zip_path: Path, dest_dir: Path, *, max_members: int, max_bytes: int) -> list[Path]:
    """Extract a ZIP defensively: rejects path traversal (zip-slip), too many members,
    and archives that expand beyond `max_bytes` (counted on actual bytes, not headers)."""
    dest_root = dest_dir.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [i for i in zf.infolist() if not i.is_dir()]
            if len(members) > max_members:
                raise ProcessingError(f"Archive contains too many files (limit {max_members})")
            for info in members:
                target = (dest_root / info.filename).resolve()
                if not target.is_relative_to(dest_root):
                    raise ProcessingError(f"Unsafe path in archive: {info.filename!r}")
                name = Path(info.filename).name
                if info.filename.startswith("__MACOSX/") or name.startswith("."):
                    continue  # macOS resource forks / hidden files
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(_CHUNK):
                        total += len(chunk)
                        if total > max_bytes:
                            raise ProcessingError("Archive is too large once extracted")
                        out.write(chunk)
                extracted.append(target)
    except zipfile.BadZipFile as exc:
        raise ProcessingError("Uploaded file is not a valid ZIP archive") from exc
    except (RuntimeError, NotImplementedError) as exc:  # encrypted / unsupported compression
        raise ProcessingError(f"Could not read ZIP archive: {exc}") from exc
    return extracted
