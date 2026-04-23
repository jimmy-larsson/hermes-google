"""Drive operations. Every function takes a `service` argument."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


class DriveError(Exception):
    """Raised on Drive API failures."""


@dataclass(frozen=True)
class FileRef:
    id: str
    name: str
    mime_type: str


_FIELDS = "files(id,name,mimeType,parents)"


def _to_ref(item: dict[str, Any]) -> FileRef:
    return FileRef(
        id=item["id"], name=item.get("name", ""), mime_type=item.get("mimeType", "")
    )


def search(
    service: Any,
    *,
    query: str,
    mime_type: str | None = None,
    limit: int = 20,
) -> list[FileRef]:
    q_parts = [f"name contains '{query}'", "trashed = false"]
    if mime_type:
        q_parts.append(f"mimeType = '{mime_type}'")
    try:
        resp = (
            service.files()
            .list(q=" and ".join(q_parts), fields=_FIELDS, pageSize=limit)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise DriveError(f"search failed: {exc}") from exc
    return [_to_ref(i) for i in resp.get("files", [])]


def list_folder(service: Any, *, folder_id: str, limit: int = 50) -> list[FileRef]:
    q = f"'{folder_id}' in parents and trashed = false"
    try:
        resp = service.files().list(q=q, fields=_FIELDS, pageSize=limit).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(f"list folder failed: {exc}") from exc
    return [_to_ref(i) for i in resp.get("files", [])]


def get_file(service: Any, *, file_id: str, cache_dir: Path) -> Path:
    try:
        meta = (
            service.files()
            .get(fileId=file_id, fields="id,name,mimeType")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise DriveError(f"get metadata failed: {exc}") from exc

    target_dir = cache_dir / "drive" / file_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / meta["name"]

    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    target.write_bytes(fh.getvalue())
    return target


def upload_file(
    service: Any,
    *,
    local_path: Path,
    name: str,
    parent_folder_id: str | None = None,
) -> str:
    body: dict[str, Any] = {"name": name}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    media = MediaFileUpload(str(local_path), resumable=True)
    try:
        resp = service.files().create(body=body, media_body=media, fields="id").execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(f"upload failed: {exc}") from exc
    return resp["id"]


def update_file(service: Any, *, file_id: str, local_path: Path) -> None:
    media = MediaFileUpload(str(local_path), resumable=True)
    try:
        service.files().update(fileId=file_id, media_body=media).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(f"update failed: {exc}") from exc


def move_file(service: Any, *, file_id: str, parent_folder_id: str) -> None:
    try:
        meta = service.files().get(fileId=file_id, fields="parents").execute()
        old_parents = ",".join(meta.get("parents", []))
        service.files().update(
            fileId=file_id,
            addParents=parent_folder_id,
            removeParents=old_parents,
            fields="id",
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(f"move failed: {exc}") from exc


def delete_file(service: Any, *, file_id: str) -> None:
    try:
        service.files().delete(fileId=file_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(f"delete failed: {exc}") from exc
