"""Tests for drive.py — Drive core operations."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_google.core.drive import (
    DriveError,
    FileRef,
    delete_file,
    get_file,
    list_folder,
    move_file,
    search,
    update_file,
    upload_file,
)


def _list_response(files: list[dict]) -> dict:
    return {"files": files}


def test_search_returns_files(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = _list_response(
        [
            {"id": "f1", "name": "Q1 report.pdf", "mimeType": "application/pdf"},
            {"id": "f2", "name": "Q1 draft.docx",
             "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        ]
    )
    mock_drive_service.files().list.return_value = call

    result = search(mock_drive_service, query="Q1")
    assert len(result) == 2
    assert isinstance(result[0], FileRef)
    assert result[0].id == "f1"
    _, kwargs = mock_drive_service.files().list.call_args
    assert "name contains 'Q1'" in kwargs["q"]
    assert kwargs["fields"].startswith("files(")


def test_search_with_mime_type(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = _list_response([])
    mock_drive_service.files().list.return_value = call
    search(mock_drive_service, query="Q1", mime_type="application/pdf")
    _, kwargs = mock_drive_service.files().list.call_args
    assert "mimeType = 'application/pdf'" in kwargs["q"]


def test_list_folder(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = _list_response(
        [{"id": "f3", "name": "sub.txt", "mimeType": "text/plain"}]
    )
    mock_drive_service.files().list.return_value = call

    result = list_folder(mock_drive_service, folder_id="FOLDER")
    assert len(result) == 1
    _, kwargs = mock_drive_service.files().list.call_args
    assert "'FOLDER' in parents" in kwargs["q"]


def test_get_file_downloads_to_cache(
    tmp_path: Path, mock_drive_service: MagicMock, mocker
) -> None:
    meta_call = MagicMock()
    meta_call.execute.return_value = {
        "id": "f1", "name": "report.pdf", "mimeType": "application/pdf"
    }
    mock_drive_service.files().get.return_value = meta_call
    mock_drive_service.files().get_media.return_value = MagicMock()

    def _fake_downloader(fh, request):  # noqa: ARG001
        fh.write(b"%PDF-1.4 fake")
        instance = MagicMock()
        instance.next_chunk.side_effect = [(MagicMock(progress=lambda: 1.0), True)]
        return instance

    mocker.patch(
        "hermes_google.core.drive.MediaIoBaseDownload", side_effect=_fake_downloader
    )

    path = get_file(mock_drive_service, file_id="f1", cache_dir=tmp_path)
    assert path == tmp_path / "drive" / "f1" / "report.pdf"
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")


def test_upload_file(
    tmp_path: Path, mock_drive_service: MagicMock, mocker
) -> None:
    local = tmp_path / "notes.md"
    local.write_text("hello")

    mocker.patch("hermes_google.core.drive.MediaFileUpload")
    call = MagicMock()
    call.execute.return_value = {"id": "new-1"}
    mock_drive_service.files().create.return_value = call

    file_id = upload_file(
        mock_drive_service, local_path=local, name="notes.md", parent_folder_id="FOLDER"
    )
    assert file_id == "new-1"
    _, kwargs = mock_drive_service.files().create.call_args
    assert kwargs["body"] == {"name": "notes.md", "parents": ["FOLDER"]}


def test_update_file(tmp_path: Path, mock_drive_service: MagicMock, mocker) -> None:
    local = tmp_path / "notes.md"
    local.write_text("v2")
    mocker.patch("hermes_google.core.drive.MediaFileUpload")
    call = MagicMock()
    call.execute.return_value = {"id": "f1"}
    mock_drive_service.files().update.return_value = call

    update_file(mock_drive_service, file_id="f1", local_path=local)
    _, kwargs = mock_drive_service.files().update.call_args
    assert kwargs["fileId"] == "f1"


def test_move_file(mock_drive_service: MagicMock) -> None:
    # First call: files().get() with fields='parents' returns the old parents
    get_call = MagicMock()
    get_call.execute.return_value = {"parents": ["OLD"]}
    mock_drive_service.files().get.return_value = get_call

    update_call = MagicMock()
    update_call.execute.return_value = {"id": "f1"}
    mock_drive_service.files().update.return_value = update_call

    move_file(mock_drive_service, file_id="f1", parent_folder_id="NEW")
    _, kwargs = mock_drive_service.files().update.call_args
    assert kwargs["fileId"] == "f1"
    assert kwargs["addParents"] == "NEW"
    assert kwargs["removeParents"] == "OLD"


def test_delete_file(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {}
    mock_drive_service.files().delete.return_value = call
    delete_file(mock_drive_service, file_id="f1")
    _, kwargs = mock_drive_service.files().delete.call_args
    assert kwargs["fileId"] == "f1"


def test_get_file_rejects_path_traversal_name(
    tmp_path: Path, mock_drive_service: MagicMock
) -> None:
    meta_call = MagicMock()
    meta_call.execute.return_value = {
        "id": "f1", "name": "../../etc/passwd", "mimeType": "text/plain"
    }
    mock_drive_service.files().get.return_value = meta_call

    with pytest.raises(DriveError, match="unsafe filename"):
        get_file(mock_drive_service, file_id="f1", cache_dir=tmp_path)


def test_upload_file_malformed_response_raises(
    tmp_path: Path, mock_drive_service: MagicMock, mocker
) -> None:
    local = tmp_path / "notes.md"
    local.write_text("hello")

    mocker.patch("hermes_google.core.drive.MediaFileUpload")
    call = MagicMock()
    call.execute.return_value = {"name": "notes.md"}  # missing "id"
    mock_drive_service.files().create.return_value = call

    with pytest.raises(DriveError, match="malformed upload response"):
        upload_file(mock_drive_service, local_path=local, name="notes.md")


def test_search_escapes_single_quotes(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = _list_response([])
    mock_drive_service.files().list.return_value = call

    search(mock_drive_service, query="O'Brien")
    _, kwargs = mock_drive_service.files().list.call_args
    assert "\\'" in kwargs["q"]
    assert "O\\'Brien" in kwargs["q"]
