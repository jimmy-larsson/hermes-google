"""Drive operations. Every function takes a `service` argument."""

from __future__ import annotations

import contextlib
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from hermes_google.core.errors import ServiceError, api_failure


class DriveError(ServiceError):
    """Raised on Drive API failures."""


@dataclass(frozen=True)
class FileRef:
    id: str
    name: str
    mime_type: str


_FIELDS = "files(id,name,mimeType,parents)"


def _to_ref(item: dict[str, Any]) -> FileRef:
    return FileRef(id=item["id"], name=item.get("name", ""), mime_type=item.get("mimeType", ""))


_REF_FIELDS = "id,name,mimeType"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_NATIVE_PREFIX = "application/vnd.google-apps."
_EXPORT_DEFAULTS = {
    "application/vnd.google-apps.document": "text/markdown",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "application/pdf",
}
_EXPORT_EXTENSIONS = {"text/markdown": ".md", "text/csv": ".csv", "application/pdf": ".pdf"}


def _export_type(mime_type: str, export_mime_type: str | None) -> str | None:
    if not mime_type.startswith(_NATIVE_PREFIX):
        return None
    if mime_type == FOLDER_MIME_TYPE:
        raise DriveError("cannot download a folder; use drive_list")
    if mime_type == "application/vnd.google-apps.shortcut":
        raise DriveError("cannot download a shortcut; open its target file instead")
    chosen = export_mime_type or _EXPORT_DEFAULTS.get(mime_type)
    if not chosen:
        raise DriveError(f"cannot download {mime_type}: pass export_mime_type")
    return chosen


def _with_extension(name: str, export_mime_type: str) -> str:
    ext = _EXPORT_EXTENSIONS.get(export_mime_type) or mimetypes.guess_extension(export_mime_type)
    if not ext or name.lower().endswith(ext):
        return name
    return name + ext


def _is_unsafe_name(name: str) -> bool:
    return not name or name in {".", ".."} or "/" in name or "\\" in name


def _validate_name(name: str) -> str:
    cleaned = name.strip()
    if _is_unsafe_name(cleaned):
        raise DriveError(f"invalid name: {name!r}")
    return cleaned


def search(
    service: Any,
    *,
    query: str,
    mime_type: str | None = None,
    limit: int = 20,
) -> list[FileRef]:
    safe_query = query.replace("'", "\\'")
    q_parts = [f"name contains '{safe_query}'", "trashed = false"]
    if mime_type:
        safe_mime_type = mime_type.replace("'", "\\'")
        q_parts.append(f"mimeType = '{safe_mime_type}'")
    try:
        resp = (
            service.files().list(q=" and ".join(q_parts), fields=_FIELDS, pageSize=limit).execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("search", exc)) from exc
    return [_to_ref(i) for i in resp.get("files", [])]


def list_folder(service: Any, *, folder_id: str, limit: int = 50) -> list[FileRef]:
    safe_id = folder_id.replace("'", "\\'")
    q = f"'{safe_id}' in parents and trashed = false"
    try:
        resp = service.files().list(q=q, fields=_FIELDS, pageSize=limit).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("list folder", exc)) from exc
    return [_to_ref(i) for i in resp.get("files", [])]


def get_file(
    service: Any,
    *,
    file_id: str,
    cache_dir: Path,
    export_mime_type: str | None = None,
) -> Path:
    try:
        meta = service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("get metadata", exc)) from exc

    export_as = _export_type(meta.get("mimeType", ""), export_mime_type)
    raw_name = meta["name"]
    if os.path.basename(raw_name) != raw_name or _is_unsafe_name(raw_name):
        raise DriveError(f"unsafe filename: {raw_name!r}")
    safe_name = _with_extension(raw_name, export_as) if export_as else raw_name

    target_dir = cache_dir / "drive" / file_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name

    # I1 (containment check): guard against symlink / absolute-path bypass.
    if not str(target.resolve()).startswith(str(target_dir.resolve()) + os.sep):
        raise DriveError(f"unsafe filename: {raw_name!r}")

    if export_as:
        request = service.files().export_media(fileId=file_id, mimeType=export_as)
    else:
        request = service.files().get_media(fileId=file_id)
    # I3: stream directly to disk — avoid buffering the full file in RAM.
    try:
        with target.open("wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(OSError):
            target.unlink()
        raise DriveError(api_failure("export" if export_as else "download", exc)) from exc
    return target


def upload_file(
    service: Any,
    *,
    local_path: Path,
    name: str,
    parent_folder_id: str | None = None,
) -> str:
    name = _validate_name(name)
    body: dict[str, Any] = {"name": name}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    try:
        media = MediaFileUpload(str(local_path), resumable=True)
        resp = service.files().create(body=body, media_body=media, fields="id").execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("upload", exc)) from exc
    try:
        return resp["id"]
    except KeyError as exc:
        raise DriveError("unexpected upload response format") from exc


def update_file(service: Any, *, file_id: str, local_path: Path) -> None:
    try:
        media = MediaFileUpload(str(local_path), resumable=True)
        service.files().update(fileId=file_id, media_body=media).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("update", exc)) from exc


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
        raise DriveError(api_failure("move", exc)) from exc


def rename_file(service: Any, *, file_id: str, new_name: str) -> FileRef:
    name = _validate_name(new_name)
    try:
        resp = (
            service.files()
            .update(fileId=file_id, body={"name": name}, fields=_REF_FIELDS)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("rename", exc)) from exc
    try:
        return _to_ref(resp)
    except KeyError as exc:
        raise DriveError("unexpected rename response format") from exc


def create_folder(
    service: Any,
    *,
    name: str,
    parent_folder_id: str | None = None,
) -> FileRef:
    folder_name = _validate_name(name)
    body: dict[str, Any] = {"name": folder_name, "mimeType": FOLDER_MIME_TYPE}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    try:
        resp = service.files().create(body=body, fields=_REF_FIELDS).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("create folder", exc)) from exc
    try:
        return _to_ref(resp)
    except KeyError as exc:
        raise DriveError("unexpected create response format") from exc


def delete_file(service: Any, *, file_id: str) -> None:
    try:
        service.files().delete(fileId=file_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise DriveError(api_failure("delete", exc)) from exc
