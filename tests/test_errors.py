"""Tests for errors.py: the api_failure message helper."""

from __future__ import annotations

import httplib2
from googleapiclient.errors import HttpError

from hermes_google.core.errors import api_failure


def test_api_failure_includes_http_status_and_reason() -> None:
    resp = httplib2.Response({"status": 403, "reason": "Forbidden"})
    content = (
        b'{"error": {"code": 403, "message": "The user does not have sufficient '
        b'permissions for this file.", "errors": [{"reason": "insufficientFilePermissions"}]}}'
    )
    exc = HttpError(resp, content, uri="https://www.googleapis.com/drive/v3/files/x")
    assert api_failure("rename", exc) == (
        "rename failed: HTTP 403 The user does not have sufficient permissions for this file."
    )


def test_api_failure_other_exceptions_show_type_and_text() -> None:
    assert api_failure("upload", OSError("disk full")) == "upload failed: OSError: disk full"
