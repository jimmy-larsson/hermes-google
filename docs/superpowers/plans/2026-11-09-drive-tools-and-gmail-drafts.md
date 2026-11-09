# hermes-google 0.4.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship hermes-google 0.4.0: `drive_rename` and `drive_create_folder` tools on the full Drive scope, Gmail turned drafts-only (send tool removed, four draft tools added, reply threading fixed), and Google API errors that say why they failed.

**Architecture:** Pure core modules under `src/hermes_google/core/` take a Google `service` and raise `ServiceError` subclasses; `mcp_server.py` wraps them in FastMCP tools behind `_auto_retry`, which turns `ServiceError` into `ToolError`. Draft code goes in a new `core/drafts.py` (mirrors hermes-imap's `core/drafts.py`); `core/mail.py` keeps message reading and labels. Every change is test-first against `MagicMock` services.

**Tech Stack:** Python 3.12, fastmcp 3.2.4, google-api-python-client, google-auth 2.49, pytest + pytest-mock, ruff (pre-commit runs ruff on every commit).

**Spec:** `docs/superpowers/specs/2026-11-09-drive-tools-and-gmail-drafts-design.md`. Section numbers below refer to it.

---

## Working conventions

- Work in the worktree `/home/hermes_jimmy/repositories/private/hermes-google/.worktrees/feat-drive-tools-gmail-drafts` on branch `feat/drive-tools-gmail-drafts`. Every path below is relative to it.
- Interpreter and tools (the project's conda env):
  - `PY=/home/hermes_jimmy/miniconda3/envs/hermes-google/bin/python`
  - run tests with `$PY -m pytest <file>::<test> -v`, the full suite with `$PY -m pytest -q`
  - lint with `/home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
- Commit rules: one commit per task, message in the form shown, no trailers (no Co-Authored-By), no explanatory comments in code. The pre-commit hook runs ruff; if it reformats a file, `git add` it and commit again.
- Baseline before Task 1: 82 tests pass.

## File map

| File | Responsibility after this plan |
|---|---|
| `src/hermes_google/core/auth.py` | OAuth scopes, token file read (`stored_scopes`), credential load with scope check, service builders |
| `src/hermes_google/core/errors.py` | `ServiceError` base and `api_failure()` message helper |
| `src/hermes_google/core/drive.py` | Drive operations incl. `rename_file`, `create_folder`, name validation |
| `src/hermes_google/core/forward.py` | Forward unwrapping; now also Message-ID, References, To, Cc, Reply-To |
| `src/hermes_google/core/mail.py` | Gmail reading, labels, `MessageDetail` (send path removed) |
| `src/hermes_google/core/drafts.py` | NEW: recipients, `build_draft_raw`, `DraftRef`, `reply_context`, create/update/delete drafts |
| `src/hermes_google/mcp_server.py` | Tool surface and instructions |
| `src/hermes_google/cli.py` | `auth status` reports stored scopes |
| `tests/test_auth.py`, `tests/test_errors.py` (new), `tests/test_drive.py`, `tests/test_forward.py`, `tests/test_mail.py`, `tests/test_drafts.py` (new), `tests/test_mcp_server.py` | Tests |
| `README.md`, `pyproject.toml` | Docs and version |

---

### Task 1: Scopes and stored-scope check (spec section 2)

**Files:**
- Modify: `src/hermes_google/core/auth.py`
- Modify: `src/hermes_google/mcp_server.py` (the `auth_status` tool, lines 131-162)
- Modify: `src/hermes_google/cli.py` (`cmd_auth_status`, lines 49-63)
- Test: `tests/test_auth.py`, `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing auth tests**

Append to `tests/test_auth.py` (and add `stored_scopes` to the `from hermes_google.core.auth import (...)` block):

```python
def test_scopes_are_exactly_the_four_required() -> None:
    assert SCOPES == (
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/drive",
    )


def test_stored_scopes_reads_token_file(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"token": "t", "scopes": ["a", "b"]}))
    assert stored_scopes(path) == ["a", "b"]


def test_stored_scopes_without_key_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"token": "t"}))
    assert stored_scopes(path) == []


def test_stored_scopes_unreadable_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("not json")
    with pytest.raises(AuthError, match="unreadable"):
        stored_scopes(path)


def test_load_credentials_rejects_token_missing_required_scope(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    creds = _FakeCreds()
    creds._json["scopes"] = [s for s in SCOPES if not s.endswith("/drive")]
    save_credentials(creds, path)  # type: ignore[arg-type]
    with pytest.raises(AuthError, match="lacks scopes: https://www.googleapis.com/auth/drive;"):
        load_credentials(path)


def test_load_credentials_rejects_token_without_scopes_key(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"token": "t", "refresh_token": "r"}))
    with pytest.raises(AuthError, match="lacks scopes"):
        load_credentials(path)


def test_load_credentials_accepts_superset_of_scopes(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    path = tmp_path / "token.json"
    creds = _FakeCreds()
    creds._json["scopes"] = [*SCOPES, "https://www.googleapis.com/auth/drive.file"]
    save_credentials(creds, path)  # type: ignore[arg-type]
    mocker.patch.object(
        auth_module.Credentials, "from_authorized_user_file", return_value=_FakeCreds()
    )
    assert load_credentials(path).valid is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_auth.py -v`
Expected: ImportError on `stored_scopes` (collection fails). That counts as failing.

- [ ] **Step 3: Implement the scope list, `stored_scopes` and the check**

In `src/hermes_google/core/auth.py`, add `import json` next to `import os`, and replace the `SCOPES` tuple and `load_credentials`:

```python
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive",
)
```

```python
def stored_scopes(path: Path) -> list[str]:
    try:
        info = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise AuthError("credentials file is unreadable; run `hermes-google auth login`") from exc
    return [str(scope) for scope in info.get("scopes") or []]


def load_credentials(path: Path) -> Credentials:
    if not path.exists():
        raise AuthError("credentials not found; run `hermes-google auth login`")
    granted = set(stored_scopes(path))
    missing = [scope for scope in SCOPES if scope not in granted]
    if missing:
        raise AuthError(
            "stored token lacks scopes: "
            + ", ".join(missing)
            + "; run 'hermes-google auth login' to re-consent"
        )
    creds = Credentials.from_authorized_user_file(str(path), scopes=list(SCOPES))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_credentials(creds, path)
        else:
            raise AuthError(
                "credentials expired and cannot refresh; run `hermes-google auth login`"
            )
    return creds
```

Remove the comment line `# Drive: readonly covers files shared to us; drive.file covers own writes.`

- [ ] **Step 4: Run the auth tests**

Run: `$PY -m pytest tests/test_auth.py -v`
Expected: all pass (the pre-existing `test_load_credentials_refreshes_when_expired` still passes because `_FakeCreds` stores `list(SCOPES)`).

- [ ] **Step 5: Rewrite the three `auth_status` server tests**

In `tests/test_mcp_server.py`, add `from pathlib import Path` to the imports and replace `test_auth_status_tool_reports_validity`, `test_auth_status_missing_credentials` and `test_auth_status_config_error` with:

```python
def test_auth_status_tool_reports_stored_scopes(mocker) -> None:
    from hermes_google import mcp_server

    cfg = MagicMock(credentials_path=Path("/nonexistent/token.json"))
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    fake_creds = MagicMock(valid=True, expired=False, scopes=["requested-only"])
    mocker.patch.object(mcp_server, "_get_credentials", return_value=fake_creds)
    mocker.patch.object(
        mcp_server.auth_core,
        "stored_scopes",
        return_value=["https://www.googleapis.com/auth/drive"],
    )

    result = mcp_server.auth_status()
    assert result["valid"] is True
    assert result["expired"] is False
    assert result["scopes"] == ["https://www.googleapis.com/auth/drive"]
    mcp_server.auth_core.stored_scopes.assert_called_once_with(Path("/nonexistent/token.json"))


def test_auth_status_surfaces_auth_error_text(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.auth import AuthError

    mocker.patch.object(mcp_server, "_get_config", return_value=MagicMock())
    mocker.patch.object(
        mcp_server,
        "_get_credentials",
        side_effect=AuthError("stored token lacks scopes: x; run 'hermes-google auth login'"),
    )
    result = mcp_server.auth_status()
    assert result["valid"] is False
    assert result["scopes"] == []
    assert result["error"].startswith("stored token lacks scopes: x")
    assert "/home" not in result["error"]


def test_auth_status_config_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.config import ConfigError

    mocker.patch.object(mcp_server, "_get_config", side_effect=ConfigError("bad config"))
    result = mcp_server.auth_status()
    assert result["valid"] is False
    assert "configuration" in result["error"]
    assert "/home" not in result["error"]
```

- [ ] **Step 6: Run them to verify they fail**

Run: `$PY -m pytest tests/test_mcp_server.py -k auth_status -v`
Expected: the first two FAIL (`scopes` still comes from `creds.scopes`; error is still the fixed string).

- [ ] **Step 7: Update `auth_status` and the CLI**

In `src/hermes_google/mcp_server.py` replace the body of `auth_status`:

```python
@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
def auth_status() -> dict[str, Any]:
    """Report whether stored credentials are valid and loaded.

    Returns dict with keys: `valid` (bool), `expired` (bool), `scopes` (the
    OAuth scopes recorded in the stored token), and, only on failure, `error`
    (string describing the auth or config problem).
    """
    try:
        cfg = _get_config()
        creds = _get_credentials()
        return {
            "valid": bool(getattr(creds, "valid", False)),
            "expired": bool(getattr(creds, "expired", False)),
            "scopes": auth_core.stored_scopes(cfg.credentials_path),
        }
    except AuthError as exc:
        _reset_services()
        return {"valid": False, "expired": False, "scopes": [], "error": str(exc)}
    except ConfigError:
        _reset_services()
        return {
            "valid": False,
            "expired": False,
            "scopes": [],
            "error": "configuration missing or invalid; run setup script",
        }
```

In `src/hermes_google/cli.py`, in `cmd_auth_status`, replace `"scopes": list(getattr(creds, "scopes", []) or []),` with `"scopes": auth_core.stored_scopes(cfg.credentials_path),`.

- [ ] **Step 8: Run the full suite and lint**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass, no lint errors.

- [ ] **Step 9: Commit**

```bash
git add src/hermes_google/core/auth.py src/hermes_google/mcp_server.py src/hermes_google/cli.py tests/test_auth.py tests/test_mcp_server.py
git commit -m "feat: full Drive scope, drafts-only Gmail scope, stored-scope check on load

drive replaces drive.readonly and drive.file so Hermes can rename files
the user uploaded; gmail.send goes because the server will no longer
send. load_credentials refuses a token whose recorded scopes miss any
required one and names them, since google-auth only warns when a refresh
returns fewer scopes than requested. auth_status reports the token's
recorded scopes and the real error text."
```

---

### Task 2: API errors carry status and reason (spec section 3)

**Files:**
- Modify: `src/hermes_google/core/errors.py`
- Modify: `src/hermes_google/core/drive.py` (every `raise DriveError("... failed") from exc`)
- Modify: `src/hermes_google/core/mail.py` (every `raise MailError(...) from exc` that wraps an API call)
- Test: `tests/test_errors.py` (new), `tests/test_drive.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_errors.py`:

```python
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
```

Append to `tests/test_drive.py` (add `import httplib2` and `from googleapiclient.errors import HttpError` to its imports):

```python
def test_search_reports_api_reason(mock_drive_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 404, "reason": "Not Found"})
    content = b'{"error": {"code": 404, "message": "File not found: abc."}}'
    call = MagicMock()
    call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_drive_service.files().list.return_value = call

    with pytest.raises(DriveError, match="search failed: HTTP 404 File not found: abc."):
        search(mock_drive_service, query="abc")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_errors.py tests/test_drive.py::test_search_reports_api_reason -v`
Expected: ImportError on `api_failure`; the drive test fails with message `search failed`.

- [ ] **Step 3: Implement `api_failure`**

Append to `src/hermes_google/core/errors.py`:

```python
def api_failure(action: str, exc: BaseException) -> str:
    """Describe a failed API call: '<action> failed: HTTP <status> <reason>'.

    googleapiclient's HttpError exposes `status_code` and `reason`; any other
    exception is described by its type and text.
    """
    status = getattr(exc, "status_code", None)
    reason = getattr(exc, "reason", None)
    if status is not None and reason is not None:
        return f"{action} failed: HTTP {status} {reason}"
    return f"{action} failed: {type(exc).__name__}: {exc}"
```

- [ ] **Step 4: Apply it in drive.py and mail.py**

In `src/hermes_google/core/drive.py` add `from hermes_google.core.errors import ServiceError, api_failure` (replacing the existing errors import) and change each wrap:

| old | new |
|---|---|
| `raise DriveError("search failed") from exc` | `raise DriveError(api_failure("search", exc)) from exc` |
| `raise DriveError("list folder failed") from exc` | `raise DriveError(api_failure("list folder", exc)) from exc` |
| `raise DriveError("get metadata failed") from exc` | `raise DriveError(api_failure("get metadata", exc)) from exc` |
| `raise DriveError("upload failed") from exc` | `raise DriveError(api_failure("upload", exc)) from exc` |
| `raise DriveError("update failed") from exc` | `raise DriveError(api_failure("update", exc)) from exc` |
| `raise DriveError("move failed") from exc` | `raise DriveError(api_failure("move", exc)) from exc` |
| `raise DriveError("delete failed") from exc` | `raise DriveError(api_failure("delete", exc)) from exc` |

In `src/hermes_google/core/mail.py` add `api_failure` to the errors import and change:

| old | new |
|---|---|
| `raise MailError("failed to list messages") from exc` | `raise MailError(api_failure("list messages", exc)) from exc` |
| `raise MailError(f"failed to fetch message {message_id}") from exc` | `raise MailError(api_failure(f"fetch message {message_id}", exc)) from exc` |
| `raise MailError("failed to send draft") from exc` | `raise MailError(api_failure("send draft", exc)) from exc` |
| `raise MailError("failed to mark read") from exc` | `raise MailError(api_failure("mark read", exc)) from exc` |
| `raise MailError("failed to archive") from exc` | `raise MailError(api_failure("archive", exc)) from exc` |

The `malformed response`, `unexpected ... response format` and `unsafe filename` messages stay as they are.

- [ ] **Step 5: Run the full suite and lint**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_google/core/errors.py src/hermes_google/core/drive.py src/hermes_google/core/mail.py tests/test_errors.py tests/test_drive.py
git commit -m "fix: Drive and Gmail errors carry the Google status and reason

Every wrapped API failure read as a bare 'x failed' because the cause
was dropped at the ToolError boundary. api_failure appends the HttpError
status and reason, or the exception type and text, so Hermes can tell a
403 on a foreign file from a 404."
```

---

### Task 3: Drive name validation and `drive_rename` (spec sections 4.1 to 4.3)

**Files:**
- Modify: `src/hermes_google/core/drive.py`
- Modify: `src/hermes_google/mcp_server.py` (Drive section, after `drive_move`; policy 4 in `INSTRUCTIONS`)
- Test: `tests/test_drive.py`, `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing core tests**

Append to `tests/test_drive.py` (add `rename_file` to the import block):

```python
def test_rename_file_updates_name_and_returns_ref(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {
        "id": "f1",
        "name": "SMBC pack 01.pdf",
        "mimeType": "application/pdf",
    }
    mock_drive_service.files().update.return_value = call

    ref = rename_file(mock_drive_service, file_id="f1", new_name="  SMBC pack 01.pdf ")
    assert ref == FileRef(id="f1", name="SMBC pack 01.pdf", mime_type="application/pdf")
    _, kwargs = mock_drive_service.files().update.call_args
    assert kwargs["fileId"] == "f1"
    assert kwargs["body"] == {"name": "SMBC pack 01.pdf"}
    assert kwargs["fields"] == "id,name,mimeType"


@pytest.mark.parametrize("bad", ["", "   ", ".", "..", "a/b", "a\\b"])
def test_rename_file_rejects_unsafe_names(mock_drive_service: MagicMock, bad: str) -> None:
    with pytest.raises(DriveError, match="invalid name"):
        rename_file(mock_drive_service, file_id="f1", new_name=bad)
    mock_drive_service.files().update.assert_not_called()


def test_rename_file_malformed_response_raises(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"name": "x"}
    mock_drive_service.files().update.return_value = call
    with pytest.raises(DriveError, match="unexpected rename response"):
        rename_file(mock_drive_service, file_id="f1", new_name="x")


def test_rename_file_reports_api_reason(mock_drive_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 403, "reason": "Forbidden"})
    content = (
        b'{"error": {"code": 403, "message": "The user does not have sufficient '
        b'permissions for this file."}}'
    )
    call = MagicMock()
    call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_drive_service.files().update.return_value = call
    with pytest.raises(DriveError, match="rename failed: HTTP 403 The user does not have"):
        rename_file(mock_drive_service, file_id="f1", new_name="x")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_drive.py -v`
Expected: ImportError on `rename_file`.

- [ ] **Step 3: Implement validation and `rename_file`**

In `src/hermes_google/core/drive.py`, after `_to_ref`, add:

```python
_REF_FIELDS = "id,name,mimeType"


def _is_unsafe_name(name: str) -> bool:
    return not name or name in {".", ".."} or "/" in name or "\\" in name


def _validate_name(name: str) -> str:
    cleaned = name.strip()
    if _is_unsafe_name(cleaned):
        raise DriveError(f"invalid name: {name!r}")
    return cleaned
```

In `get_file`, replace the block from `# I1: validate filename before touching the filesystem.` through the first `raise DriveError(f"unsafe filename: {raw_name!r}")` with:

```python
    raw_name = meta["name"]
    safe_name = os.path.basename(raw_name)
    if safe_name != raw_name or _is_unsafe_name(safe_name):
        raise DriveError(f"unsafe filename: {raw_name!r}")
```

(The second containment check `# I1 (containment check)` stays.) Then add after `move_file`:

```python
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
```

- [ ] **Step 4: Run the drive tests**

Run: `$PY -m pytest tests/test_drive.py -v`
Expected: all pass, including `test_get_file_rejects_path_traversal_name`.

- [ ] **Step 5: Write the failing server tests**

In `tests/test_mcp_server.py`: add `"drive_rename"` to the `expected` set in `test_smoke_server_has_expected_tools`, add `"drive_rename"` to `idempotent_tools` in `test_idempotent_tools_annotated`, add `"drive_rename"` to the `required` list in `test_instructions_contains_key_policies`, and append:

```python
def test_drive_rename_tool_returns_ref(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import FileRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(
        mcp_server.drive_core,
        "rename_file",
        return_value=FileRef(id="f1", name="new.pdf", mime_type="application/pdf"),
    )
    result = mcp_server.drive_rename(file_id="f1", new_name="new.pdf")
    assert result == {"id": "f1", "name": "new.pdf", "mime_type": "application/pdf"}
    _, kwargs = spy.call_args
    assert kwargs == {"file_id": "f1", "new_name": "new.pdf"}
```

- [ ] **Step 6: Run them to verify they fail**

Run: `$PY -m pytest tests/test_mcp_server.py -v`
Expected: inventory, idempotent, instructions and the new test FAIL.

- [ ] **Step 7: Add the tool and the policy entry**

In `src/hermes_google/mcp_server.py`, in `INSTRUCTIONS` policy 4, change the list to:

```
4. Confirmation — all write operations (`cal_create_event`, `cal_update_event`,
   `cal_delete_event`, `drive_upload`, `drive_update`, `drive_move`,
   `drive_rename`, `drive_delete`) require the user to confirm the proposed
   action in chat before you invoke the tool.
```

After `drive_move` add:

```python
@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
@_auto_retry
def drive_rename(file_id: str, new_name: str) -> dict[str, Any]:
    """Rename a Drive file or folder. Requires user confirmation before calling.

    Works on anything Hermes can see, including files the user uploaded or
    shared. The name may not be empty or contain slashes.

    Returns dict with keys: `id`, `name` (as stored by Drive), `mime_type`.
    """
    services = _get_services()
    ref = drive_core.rename_file(services.drive, file_id=file_id, new_name=new_name)
    return asdict(ref)
```

- [ ] **Step 8: Run the full suite and lint**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/hermes_google/core/drive.py src/hermes_google/mcp_server.py tests/test_drive.py tests/test_mcp_server.py
git commit -m "feat: drive_rename tool

Renames any file or folder Hermes can see with a single files.update
and returns the stored id, name and MIME type. Names are validated the
way downloaded names already are, so whatever Hermes names stays
downloadable."
```

---

### Task 4: `drive_create_folder` (spec sections 4.2 and 4.3)

**Files:**
- Modify: `src/hermes_google/core/drive.py`
- Modify: `src/hermes_google/mcp_server.py`
- Test: `tests/test_drive.py`, `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing core tests**

Append to `tests/test_drive.py` (add `FOLDER_MIME_TYPE` and `create_folder` to the import block):

```python
def test_create_folder_sends_folder_mime_type_and_parent(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "d1", "name": "SMBC pack", "mimeType": FOLDER_MIME_TYPE}
    mock_drive_service.files().create.return_value = call

    ref = create_folder(mock_drive_service, name=" SMBC pack ", parent_folder_id="PARENT")
    assert ref == FileRef(id="d1", name="SMBC pack", mime_type=FOLDER_MIME_TYPE)
    _, kwargs = mock_drive_service.files().create.call_args
    assert kwargs["body"] == {
        "name": "SMBC pack",
        "mimeType": FOLDER_MIME_TYPE,
        "parents": ["PARENT"],
    }
    assert kwargs["fields"] == "id,name,mimeType"


def test_create_folder_without_parent_omits_parents(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "d1", "name": "x", "mimeType": FOLDER_MIME_TYPE}
    mock_drive_service.files().create.return_value = call

    create_folder(mock_drive_service, name="x")
    _, kwargs = mock_drive_service.files().create.call_args
    assert "parents" not in kwargs["body"]


def test_create_folder_rejects_unsafe_name(mock_drive_service: MagicMock) -> None:
    with pytest.raises(DriveError, match="invalid name"):
        create_folder(mock_drive_service, name="a/b")
    mock_drive_service.files().create.assert_not_called()


def test_create_folder_malformed_response_raises(mock_drive_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"name": "x"}
    mock_drive_service.files().create.return_value = call
    with pytest.raises(DriveError, match="unexpected create response"):
        create_folder(mock_drive_service, name="x")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_drive.py -v`
Expected: ImportError on `FOLDER_MIME_TYPE`.

- [ ] **Step 3: Implement `create_folder`**

In `src/hermes_google/core/drive.py`, next to `_REF_FIELDS` add `FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"`, and after `rename_file` add:

```python
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
```

- [ ] **Step 4: Run the drive tests**

Run: `$PY -m pytest tests/test_drive.py -v`
Expected: all pass.

- [ ] **Step 5: Write the failing server tests**

In `tests/test_mcp_server.py`: add `"drive_create_folder"` to `expected` in `test_smoke_server_has_expected_tools` and to `required` in `test_instructions_contains_key_policies`, and append:

```python
def test_drive_create_folder_uses_default_parent(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import FOLDER_MIME_TYPE, FileRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(drive_default_parent_folder_id="DEFAULT")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    spy = mocker.patch.object(
        mcp_server.drive_core,
        "create_folder",
        return_value=FileRef(id="d1", name="SMBC pack", mime_type=FOLDER_MIME_TYPE),
    )
    result = mcp_server.drive_create_folder(name="SMBC pack")
    assert result == {
        "id": "d1",
        "name": "SMBC pack",
        "mime_type": FOLDER_MIME_TYPE,
        "parent_folder_id": "DEFAULT",
    }
    _, kwargs = spy.call_args
    assert kwargs == {"name": "SMBC pack", "parent_folder_id": "DEFAULT"}


def test_drive_create_folder_explicit_parent_wins(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import FOLDER_MIME_TYPE, FileRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(drive_default_parent_folder_id="DEFAULT")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    spy = mocker.patch.object(
        mcp_server.drive_core,
        "create_folder",
        return_value=FileRef(id="d1", name="x", mime_type=FOLDER_MIME_TYPE),
    )
    result = mcp_server.drive_create_folder(name="x", parent_folder_id="P")
    assert result["parent_folder_id"] == "P"
    _, kwargs = spy.call_args
    assert kwargs["parent_folder_id"] == "P"
```

- [ ] **Step 6: Run them to verify they fail**

Run: `$PY -m pytest tests/test_mcp_server.py -v`
Expected: inventory, instructions and the two new tests FAIL.

- [ ] **Step 7: Add the tool and the policy entry**

In `INSTRUCTIONS` policy 4, insert `drive_create_folder` after `drive_rename`:

```
4. Confirmation — all write operations (`cal_create_event`, `cal_update_event`,
   `cal_delete_event`, `drive_upload`, `drive_update`, `drive_move`,
   `drive_rename`, `drive_create_folder`, `drive_delete`) require the user to
   confirm the proposed action in chat before you invoke the tool.
```

After `drive_rename` add:

```python
@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
@_auto_retry
def drive_create_folder(name: str, parent_folder_id: str | None = None) -> dict[str, Any]:
    """Create a Drive folder. Requires user confirmation before calling.

    If `parent_folder_id` is omitted, the folder is created in the configured
    default parent folder. Drive allows several folders with the same name in
    one parent, so list the parent with `drive_list` first.

    Returns dict with keys: `id`, `name`, `mime_type`, `parent_folder_id` (the
    parent used, or null for the account's own root).
    """
    services = _get_services()
    cfg = _get_config()
    parent = parent_folder_id or cfg.drive_default_parent_folder_id
    ref = drive_core.create_folder(services.drive, name=name, parent_folder_id=parent)
    return {**asdict(ref), "parent_folder_id": parent}
```

- [ ] **Step 8: Run the full suite and lint**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/hermes_google/core/drive.py src/hermes_google/mcp_server.py tests/test_drive.py tests/test_mcp_server.py
git commit -m "feat: drive_create_folder tool

Creates a folder under an explicit parent or the configured default
parent, the same resolution drive_upload uses, and returns the stored
id, name and MIME type plus the parent that was used."
```

---

### Task 5: Forwarded messages expose threading and recipient headers (spec section 5.2, fixes #950)

**Files:**
- Modify: `src/hermes_google/core/forward.py`
- Modify: `src/hermes_google/core/mail.py` (`MessageDetail`, `get_message`)
- Modify: `src/hermes_google/mcp_server.py` (`mail_get` docstring)
- Test: `tests/test_forward.py`, `tests/test_mail.py`

- [ ] **Step 1: Write the failing forward tests**

Append to `tests/test_forward.py`:

```python
def test_unwrap_direct_message_exposes_headers_and_normalises_folded_ids() -> None:
    raw = (
        b"From: Alice <alice@example.com>\r\n"
        b"To: Jimmy <jimmy@example.com>, hermes@example.com\r\n"
        b"Cc: Bob <bob@example.com>\r\n"
        b"Reply-To: Alice Work <alice@work.example>\r\n"
        b"Subject: Direct\r\n"
        b"Message-ID: <direct-1@example.com>\r\n"
        b"In-Reply-To: <a@example.com>\r\n\t<b@example.com>\r\n"
        b"References: <root@example.com>\r\n\t<a@example.com>\r\n"
        b'Content-Type: text/plain; charset="UTF-8"\r\n'
        b"\r\n"
        b"Body.\r\n"
    )
    msg = message_from_bytes(raw, policy=default_policy)
    original = unwrap(msg)  # type: ignore[arg-type]
    assert original.message_id == "<direct-1@example.com>"
    assert original.in_reply_to == "<a@example.com> <b@example.com>"
    assert original.references == "<root@example.com> <a@example.com>"
    assert original.to == "Jimmy <jimmy@example.com>, hermes@example.com"
    assert original.cc == "Bob <bob@example.com>"
    assert original.reply_to == "Alice Work <alice@work.example>"


def test_unwrap_direct_message_without_headers_yields_none() -> None:
    msg = EmailMessage()
    msg["From"] = "direct@example.com"
    msg["Subject"] = "Plain"
    msg.set_content("Body.")
    original = unwrap(msg)
    assert original.message_id is None
    assert original.references is None
    assert original.to is None
    assert original.cc is None
    assert original.reply_to is None


def test_unwrap_manual_forward_threads_from_wrapper_headers(fixtures_dir: Path) -> None:
    msg = _load(fixtures_dir, "fwd_plain_gmail_web.eml")
    msg["In-Reply-To"] = "<orig-001@acme.example>"
    msg["References"] = "<root@acme.example> <orig-001@acme.example>"
    original = unwrap(msg)
    assert original.message_id is None
    assert original.in_reply_to == "<orig-001@acme.example>"
    assert original.references == "<root@acme.example> <orig-001@acme.example>"
    assert original.to == "Jimmy Larsson <jimmy@example.com>"
    assert original.cc is None
    assert original.reply_to is None


def test_unwrap_manual_forward_reads_inner_cc_and_reply_to() -> None:
    msg = EmailMessage()
    msg["From"] = "Jimmy <jimmy@example.com>"
    msg["Subject"] = "Fwd: Agenda"
    msg.set_content(
        "---------- Forwarded message ---------\n"
        "From: Alex Chen <alex@board.example>\n"
        "Date: Wed, 22 Apr 2026 at 18:47\n"
        "Subject: Agenda\n"
        "To: Jimmy <jimmy@example.com>, Alexandra <alex@example.com>\n"
        "Cc: Board <board@board.example>\n"
        "Reply-To: Alex Work <alex.work@board.example>\n\n"
        "Body."
    )
    original = unwrap(msg)
    assert original.sender == "Alex Chen <alex@board.example>"
    assert original.to == "Jimmy <jimmy@example.com>, Alexandra <alex@example.com>"
    assert original.cc == "Board <board@board.example>"
    assert original.reply_to == "Alex Work <alex.work@board.example>"
    assert original.body == "Body."
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_forward.py -v`
Expected: the four new tests FAIL with `AttributeError: 'OriginalMessage' object has no attribute 'message_id'`.

- [ ] **Step 3: Implement the new fields in forward.py**

In `src/hermes_google/core/forward.py` replace `OriginalMessage`, `_KEEP_HEADERS` and `unwrap`, and add the two helpers:

```python
@dataclass(frozen=True)
class OriginalMessage:
    sender: str
    subject: str
    body: str
    in_reply_to: str | None
    forwarding_note: str | None
    message_id: str | None = None
    references: str | None = None
    to: str | None = None
    cc: str | None = None
    reply_to: str | None = None
```

```python
_KEEP_HEADERS = {"from", "subject", "date", "to", "cc", "reply-to"}
```

```python
def normalize_ids(value: object) -> str | None:
    """Collapse the whitespace of a Message-ID style header, keeping every id."""
    if value is None:
        return None
    return " ".join(str(value).split()) or None


def _header_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
```

```python
def unwrap(msg: EmailMessage) -> OriginalMessage:
    body = _get_plain_body(msg)
    split = _split_on_delimiter(body)

    if split is None:
        return OriginalMessage(
            sender=msg.get("From", ""),
            subject=msg.get("Subject", ""),
            body=body.strip(),
            in_reply_to=normalize_ids(msg.get("In-Reply-To")),
            forwarding_note=None,
            message_id=normalize_ids(msg.get("Message-ID")),
            references=normalize_ids(msg.get("References")),
            to=_header_or_none(msg.get("To")),
            cc=_header_or_none(msg.get("Cc")),
            reply_to=_header_or_none(msg.get("Reply-To")),
        )

    preamble, after = split
    headers, inner_body = _parse_inner_headers(after)
    note = preamble.strip() or None
    return OriginalMessage(
        sender=headers.get("from", msg.get("From", "")),
        subject=headers.get("subject", msg.get("Subject", "")),
        body=inner_body,
        in_reply_to=normalize_ids(msg.get("In-Reply-To")),
        forwarding_note=note,
        message_id=None,
        references=normalize_ids(msg.get("References")),
        to=headers.get("to"),
        cc=headers.get("cc"),
        reply_to=headers.get("reply-to"),
    )
```

- [ ] **Step 4: Run the forward tests**

Run: `$PY -m pytest tests/test_forward.py -v`
Expected: all pass (the existing `test_unwrap_gmail_web_plain` keeps `in_reply_to == "<thread@example.com>"`).

- [ ] **Step 5: Write the failing mail test**

Append to `tests/test_mail.py`:

```python
def test_get_message_exposes_threading_and_recipient_headers(
    tmp_path: Path, mock_gmail_service: MagicMock
) -> None:
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "hermes@example.com"
    msg["Cc"] = "Bob <bob@example.com>"
    msg["Subject"] = "Direct"
    msg["Message-ID"] = "<direct-1@example.com>"
    msg["References"] = "<root@example.com>"
    msg.set_content("Body.")
    raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    get_call = MagicMock()
    get_call.execute.return_value = {"id": "m1", "threadId": "t", "raw": raw_b64}
    mock_gmail_service.users().messages().get.return_value = get_call

    detail = get_message(mock_gmail_service, message_id="m1", cache_dir=tmp_path)
    assert detail.rfc_message_id == "<direct-1@example.com>"
    assert detail.references == "<root@example.com>"
    assert detail.in_reply_to is None
    assert detail.original_to == "hermes@example.com"
    assert detail.original_cc == "Bob <bob@example.com>"
    assert detail.original_reply_to is None
```

- [ ] **Step 6: Run it to verify it fails**

Run: `$PY -m pytest tests/test_mail.py::test_get_message_exposes_threading_and_recipient_headers -v`
Expected: FAIL with `AttributeError: 'MessageDetail' object has no attribute 'rfc_message_id'`.

- [ ] **Step 7: Extend `MessageDetail` and `get_message`**

In `src/hermes_google/core/mail.py`, append five defaulted fields to `MessageDetail`:

```python
@dataclass(frozen=True)
class MessageDetail:
    id: str
    thread_id: str
    sender: str
    original_sender: str
    original_subject: str
    original_body: str
    in_reply_to: str | None
    forwarding_note: str | None
    attachment_paths: list[Path]
    rfc_message_id: str | None = None
    references: str | None = None
    original_to: str | None = None
    original_cc: str | None = None
    original_reply_to: str | None = None
```

and in `get_message` extend the return:

```python
    return MessageDetail(
        id=resp["id"],
        thread_id=resp.get("threadId", ""),
        sender=sender,
        original_sender=original.sender,
        original_subject=original.subject,
        original_body=original.body,
        in_reply_to=original.in_reply_to,
        forwarding_note=original.forwarding_note,
        attachment_paths=attachments,
        rfc_message_id=original.message_id,
        references=original.references,
        original_to=original.to,
        original_cc=original.cc,
        original_reply_to=original.reply_to,
    )
```

In `src/hermes_google/mcp_server.py`, replace the `mail_get` docstring:

```python
    """Fetch a single email by ID. Unwraps forwarded messages to extract the original.

    Returns dict with keys: `id`, `thread_id`, `sender` (the account that
    forwarded this message to Hermes), `original_sender`, `original_subject`,
    `original_body` (plain text), `original_to`, `original_cc`,
    `original_reply_to`, `rfc_message_id`, `in_reply_to`, `references` (RFC 822
    threading headers; `mail_create_reply_draft` uses them for you),
    `forwarding_note` (text the user wrote above the forward delimiter, or
    null), `attachment_paths` (list of local file paths in ~/.cache/hermes-google/).
    """
```

- [ ] **Step 8: Run the full suite and lint**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass; `test_mail_get_tool_serializes_attachment_paths` still constructs `MessageDetail` positionally and passes.

- [ ] **Step 9: Commit**

```bash
git add src/hermes_google/core/forward.py src/hermes_google/core/mail.py src/hermes_google/mcp_server.py tests/test_forward.py tests/test_mail.py
git commit -m "fix: forwarded messages expose Message-ID, References and recipients

unwrap only kept In-Reply-To, so replies could not be threaded under the
right parent (#950). Direct and filter-forwarded mail now expose their
own Message-ID, References, To, Cc and Reply-To; manual forwards keep
the wrapper's In-Reply-To and References, which point at the forwarded
message, and read To, Cc and Reply-To from the inner header block. Ids
are whitespace-normalised so folded multi-id headers survive."
```

---

### Task 6: Draft recipients and `build_draft_raw` (spec section 5.3, first half)

**Files:**
- Create: `src/hermes_google/core/drafts.py`
- Test: `tests/test_drafts.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_drafts.py`:

```python
"""Tests for drafts.py: recipients, draft building, reply context, Gmail Drafts calls."""

from __future__ import annotations

import base64
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_google.core.drafts import (
    Recipient,
    build_draft_raw,
    parse_recipients,
)
from hermes_google.core.mail import MailError


def _decode(raw_b64: str) -> EmailMessage:
    return message_from_bytes(  # type: ignore[return-value]
        base64.urlsafe_b64decode(raw_b64), policy=default_policy
    )


def test_parse_recipients_accepts_plain_and_named_addresses() -> None:
    got = parse_recipients(["a@x.com", "Jimmy Larsson <j@x.com>"])
    assert got == [Recipient(name="", addr="a@x.com"), Recipient(name="Jimmy Larsson", addr="j@x.com")]


def test_parse_recipients_keeps_quoted_comma_name_as_one_recipient() -> None:
    assert parse_recipients(['"Larsson, Jimmy" <j@x.com>']) == [
        Recipient(name="Larsson, Jimmy", addr="j@x.com")
    ]


def test_parse_recipients_accepts_non_ascii_display_name() -> None:
    assert parse_recipients(["Jörg Müller <j@x.com>"]) == [
        Recipient(name="Jörg Müller", addr="j@x.com")
    ]


def test_parse_recipients_skips_blank_entries() -> None:
    assert parse_recipients(["", "  ", "a@x.com"]) == [Recipient(name="", addr="a@x.com")]


@pytest.mark.parametrize("bad", ["Larsson", "Jörg <jörg@x.com>", "Larsson, Jimmy <j@x.com>", "<>"])
def test_parse_recipients_rejects_unusable_entries(bad: str) -> None:
    with pytest.raises(MailError, match="invalid recipient"):
        parse_recipients([bad])


def test_recipient_render_quotes_comma_names_and_round_trips() -> None:
    rendered = Recipient(name="Larsson, Jimmy", addr="j@x.com").render()
    assert rendered == '"Larsson, Jimmy" <j@x.com>'
    assert parse_recipients([rendered]) == [Recipient(name="Larsson, Jimmy", addr="j@x.com")]
    assert Recipient(name="", addr="j@x.com").render() == "j@x.com"
    assert Recipient(name="Jörg Müller", addr="j@x.com").render() == "Jörg Müller <j@x.com>"


def test_build_draft_raw_sets_headers_and_body() -> None:
    raw = build_draft_raw(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com")],
        subject="Re: Hello",
        body="Hi Alice",
        in_reply_to="<orig@example.com>",
        references="<root@example.com> <orig@example.com>",
    )
    msg = _decode(raw)
    assert [(a.display_name, a.addr_spec) for a in msg["To"].addresses] == [
        ("Alice", "alice@example.com")
    ]
    assert [a.addr_spec for a in msg["Cc"].addresses] == ["bob@example.com"]
    assert msg["Subject"] == "Re: Hello"
    assert msg["In-Reply-To"] == "<orig@example.com>"
    assert msg["References"] == "<root@example.com> <orig@example.com>"
    assert "From" not in msg
    assert msg.get_body(preferencelist=("plain",)).get_content() == "Hi Alice\n"


def test_build_draft_raw_omits_optional_headers() -> None:
    msg = _decode(build_draft_raw(to=[Recipient("", "a@x.com")], subject="s", body="b"))
    assert "Cc" not in msg
    assert "In-Reply-To" not in msg
    assert "References" not in msg


def test_build_draft_raw_references_default_to_in_reply_to() -> None:
    msg = _decode(
        build_draft_raw(
            to=[Recipient("", "a@x.com")], subject="s", body="b", in_reply_to="<p@x.com>"
        )
    )
    assert msg["References"] == "<p@x.com>"


def test_build_draft_raw_renders_non_ascii_names_readably() -> None:
    msg = _decode(
        build_draft_raw(
            to=[Recipient("Jörg Müller", "j@x.com"), Recipient("Larsson, Jimmy", "k@x.com")],
            subject="s",
            body="b",
        )
    )
    assert [(a.display_name, a.addr_spec) for a in msg["To"].addresses] == [
        ("Jörg Müller", "j@x.com"),
        ("Larsson, Jimmy", "k@x.com"),
    ]


def test_build_draft_raw_requires_a_recipient() -> None:
    with pytest.raises(MailError, match="at least one To recipient"):
        build_draft_raw(to=[], subject="s", body="b")


def test_build_draft_raw_rejects_multiline_subject() -> None:
    with pytest.raises(MailError, match="single line"):
        build_draft_raw(to=[Recipient("", "a@x.com")], subject="a\nb", body="b")


def test_build_draft_raw_attaches_files(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    msg = _decode(
        build_draft_raw(
            to=[Recipient("", "a@x.com")], subject="s", body="b", attachments=[pdf]
        )
    )
    parts = list(msg.iter_attachments())
    assert [(p.get_filename(), p.get_content_type()) for p in parts] == [
        ("report.pdf", "application/pdf")
    ]
    assert parts[0].get_payload(decode=True) == b"%PDF-1.4 fake"
    assert msg.get_body(preferencelist=("plain",)).get_content() == "b\n"


def test_build_draft_raw_missing_attachment_raises(tmp_path: Path) -> None:
    with pytest.raises(MailError, match="attachment not found"):
        build_draft_raw(
            to=[Recipient("", "a@x.com")],
            subject="s",
            body="b",
            attachments=[tmp_path / "nope.pdf"],
        )


def test_build_draft_raw_carries_existing_parts(tmp_path: Path) -> None:
    txt = tmp_path / "a.txt"
    txt.write_bytes(b"one")
    first = _decode(
        build_draft_raw(to=[Recipient("", "a@x.com")], subject="s", body="b", attachments=[txt])
    )
    parts = list(first.iter_attachments())

    second = _decode(
        build_draft_raw(
            to=[Recipient("", "a@x.com")], subject="s", body="new", attachment_parts=parts
        )
    )
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in second.iter_attachments()] == [
        ("a.txt", b"one")
    ]
    assert second.get_body(preferencelist=("plain",)).get_content() == "new\n"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_drafts.py -v`
Expected: `ModuleNotFoundError: No module named 'hermes_google.core.drafts'`.

- [ ] **Step 3: Create `core/drafts.py` with recipients and the builder**

Create `src/hermes_google/core/drafts.py`:

```python
"""Gmail drafts for the Hermes mailbox: build RFC 822 drafts and store them.

Every function that talks to Gmail takes a `service` argument. Nothing in this
module can send mail: the only Gmail calls are users().drafts() create, get,
update and delete.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.policy import default as default_policy
from pathlib import Path

from hermes_google.core.mail import MailError

_ADDR_SPEC_RE = re.compile(r"[^\s@]+@[^\s@]+")


@dataclass(frozen=True)
class Recipient:
    name: str
    addr: str

    def render(self) -> str:
        return str(Address(display_name=self.name, addr_spec=self.addr))


def _parse_header_addresses(value: str) -> tuple[list[Recipient], list[str]]:
    """Parse an address header value into (usable recipients, rejected entries)."""
    header = default_policy.header_factory("To", value)
    good: list[Recipient] = []
    bad: list[str] = []
    for address in header.addresses:
        spec = address.addr_spec
        if spec.isascii() and _ADDR_SPEC_RE.fullmatch(spec):
            good.append(Recipient(name=address.display_name, addr=spec))
        else:
            bad.append(str(address))
    return good, bad


def parse_recipients(entries: list[str]) -> list[Recipient]:
    """Strictly parse user-supplied recipients ('addr' or 'Name <addr>')."""
    out: list[Recipient] = []
    for entry in entries:
        if not entry.strip():
            continue
        good, bad = _parse_header_addresses(entry)
        if bad or not good:
            raise MailError(f"invalid recipient: {entry!r}")
        out.extend(good)
    return out


def build_draft_raw(
    *,
    to: list[Recipient],
    subject: str,
    body: str,
    cc: list[Recipient] | None = None,
    attachments: list[Path] | None = None,
    attachment_parts: list[Message] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    if not to:
        raise MailError("a draft needs at least one To recipient")
    if "\n" in subject or "\r" in subject:
        raise MailError("the subject must be a single line")
    msg = EmailMessage()
    msg["To"] = ", ".join(r.render() for r in to)
    if cc:
        msg["Cc"] = ", ".join(r.render() for r in cc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references or in_reply_to:
        msg["References"] = references or in_reply_to
    msg.set_content(body)
    for path in attachments or []:
        if not path.is_file():
            raise MailError(f"attachment not found: {path}")
        mime_type, _ = mimetypes.guess_type(str(path))
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    for part in attachment_parts or []:
        maintype, subtype = part.get_content_type().split("/", 1)
        msg.add_attachment(
            part.get_payload(decode=True) or b"",
            maintype=maintype,
            subtype=subtype,
            filename=part.get_filename() or "attachment",
        )
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
```

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest tests/test_drafts.py -v`
Expected: all pass. If `test_build_draft_raw_carries_existing_parts` fails on the text part, check `part.get_content_type()` for the carried part is `text/plain` and the payload decodes to `b"one"`; `add_attachment` with bytes and `maintype="text"` base64-encodes it, which is correct.

- [ ] **Step 5: Lint**

Run: `/home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: clean (ruff may reflow the long list in `test_parse_recipients_accepts_plain_and_named_addresses`; that is fine).

- [ ] **Step 6: Commit**

```bash
git add src/hermes_google/core/drafts.py tests/test_drafts.py
git commit -m "feat: Gmail draft builder with validated recipients and attachments

Recipients are parsed with the email.headerregistry parser, which keeps
a quoted comma name as one address and decodes encoded words, and are
rendered back through Address so they survive the round trip. The
builder emits the RFC 822 draft Gmail expects in message.raw, with no
From header and optional threading headers and attachments."
```

---

### Task 7: `DraftRef`, `reply_context`, `create_draft`, `delete_draft` (spec section 5.3, second half)

**Files:**
- Modify: `src/hermes_google/core/drafts.py`
- Test: `tests/test_drafts.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_drafts.py`, extend the import block to:

```python
import httplib2
from googleapiclient.errors import HttpError

from hermes_google.core.drafts import (
    DraftRef,
    Recipient,
    build_draft_raw,
    create_draft,
    delete_draft,
    parse_recipients,
    reply_context,
)
from hermes_google.core.mail import MailError, MessageDetail
```

and append:

```python
USER = "jimmy@example.com"
HERMES = "hermes@example.com"


def _detail(**overrides) -> MessageDetail:
    base = dict(
        id="m1",
        thread_id="t1",
        sender="Alice <alice@example.com>",
        original_sender="Alice <alice@example.com>",
        original_subject="Hello",
        original_body="...",
        in_reply_to=None,
        forwarding_note=None,
        attachment_paths=[],
    )
    base.update(overrides)
    return MessageDetail(**base)


def _ctx(**overrides):
    return reply_context(_detail(**overrides), user_email=USER, hermes_email=HERMES)


def test_reply_context_reply_all_drops_own_addresses_and_duplicates() -> None:
    ctx = _ctx(
        original_to=(
            "Jimmy <jimmy@example.com>, Hermes <hermes@example.com>, Carol <carol@example.com>"
        ),
        original_cc="Dave <dave@example.com>, carol@example.com, JIMMY@example.com",
        rfc_message_id="<orig@example.com>",
    )
    assert [r.addr for r in ctx.to] == ["alice@example.com", "carol@example.com"]
    assert [r.addr for r in ctx.cc] == ["dave@example.com"]
    assert ctx.warning is None


def test_reply_context_prefers_reply_to_over_sender() -> None:
    ctx = _ctx(original_reply_to="Alice Work <alice@work.example>")
    assert [r.addr for r in ctx.to] == ["alice@work.example"]


def test_reply_context_prefixes_re_once() -> None:
    assert _ctx(original_subject="Hello").subject == "Re: Hello"
    assert _ctx(original_subject="RE: Hello").subject == "RE: Hello"
    assert _ctx(original_subject="re: Hello").subject == "re: Hello"


def test_reply_context_threads_intact_headers_with_thread_id() -> None:
    ctx = _ctx(
        rfc_message_id="<orig@example.com>",
        references="<root@example.com>",
        in_reply_to="<root@example.com>",
    )
    assert ctx.in_reply_to == "<orig@example.com>"
    assert ctx.references == "<root@example.com> <orig@example.com>"
    assert ctx.thread_id == "t1"


def test_reply_context_intact_headers_without_references_use_in_reply_to() -> None:
    ctx = _ctx(rfc_message_id="<orig@x>", in_reply_to="<prev@x>")
    assert ctx.references == "<prev@x> <orig@x>"


def test_reply_context_intact_thread_starter_references_only_itself() -> None:
    ctx = _ctx(rfc_message_id="<orig@x>")
    assert ctx.in_reply_to == "<orig@x>"
    assert ctx.references == "<orig@x>"


def test_reply_context_manual_forward_uses_wrapper_headers_without_thread_id() -> None:
    ctx = _ctx(
        rfc_message_id=None,
        in_reply_to="<orig@acme.example>",
        references="<root@acme.example> <orig@acme.example>",
        original_sender="Acme <billing@acme.example>",
    )
    assert [r.addr for r in ctx.to] == ["billing@acme.example"]
    assert ctx.in_reply_to == "<orig@acme.example>"
    assert ctx.references == "<root@acme.example> <orig@acme.example>"
    assert ctx.thread_id is None


def test_reply_context_manual_forward_without_wrapper_headers_has_no_threading() -> None:
    ctx = _ctx(rfc_message_id=None)
    assert ctx.in_reply_to is None
    assert ctx.references is None
    assert ctx.thread_id is None


def test_reply_context_falls_back_to_sender_when_everyone_is_filtered() -> None:
    ctx = _ctx(original_sender="Jimmy <jimmy@example.com>", original_to="hermes@example.com")
    assert [r.addr for r in ctx.to] == ["jimmy@example.com"]
    assert ctx.cc == []


def test_reply_context_drops_bad_header_entries_into_warning() -> None:
    ctx = _ctx(original_to="Jörg <jörg@example.com>, Carol <carol@example.com>")
    assert [r.addr for r in ctx.to] == ["alice@example.com", "carol@example.com"]
    assert ctx.warning is not None
    assert "jörg@example.com" in ctx.warning


def test_reply_context_fails_when_no_recipient_is_usable() -> None:
    with pytest.raises(MailError, match="no usable reply recipient"):
        _ctx(original_sender="Jörg <jörg@example.com>")


def test_reply_context_keeps_comma_names_quoted_for_rendering() -> None:
    ctx = _ctx(original_sender='"Larsson, Jimmy" <jl@example.com>')
    rendered = ctx.to[0].render()
    assert rendered == '"Larsson, Jimmy" <jl@example.com>'
    assert parse_recipients([rendered]) == [Recipient("Larsson, Jimmy", "jl@example.com")]


def test_create_draft_posts_raw_and_thread_id(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {
        "id": "d1",
        "message": {"id": "m9", "threadId": "t1", "labelIds": ["DRAFT"]},
    }
    mock_gmail_service.users().drafts().create.return_value = call

    ref = create_draft(
        mock_gmail_service,
        to=[Recipient("Alice", "alice@example.com")],
        subject="Re: Hello",
        body="Hi",
        thread_id="t1",
    )
    assert ref == DraftRef(
        draft_id="d1",
        message_id="m9",
        thread_id="t1",
        to=["Alice <alice@example.com>"],
        cc=[],
        subject="Re: Hello",
        warning=None,
    )
    _, kwargs = mock_gmail_service.users().drafts().create.call_args
    assert kwargs["userId"] == "me"
    assert kwargs["body"]["message"]["threadId"] == "t1"
    assert _decode(kwargs["body"]["message"]["raw"])["Subject"] == "Re: Hello"


def test_create_draft_omits_thread_id_when_none(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "d1", "message": {"id": "m9", "threadId": "t-new"}}
    mock_gmail_service.users().drafts().create.return_value = call

    ref = create_draft(mock_gmail_service, to=[Recipient("", "a@x.com")], subject="s", body="b")
    assert ref.thread_id == "t-new"
    _, kwargs = mock_gmail_service.users().drafts().create.call_args
    assert "threadId" not in kwargs["body"]["message"]


def test_create_draft_malformed_response_raises(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "d1"}
    mock_gmail_service.users().drafts().create.return_value = call
    with pytest.raises(MailError, match="unexpected draft response"):
        create_draft(mock_gmail_service, to=[Recipient("", "a@x.com")], subject="s", body="b")


def test_create_draft_reports_api_reason(mock_gmail_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 403, "reason": "Forbidden"})
    content = b'{"error": {"code": 403, "message": "Insufficient Permission"}}'
    call = MagicMock()
    call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_gmail_service.users().drafts().create.return_value = call
    with pytest.raises(MailError, match="create draft failed: HTTP 403 Insufficient Permission"):
        create_draft(mock_gmail_service, to=[Recipient("", "a@x.com")], subject="s", body="b")


def test_delete_draft_calls_gmail(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = ""
    mock_gmail_service.users().drafts().delete.return_value = call
    delete_draft(mock_gmail_service, draft_id="d1")
    _, kwargs = mock_gmail_service.users().drafts().delete.call_args
    assert kwargs == {"userId": "me", "id": "d1"}


def test_delete_draft_reports_api_reason(mock_gmail_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 404, "reason": "Not Found"})
    content = b'{"error": {"code": 404, "message": "Requested entity was not found."}}'
    call = MagicMock()
    call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_gmail_service.users().drafts().delete.return_value = call
    with pytest.raises(MailError, match="delete draft d1 failed: HTTP 404"):
        delete_draft(mock_gmail_service, draft_id="d1")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_drafts.py -v`
Expected: ImportError on `DraftRef`.

- [ ] **Step 3: Implement**

In `src/hermes_google/core/drafts.py`, extend the imports:

```python
from typing import Any

from hermes_google.core.errors import api_failure
from hermes_google.core.mail import MailError, MessageDetail
```

and append:

```python
@dataclass(frozen=True)
class DraftRef:
    draft_id: str
    message_id: str
    thread_id: str | None
    to: list[str]
    cc: list[str]
    subject: str
    warning: str | None = None


@dataclass(frozen=True)
class ReplyContext:
    to: list[Recipient]
    cc: list[Recipient]
    subject: str
    in_reply_to: str | None
    references: str | None
    thread_id: str | None
    warning: str | None


def _draft_ref(
    resp: dict[str, Any], *, to: list[Recipient], cc: list[Recipient], subject: str
) -> DraftRef:
    try:
        message = resp["message"]
        return DraftRef(
            draft_id=resp["id"],
            message_id=message["id"],
            thread_id=message.get("threadId"),
            to=[r.render() for r in to],
            cc=[r.render() for r in cc],
            subject=subject,
        )
    except (KeyError, TypeError) as exc:
        raise MailError("unexpected draft response format") from exc


def _message_body(raw: str, thread_id: str | None) -> dict[str, Any]:
    message: dict[str, Any] = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    return {"message": message}


def create_draft(
    service: Any,
    *,
    to: list[Recipient],
    subject: str,
    body: str,
    cc: list[Recipient] | None = None,
    attachments: list[Path] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    thread_id: str | None = None,
) -> DraftRef:
    raw = build_draft_raw(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        attachments=attachments,
        in_reply_to=in_reply_to,
        references=references,
    )
    try:
        resp = (
            service.users()
            .drafts()
            .create(userId="me", body=_message_body(raw, thread_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure("create draft", exc)) from exc
    return _draft_ref(resp, to=to, cc=cc or [], subject=subject)


def delete_draft(service: Any, *, draft_id: str) -> None:
    try:
        service.users().drafts().delete(userId="me", id=draft_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure(f"delete draft {draft_id}", exc)) from exc


def _reply_subject(subject: str) -> str:
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _dedupe(recipients: list[Recipient], *, exclude: set[str]) -> list[Recipient]:
    seen: set[str] = set()
    out: list[Recipient] = []
    for recipient in recipients:
        key = recipient.addr.lower()
        if key in exclude or key in seen:
            continue
        seen.add(key)
        out.append(recipient)
    return out


def reply_context(detail: MessageDetail, *, user_email: str, hermes_email: str) -> ReplyContext:
    rejected: list[str] = []

    def parse(value: str | None) -> list[Recipient]:
        if not value:
            return []
        good, bad = _parse_header_addresses(str(value))
        rejected.extend(bad)
        return good

    origin = parse(detail.original_reply_to) or parse(detail.original_sender)
    own = {user_email.lower(), hermes_email.lower()}
    to = _dedupe(origin + parse(detail.original_to), exclude=own)
    if not to:
        to = _dedupe(origin, exclude=set())
    if not to:
        raise MailError("no usable reply recipient; pass to explicitly")
    cc = _dedupe(parse(detail.original_cc), exclude=own | {r.addr.lower() for r in to})

    if detail.rfc_message_id:
        parent: str | None = detail.rfc_message_id
        chain = detail.references or detail.in_reply_to
        references: str | None = f"{chain} {parent}" if chain else parent
        thread_id: str | None = detail.thread_id or None
    else:
        parent = detail.in_reply_to
        references = detail.references or parent
        thread_id = None

    warning = f"ignored unusable addresses: {', '.join(rejected)}" if rejected else None
    return ReplyContext(
        to=to,
        cc=cc,
        subject=_reply_subject(detail.original_subject),
        in_reply_to=parent,
        references=references,
        thread_id=thread_id,
        warning=warning,
    )
```

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest tests/test_drafts.py -v`
Expected: all pass.

- [ ] **Step 5: Lint and full suite**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_google/core/drafts.py tests/test_drafts.py
git commit -m "feat: reply context and draft create/delete for the Hermes mailbox

reply_context derives reply-all recipients from the original headers,
dropping the Hermes and user addresses and anything unusable (reported
in a warning), prefixes Re: once, and threads: a message with its own
Message-ID gets In-Reply-To, References and the Gmail threadId; a manual
forward reuses the wrapper's In-Reply-To and References and no threadId.
create_draft and delete_draft wrap users.drafts and read the nested
Draft resource."
```

---

### Task 8: `update_draft` (spec section 5.3, update semantics)

**Files:**
- Modify: `src/hermes_google/core/drafts.py`
- Test: `tests/test_drafts.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_drafts.py` add `update_draft` to the drafts import block and append:

```python
def _stored_draft(mock_gmail_service: MagicMock, tmp_path: Path) -> MagicMock:
    txt = tmp_path / "a.txt"
    txt.write_bytes(b"one")
    raw = build_draft_raw(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com")],
        subject="Re: Hello",
        body="old body",
        attachments=[txt],
        in_reply_to="<orig@example.com>",
        references="<root@example.com> <orig@example.com>",
    )
    get_call = MagicMock()
    get_call.execute.return_value = {
        "id": "d1",
        "message": {"id": "m1", "threadId": "t1", "raw": raw},
    }
    mock_gmail_service.users().drafts().get.return_value = get_call
    update_call = MagicMock()
    update_call.execute.return_value = {"id": "d1", "message": {"id": "m2", "threadId": "t1"}}
    mock_gmail_service.users().drafts().update.return_value = update_call
    return update_call


def _updated_message(mock_gmail_service: MagicMock) -> tuple[EmailMessage, dict]:
    _, kwargs = mock_gmail_service.users().drafts().update.call_args
    return _decode(kwargs["body"]["message"]["raw"]), kwargs


def test_update_draft_changes_body_and_keeps_everything_else(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)

    ref = update_draft(mock_gmail_service, draft_id="d1", body="new body")

    assert ref.draft_id == "d1"
    assert ref.message_id == "m2"
    assert ref.to == ["Alice <alice@example.com>"]
    assert ref.cc == ["bob@example.com"]
    assert ref.subject == "Re: Hello"
    _, get_kwargs = mock_gmail_service.users().drafts().get.call_args
    assert get_kwargs == {"userId": "me", "id": "d1", "format": "raw"}
    msg, kwargs = _updated_message(mock_gmail_service)
    assert kwargs["userId"] == "me"
    assert kwargs["id"] == "d1"
    assert kwargs["body"]["message"]["threadId"] == "t1"
    assert [a.addr_spec for a in msg["To"].addresses] == ["alice@example.com"]
    assert [a.addr_spec for a in msg["Cc"].addresses] == ["bob@example.com"]
    assert msg["Subject"] == "Re: Hello"
    assert msg["In-Reply-To"] == "<orig@example.com>"
    assert msg["References"] == "<root@example.com> <orig@example.com>"
    assert msg.get_body(preferencelist=("plain",)).get_content() == "new body\n"
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in msg.iter_attachments()] == [
        ("a.txt", b"one")
    ]


def test_update_draft_empty_cc_clears_cc(mock_gmail_service: MagicMock, tmp_path: Path) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    ref = update_draft(mock_gmail_service, draft_id="d1", cc=[])
    assert ref.cc == []
    msg, _ = _updated_message(mock_gmail_service)
    assert "Cc" not in msg


def test_update_draft_empty_attachments_removes_all(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    update_draft(mock_gmail_service, draft_id="d1", attachments=[])
    msg, _ = _updated_message(mock_gmail_service)
    assert list(msg.iter_attachments()) == []
    assert msg.get_body(preferencelist=("plain",)).get_content() == "old body\n"


def test_update_draft_new_attachments_replace_stored_ones(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF two")
    update_draft(mock_gmail_service, draft_id="d1", attachments=[pdf])
    msg, _ = _updated_message(mock_gmail_service)
    assert [p.get_filename() for p in msg.iter_attachments()] == ["b.pdf"]


def test_update_draft_replaces_recipients_and_subject(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    ref = update_draft(
        mock_gmail_service,
        draft_id="d1",
        to=[Recipient("Carol", "carol@example.com")],
        subject="Re: Hello again",
    )
    assert ref.to == ["Carol <carol@example.com>"]
    assert ref.cc == ["bob@example.com"]
    msg, _ = _updated_message(mock_gmail_service)
    assert [a.addr_spec for a in msg["To"].addresses] == ["carol@example.com"]
    assert msg["Subject"] == "Re: Hello again"


def test_update_draft_with_nothing_to_change_raises(mock_gmail_service: MagicMock) -> None:
    with pytest.raises(MailError, match="nothing to update"):
        update_draft(mock_gmail_service, draft_id="d1")
    mock_gmail_service.users().drafts().get.assert_not_called()


def test_update_draft_malformed_get_response_raises(mock_gmail_service: MagicMock) -> None:
    get_call = MagicMock()
    get_call.execute.return_value = {"id": "d1", "threadId": "t1", "raw": "abc"}
    mock_gmail_service.users().drafts().get.return_value = get_call
    with pytest.raises(MailError, match="unexpected draft response"):
        update_draft(mock_gmail_service, draft_id="d1", body="x")


def test_update_draft_reports_api_reason_on_fetch(mock_gmail_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 404, "reason": "Not Found"})
    content = b'{"error": {"code": 404, "message": "Requested entity was not found."}}'
    get_call = MagicMock()
    get_call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_gmail_service.users().drafts().get.return_value = get_call
    with pytest.raises(MailError, match="fetch draft d1 failed: HTTP 404"):
        update_draft(mock_gmail_service, draft_id="d1", body="x")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_drafts.py -v`
Expected: ImportError on `update_draft`.

- [ ] **Step 3: Implement `update_draft`**

In `src/hermes_google/core/drafts.py` add to the imports:

```python
import binascii
from email import message_from_bytes

from hermes_google.core.forward import normalize_ids
```

and append:

```python
@dataclass(frozen=True)
class _StoredDraft:
    to: list[Recipient]
    cc: list[Recipient]
    subject: str
    body: str
    attachment_parts: list[Message]
    in_reply_to: str | None
    references: str | None
    thread_id: str | None


def _load_stored_draft(service: Any, draft_id: str) -> _StoredDraft:
    try:
        resp = service.users().drafts().get(userId="me", id=draft_id, format="raw").execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure(f"fetch draft {draft_id}", exc)) from exc
    try:
        message = resp["message"]
        raw_bytes = base64.urlsafe_b64decode(message["raw"])
        thread_id = message.get("threadId")
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise MailError("unexpected draft response format") from exc
    parsed = message_from_bytes(raw_bytes, policy=default_policy)
    to, _ = _parse_header_addresses(str(parsed.get("To", "")))
    cc, _ = _parse_header_addresses(str(parsed.get("Cc", "")))
    body_part = parsed.get_body(preferencelist=("plain",))
    body = body_part.get_content() if body_part is not None else ""
    return _StoredDraft(
        to=to,
        cc=cc,
        subject=str(parsed.get("Subject", "")),
        body=body.rstrip("\n"),
        attachment_parts=list(parsed.iter_attachments()),
        in_reply_to=normalize_ids(parsed.get("In-Reply-To")),
        references=normalize_ids(parsed.get("References")),
        thread_id=thread_id,
    )


def update_draft(
    service: Any,
    *,
    draft_id: str,
    to: list[Recipient] | None = None,
    cc: list[Recipient] | None = None,
    subject: str | None = None,
    body: str | None = None,
    attachments: list[Path] | None = None,
) -> DraftRef:
    if to is None and cc is None and subject is None and body is None and attachments is None:
        raise MailError("nothing to update")
    stored = _load_stored_draft(service, draft_id)
    new_to = stored.to if to is None else to
    new_cc = stored.cc if cc is None else cc
    new_subject = stored.subject if subject is None else subject
    new_body = stored.body if body is None else body
    if attachments is None:
        parts: list[Message] = stored.attachment_parts
        files: list[Path] | None = None
    else:
        parts = []
        files = attachments
    raw = build_draft_raw(
        to=new_to,
        subject=new_subject,
        body=new_body,
        cc=new_cc or None,
        attachments=files,
        attachment_parts=parts,
        in_reply_to=stored.in_reply_to,
        references=stored.references,
    )
    try:
        resp = (
            service.users()
            .drafts()
            .update(userId="me", id=draft_id, body=_message_body(raw, stored.thread_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure(f"update draft {draft_id}", exc)) from exc
    return _draft_ref(resp, to=new_to, cc=new_cc, subject=new_subject)
```

- [ ] **Step 4: Run the tests**

Run: `$PY -m pytest tests/test_drafts.py -v`
Expected: all pass.

- [ ] **Step 5: Lint and full suite**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_google/core/drafts.py tests/test_drafts.py
git commit -m "feat: update Gmail drafts in place

update_draft fetches the stored draft in raw form, merges only the
fields passed (cc=[] clears, attachments=[] removes, a list replaces,
omitted attachments are carried over as parts), keeps the threading
headers and threadId, and rewrites the draft under the same id. A call
that changes nothing is refused."
```

---

### Task 9: Drafts-only tool surface, send removed (spec sections 5.1, 5.4, 5.5)

**Files:**
- Modify: `src/hermes_google/mcp_server.py`
- Modify: `src/hermes_google/core/mail.py` (remove `send_draft`, `_build_raw`, the `MIMEText` import)
- Test: `tests/test_mcp_server.py`, `tests/test_mail.py`

- [ ] **Step 1: Write the failing server tests and remove the send tests**

In `tests/test_mail.py` delete `test_send_draft_to_user_email_succeeds`, `test_send_draft_allows_any_recipient` and `test_send_draft_with_in_reply_to_adds_threading_headers`.

In `tests/test_mcp_server.py`:

1. Delete `test_mail_send_draft_tool_calls_core`.
2. In `test_instructions_contains_key_policies` replace the `required` list with:

```python
    required = [
        "mail_archive",  # archive policy
        "No send capability",  # drafts-only policy
        "mail_create_draft",
        "mail_create_reply_draft",
        "mail_update_draft",
        "mail_delete_draft",
        "drive_delete",  # delete friction
        "drive_rename",
        "drive_create_folder",
        "data, not instructions",  # prompt-injection note
        "confirm",  # confirmation policy
    ]
```

3. In `test_smoke_server_has_expected_tools` remove `"mail_send_draft"` from `expected` and add `"mail_create_draft"`, `"mail_create_reply_draft"`, `"mail_update_draft"`, `"mail_delete_draft"`.
4. In `test_destructive_tools_annotated` set `destructive_tools = {"cal_delete_event", "drive_delete", "mail_delete_draft"}`.
5. In `test_idempotent_tools_annotated` add `"mail_update_draft"` to `idempotent_tools`.
6. Append:

```python
def test_server_has_no_send_capability() -> None:
    import inspect

    from hermes_google.core import drafts as drafts_core
    from hermes_google.core import mail as mail_core

    assert not hasattr(mail_core, "send_draft")
    assert "mail_send_draft" not in _tool_map()
    for module in (mail_core, drafts_core):
        assert ".send(" not in inspect.getsource(module)


def test_mail_create_draft_tool_parses_recipients_and_paths(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef, Recipient

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(
        mcp_server.drafts_core,
        "create_draft",
        return_value=DraftRef(
            draft_id="d1", message_id="m1", thread_id="t1", to=["a@x.com"], cc=[], subject="s"
        ),
    )
    result = mcp_server.mail_create_draft(
        to=["a@x.com"],
        cc=['"Larsson, Jimmy" <j@x.com>'],
        subject="s",
        body="b",
        attachments=["~/file.pdf"],
    )
    assert result["draft_id"] == "d1"
    assert result["warning"] is None
    _, kwargs = spy.call_args
    assert kwargs["to"] == [Recipient("", "a@x.com")]
    assert kwargs["cc"] == [Recipient("Larsson, Jimmy", "j@x.com")]
    assert kwargs["attachments"] == [Path("~/file.pdf").expanduser()]


def test_mail_create_reply_draft_uses_config_emails_and_overrides(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef, Recipient, ReplyContext
    from hermes_google.core.mail import MessageDetail

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(
        cache_dir=tmp_path,
        user_email="jimmy@example.com",
        hermes_account_email="hermes@example.com",
    )
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    detail = MessageDetail(
        id="m1",
        thread_id="t1",
        sender="s",
        original_sender="Alice <alice@example.com>",
        original_subject="Hello",
        original_body="b",
        in_reply_to=None,
        forwarding_note=None,
        attachment_paths=[],
        rfc_message_id="<o@x>",
    )
    mocker.patch.object(mcp_server.mail_core, "get_message", return_value=detail)
    ctx = ReplyContext(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com"), Recipient("", "carol@example.com")],
        subject="Re: Hello",
        in_reply_to="<o@x>",
        references="<o@x>",
        thread_id="t1",
        warning="ignored unusable addresses: x",
    )
    ctx_spy = mocker.patch.object(mcp_server.drafts_core, "reply_context", return_value=ctx)
    create_spy = mocker.patch.object(
        mcp_server.drafts_core,
        "create_draft",
        return_value=DraftRef(
            draft_id="d1",
            message_id="m2",
            thread_id="t1",
            to=["carol@example.com"],
            cc=["bob@example.com"],
            subject="Re: Hello",
        ),
    )

    result = mcp_server.mail_create_reply_draft(message_id="m1", body="Hi", to=["carol@example.com"])

    args, ctx_kwargs = ctx_spy.call_args
    assert args == (detail,)
    assert ctx_kwargs == {"user_email": "jimmy@example.com", "hermes_email": "hermes@example.com"}
    _, kwargs = create_spy.call_args
    assert kwargs["to"] == [Recipient("", "carol@example.com")]
    assert kwargs["cc"] == [Recipient("", "bob@example.com")]
    assert kwargs["subject"] == "Re: Hello"
    assert kwargs["in_reply_to"] == "<o@x>"
    assert kwargs["references"] == "<o@x>"
    assert kwargs["thread_id"] == "t1"
    assert result["draft_id"] == "d1"
    assert result["warning"] == "ignored unusable addresses: x"


def test_mail_create_reply_draft_defaults_to_context_recipients(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef, Recipient, ReplyContext
    from hermes_google.core.mail import MessageDetail

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(cache_dir=tmp_path, user_email="u@x.com", hermes_account_email="h@x.com")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    detail = MessageDetail(
        id="m1",
        thread_id="t1",
        sender="s",
        original_sender="Alice <alice@example.com>",
        original_subject="Hello",
        original_body="b",
        in_reply_to=None,
        forwarding_note=None,
        attachment_paths=[],
    )
    mocker.patch.object(mcp_server.mail_core, "get_message", return_value=detail)
    ctx = ReplyContext(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com")],
        subject="Re: Hello",
        in_reply_to=None,
        references=None,
        thread_id=None,
        warning=None,
    )
    mocker.patch.object(mcp_server.drafts_core, "reply_context", return_value=ctx)
    create_spy = mocker.patch.object(
        mcp_server.drafts_core,
        "create_draft",
        return_value=DraftRef(
            draft_id="d1", message_id="m2", thread_id="t9", to=[], cc=[], subject="Re: Hello"
        ),
    )

    mcp_server.mail_create_reply_draft(message_id="m1", body="Hi")

    _, kwargs = create_spy.call_args
    assert kwargs["to"] == ctx.to
    assert kwargs["cc"] == ctx.cc
    assert kwargs["thread_id"] is None


def test_mail_update_draft_tool_passes_only_given_fields(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(
        mcp_server.drafts_core,
        "update_draft",
        return_value=DraftRef(
            draft_id="d1", message_id="m1", thread_id="t1", to=["a@x.com"], cc=[], subject="s"
        ),
    )
    result = mcp_server.mail_update_draft(draft_id="d1", body="new", cc=[])
    assert result["draft_id"] == "d1"
    _, kwargs = spy.call_args
    assert kwargs["draft_id"] == "d1"
    assert kwargs["body"] == "new"
    assert kwargs["cc"] == []
    assert kwargs["to"] is None
    assert kwargs["subject"] is None
    assert kwargs["attachments"] is None


def test_mail_delete_draft_tool_returns_id(mocker) -> None:
    from hermes_google import mcp_server

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(mcp_server.drafts_core, "delete_draft")
    assert mcp_server.mail_delete_draft(draft_id="d1") == {"draft_id": "d1"}
    _, kwargs = spy.call_args
    assert kwargs == {"draft_id": "d1"}


def test_mail_create_draft_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.mail import MailError

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    mocker.patch.object(
        mcp_server.drafts_core, "create_draft", side_effect=MailError("create draft failed")
    )
    with pytest.raises(ToolError, match="create draft failed"):
        mcp_server.mail_create_draft(to=["a@x.com"], subject="s", body="b")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_mcp_server.py tests/test_mail.py -v`
Expected: the inventory, instructions, annotation and new tool tests FAIL (`mcp_server` has no `drafts_core`, no draft tools); `test_mail.py` passes.

- [ ] **Step 3: Remove the send path from mail.py**

In `src/hermes_google/core/mail.py`: delete `_build_raw` and `send_draft` entirely, and delete the line `from email.mime.text import MIMEText`.

- [ ] **Step 4: Rewrite the instructions and add the tools**

In `src/hermes_google/mcp_server.py`:

1. Module docstring: replace `- Enforce the destination-email invariant on \`mail_send_draft\`.` with `- Never send mail: every Gmail write is a draft in the Hermes mailbox.`
2. Imports: add `from hermes_google.core import drafts as drafts_core` after the `drive` import, and change `from dataclasses import asdict` to `from dataclasses import asdict, replace`.
3. Replace policies 1, 2 and 4 in `INSTRUCTIONS`:

```
1. Archive policy — never call `mail_archive` without explicit user confirmation.
   Ask after creating a draft ("want me to archive my copy?") AND when the user
   mentions they've sent the reply. No silent auto-archive.

2. No send capability — this server creates drafts in the Hermes account's
   Gmail only (`mail_create_draft`, `mail_create_reply_draft`); the user
   reviews and sends them from Gmail. Present the draft content in chat before
   creating it. Revise an existing draft with `mail_update_draft` rather than
   deleting and recreating it. Call `mail_delete_draft` only when replacing a
   draft the user has reviewed or when the user explicitly asks to discard one.
```

```
4. Confirmation — all write operations (`mail_create_draft`,
   `mail_create_reply_draft`, `mail_update_draft`, `mail_delete_draft`,
   `cal_create_event`, `cal_update_event`, `cal_delete_event`, `drive_upload`,
   `drive_update`, `drive_move`, `drive_rename`, `drive_create_folder`,
   `drive_delete`) require the user to confirm the proposed action in chat
   before you invoke the tool.
```

4. Delete the `mail_send_draft` tool and in its place add:

```python
def _paths(attachments: list[str] | None) -> list[Path] | None:
    if attachments is None:
        return None
    return [Path(p).expanduser() for p in attachments]


@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
@_auto_retry
def mail_create_draft(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new draft in the Hermes account's Gmail. Does NOT send: the user
    reviews and sends it from Gmail. Requires user confirmation before calling.

    Recipients are `addr` or `Name <addr>` strings with ASCII addresses; quote
    a display name that contains a comma. `attachments` are local file paths.

    Returns dict with keys: `draft_id`, `message_id`, `thread_id`, `to`, `cc`,
    `subject`, `warning`.
    """
    services = _get_services()
    ref = drafts_core.create_draft(
        services.gmail,
        to=drafts_core.parse_recipients(to),
        cc=drafts_core.parse_recipients(cc) if cc else None,
        subject=subject,
        body=body,
        attachments=_paths(attachments),
    )
    return asdict(ref)


@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
@_auto_retry
def mail_create_reply_draft(
    message_id: str,
    body: str,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Create a reply-all draft to a message in Hermes's inbox, threaded under
    the original conversation. Does NOT send. Requires user confirmation before
    calling.

    `message_id` is the Gmail id from `mail_list_pending` or `mail_get`. By
    default To is the original Reply-To or sender plus the original To
    recipients, and Cc keeps the original Cc; the Hermes address and the
    user's own address are dropped. Pass `to` and/or `cc` to override.
    Unusable header addresses are skipped and listed in `warning`.

    Returns dict with keys: `draft_id`, `message_id`, `thread_id`, `to`, `cc`,
    `subject`, `warning`.
    """
    services = _get_services()
    cfg = _get_config()
    detail = mail_core.get_message(services.gmail, message_id=message_id, cache_dir=cfg.cache_dir)
    ctx = drafts_core.reply_context(
        detail, user_email=cfg.user_email, hermes_email=cfg.hermes_account_email
    )
    reply_to = ctx.to if to is None else drafts_core.parse_recipients(to)
    if cc is None:
        chosen = {r.addr.lower() for r in reply_to}
        reply_cc = [r for r in ctx.cc if r.addr.lower() not in chosen]
    else:
        reply_cc = drafts_core.parse_recipients(cc)
    ref = drafts_core.create_draft(
        services.gmail,
        to=reply_to,
        cc=reply_cc or None,
        subject=ctx.subject,
        body=body,
        attachments=_paths(attachments),
        in_reply_to=ctx.in_reply_to,
        references=ctx.references,
        thread_id=ctx.thread_id,
    )
    return asdict(replace(ref, warning=ctx.warning))


@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
@_auto_retry
def mail_update_draft(
    draft_id: str,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    subject: str | None = None,
    body: str | None = None,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Revise a draft in place. Does NOT send. Requires user confirmation before calling.

    Pass only the fields to change; omitted fields keep their stored values.
    `cc=[]` clears Cc, `attachments=[]` removes all attachments, a list of
    paths replaces them, and omitting `attachments` keeps the stored ones.
    The draft keeps its `draft_id`.

    Returns dict with keys: `draft_id`, `message_id`, `thread_id`, `to`, `cc`,
    `subject`, `warning`.
    """
    services = _get_services()
    ref = drafts_core.update_draft(
        services.gmail,
        draft_id=draft_id,
        to=None if to is None else drafts_core.parse_recipients(to),
        cc=None if cc is None else drafts_core.parse_recipients(cc),
        subject=subject,
        body=body,
        attachments=_paths(attachments),
    )
    return asdict(ref)


@mcp.tool(annotations={"destructiveHint": True, "openWorldHint": False})
@_auto_retry
def mail_delete_draft(draft_id: str) -> dict[str, Any]:
    """Delete a draft from the Hermes account's Gmail.

    Only call when replacing a draft the user has reviewed, or when the user
    explicitly asks to discard one.

    Returns dict with key: `draft_id`.
    """
    services = _get_services()
    drafts_core.delete_draft(services.gmail, draft_id=draft_id)
    return {"draft_id": draft_id}
```

- [ ] **Step 5: Run the full suite and lint**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass. If ruff flags an unused import in `mail.py` after the removal, delete it.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_google/mcp_server.py src/hermes_google/core/mail.py tests/test_mcp_server.py tests/test_mail.py
git commit -m "feat!: Gmail becomes drafts-only; mail_send_draft removed

The server no longer sends mail. mail_create_draft, mail_create_reply_draft,
mail_update_draft and mail_delete_draft write drafts into the Hermes
account's Gmail for the user to review and send, mirroring hermes-imap.
The reply tool derives reply-all recipients and threading from the
original message and lets explicit to/cc override them. The server
instructions describe the no-send posture and the new confirm-first list."
```

---

### Task 10: README and docs (spec section 7)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Apply the README changes**

1. Lines 7-8, replace with:

```markdown
See [`docs/superpowers/specs/2026-04-23-hermes-google-design.md`](docs/superpowers/specs/2026-04-23-hermes-google-design.md)
for the original design and
[`docs/superpowers/specs/2026-11-09-drive-tools-and-gmail-drafts-design.md`](docs/superpowers/specs/2026-11-09-drive-tools-and-gmail-drafts-design.md)
for the 0.4.0 changes (full Drive scope, drafts-only Gmail).
```

2. After the setup-script paragraph (line 43) and before `### Host-Side OAuth`, insert:

```markdown
### Scopes

The OAuth consent asks for exactly these scopes:

| Scope | Used for |
|---|---|
| `gmail.modify` | read the forwarded-mail inbox, mark read, archive, create and edit drafts |
| `calendar.events` | create, update and delete events on calendars shared with Hermes |
| `calendar.readonly` | list calendars and events |
| `drive` | read, upload, update, move, rename, create folders and delete files shared with Hermes |

Hermes never sends mail: the server has no send tool, and `gmail.modify` is
needed for drafts anyway (every Gmail scope that allows drafts also allows
sending, so the guarantee is in the code, not the scope). The full `drive`
scope is needed to rename files you uploaded yourself; Hermes still only
reaches what you share with its account.

### Upgrading from 0.3.x

0.4.0 changes the scope set. Re-run the consent flow once:

```bash
hermes-google auth login --headless
```

Until you do, every tool returns `stored token lacks scopes: ...; run
'hermes-google auth login' to re-consent`.
```

3. In `### Host-Side OAuth`, replace the first paragraph with:

```markdown
The default OAuth flow opens a browser for consent, so it must run on your
host machine. Inside a headless container use `hermes-google auth login
--headless`: it prints a URL to open in any browser and asks you to paste the
redirect URL back.
```

4. In `## Gmail Setup`, replace the numbered list (lines 66-70) with:

```markdown
1. For each sender you want Hermes to handle: create a filter that **both**
   labels the email (e.g. `hermes-review`) **and** forwards it to
   `hermes-yourname@gmail.com` — in a single filter
2. Forwarding a message to the Hermes account by hand works too

Hermes never sends mail. Reply drafts are written to the **Hermes account's
Drafts folder**: open that account in Gmail (or add it to your mail app) to
review and send. A draft sent from there goes out as the Hermes address
unless you add your own address as a "Send mail as" alias in the Hermes
account's Gmail settings.
```

5. In `## Calendar & Drive Setup`, replace the Drive bullet with:

```markdown
- **Drive:** Share the folders you want Hermes to work in with the Hermes
  account (editor access to rename or move your own files). Set
  `[drive].default_parent_folder_id` in `config.toml` to the shared folder so
  uploads and new folders land where you can see them; without it they go to
  the Hermes account's own My Drive root.
```

6. In `## Usage`, replace the tool list and the paragraph after it (lines 94-104) with:

```markdown
- `mail_list_pending`, `mail_search`, `mail_get`, `mail_create_draft`,
  `mail_create_reply_draft`, `mail_update_draft`, `mail_delete_draft`,
  `mail_mark_read`, `mail_archive`
- `cal_list_calendars`, `cal_list_events`, `cal_create_event`,
  `cal_update_event`, `cal_delete_event`
- `drive_search`, `drive_list`, `drive_get`, `drive_upload`, `drive_update`,
  `drive_move`, `drive_rename`, `drive_create_folder`, `drive_delete`
- `auth_status`

All write operations require user confirmation. The server has no send
capability: Gmail writes are drafts in the Hermes mailbox, and you send them.
```

- [ ] **Step 2: Check the rendered text for leftovers**

Run: `grep -n 'mail_send_draft\|gmail.send\|drive.file\|drive.readonly\|hermes-review\|apply label' README.md`
Expected: only the `hermes-review` label line from the forwarding filter instructions.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README for 0.4.0 scopes, drafts-only Gmail and Drive tools

Lists the four scopes and why gmail.modify and drive are needed,
documents the 0.3.x upgrade re-consent, replaces the return-path filter
with the Drafts-folder flow, recommends the default parent folder, and
updates the tool list."
```

---

### Task 11: Upload and update explain a missing local file (Mimir #1112)

**Files:**
- Modify: `src/hermes_google/core/drive.py` (`upload_file`, `update_file`)
- Test: `tests/test_drive.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_drive.py`:

```python
def test_upload_file_missing_local_file_raises_drive_error(
    tmp_path: Path, mock_drive_service: MagicMock
) -> None:
    with pytest.raises(DriveError, match="upload failed: FileNotFoundError"):
        upload_file(mock_drive_service, local_path=tmp_path / "missing.md", name="missing.md")
    mock_drive_service.files().create.assert_not_called()


def test_update_file_missing_local_file_raises_drive_error(
    tmp_path: Path, mock_drive_service: MagicMock
) -> None:
    with pytest.raises(DriveError, match="update failed: FileNotFoundError"):
        update_file(mock_drive_service, file_id="f1", local_path=tmp_path / "missing.md")
    mock_drive_service.files().update.assert_not_called()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_drive.py -k missing_local_file -v`
Expected: both FAIL with `FileNotFoundError` escaping instead of `DriveError` (pytest reports the raw `FileNotFoundError`).

- [ ] **Step 3: Build the upload media inside the try blocks**

In `src/hermes_google/core/drive.py` replace the bodies of `upload_file` and `update_file`:

```python
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
```

- [ ] **Step 4: Run the drive tests**

Run: `$PY -m pytest tests/test_drive.py -v`
Expected: all pass (the existing upload and update tests patch `MediaFileUpload` on the module, which still works inside the try).

- [ ] **Step 5: Run the full suite and lint**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format src tests`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_google/core/drive.py tests/test_drive.py
git commit -m "fix: upload and update explain a missing local file

MediaFileUpload opened the file before the try, so a wrong local_path
raised FileNotFoundError, which is not a ServiceError and reached Hermes
as a masked error. Building it inside the try routes it through
api_failure like every other Drive failure."
```

---

### Task 12: Version bump

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Bump**

In `pyproject.toml` change `version = "0.3.0"` to `version = "0.4.0"`.

- [ ] **Step 2: Final verification**

Run: `$PY -m pytest -q && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff check src tests && /home/hermes_jimmy/miniconda3/envs/hermes-google/bin/ruff format --check src tests && grep -rn 'send_draft\|gmail.send\|drive.file\|drive.readonly' src tests README.md`
Expected: tests pass, ruff clean, the grep prints only `tests/test_auth.py` (the superset test mentions `drive.file` on purpose) and `tests/test_mcp_server.py` (the no-send test mentions `send_draft` on purpose).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.4.0"
```

---

## After the plan

Not part of the implementation tasks; handled with Jimmy step by step (spec section 8): push the branch and open the PR, merge, tag `0.4.0`, add the `[drive]` section to the live config, re-consent with `hermes-google auth login --headless`, reconnect the MCP server, live check, then update Mimir (#1103, #1106, #950 done; #355 dropped; fact #354 archived; new facts on #231).
