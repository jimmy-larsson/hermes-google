# hermes-google 0.4.0: Drive rename and create-folder, Gmail drafts-only

**Date:** 2026-11-09
**Version:** 0.4.0
**Mimir:** task #1103 (Drive rename and create-folder tools), task #1106 (Gmail drafts-only), task #950 (reply threading headers)
**Supersedes:** section 8.2 (Drive scope) and the Gmail send flow (section 6.1, section 9) of `2026-04-23-hermes-google-design.md`

## 1. Summary

Three changes shipped in one release so the Hermes Google account re-consents once:

1. **Drive:** new `drive_rename` and `drive_create_folder` tools. Renaming files Jimmy uploaded himself needs the full Drive scope, so the scope set changes.
2. **Gmail:** Hermes stops sending mail. `mail_send_draft` is removed. `mail_create_draft`, `mail_create_reply_draft`, `mail_update_draft` and `mail_delete_draft` write drafts into the Hermes account's own Gmail, mirroring hermes-imap. The user reviews and sends from Gmail.
3. **Errors:** Drive and Gmail failures carry the Google HTTP status and reason instead of a bare "x failed".

Decisions taken by Jimmy on 2026-11-09: full `drive` scope with no folder-tree guard; the shared Hermes folder becomes the configured default parent while upload keeps its silent fall-through to the account root when nothing is configured; IMAP-parity drafts (create, reply, update, delete) with reply-all recipients in hermes-imap's shape; one release and one PR.

## 2. Scopes and token check (`core/auth.py`)

`SCOPES` becomes exactly:

- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/calendar.readonly`
- `https://www.googleapis.com/auth/drive`

Removed: `gmail.send` (redundant under `gmail.modify`, and the server no longer sends), `drive.readonly` and `drive.file` (both subsumed by `drive`).

**Why `drive`.** `drive.file` only reaches files the app created. Jimmy's own uploads into the shared Hermes folder cannot be renamed under it. `drive` is the practical scope for it (`drive.metadata` would also allow the rename and is equally restricted). The same change makes `drive_update`, `drive_move` and `drive_delete` work on Jimmy's own files, which fail under `drive.file` for the same reason. No folder-tree guard is added: chat confirmation gates every write, and the dedicated account only sees what Jimmy shares with it.

**Why there is no drafts-without-send scope.** `users.drafts.create` is authorised by `https://mail.google.com/`, `gmail.modify` and `gmail.compose`, and each of those also authorises `users.messages.send` (checked against the Gmail API reference on 2026-11-09). `gmail.modify` must stay for mark-read and archive. The no-send guarantee is therefore structural in code: no tool calls `messages.send` or `drafts.send`, the same way hermes-imap has no SMTP.

**Stored-scope check.** A new helper `stored_scopes(path) -> list[str]` returns the token file's `scopes` list (empty when the key is absent). `load_credentials` calls it before building credentials. If any entry of `SCOPES` is missing it raises `AuthError` with the message "stored token lacks scopes: <missing, comma separated>; run 'hermes-google auth login' to re-consent". A token that holds extra scopes passes. A token file without a `scopes` key counts as lacking all of them. Rationale: google-auth 2.49 only logs a warning when a refresh returns fewer scopes than requested, so without this check the first rename after upgrading would fail with an opaque 403. `_auto_retry` already converts `AuthError` into a `ToolError`, so the message reaches Hermes unchanged. `auth_status` changes in two ways: it reports `stored_scopes` instead of the requested list that `creds.scopes` always echoes, and on `AuthError` it puts the exception text in `error` instead of a fixed string, so the missing-scope message is visible through it as well; its tests adjust accordingly.

## 3. API error reasons (`core/errors.py`, `core/drive.py`, `core/mail.py`, `core/drafts.py`)

New helper in `errors.py`:

```python
def api_failure(action: str, exc: BaseException) -> str
```

- `googleapiclient.errors.HttpError`: `"<action> failed: HTTP <status_code> <reason>"`.
- anything else: `"<action> failed: <ExceptionType>: <exc>"`.

Every `raise DriveError("x failed") from exc` and `raise MailError("x failed") from exc` becomes `raise DriveError(api_failure("x", exc)) from exc`. `upload_file` and `update_file` build their `MediaFileUpload` inside the `try`, so a missing local file is reported as `upload failed: FileNotFoundError: ...` instead of escaping as a masked error (Mimir task #1112, added to the release by Jimmy on 2026-11-09). Existing messages are reworded to the `<action> failed: ...` form, keeping their context inside the action (for example `fetch message <id> failed: HTTP 404 Requested entity was not found.`). FastMCP's `mask_error_details` masks unexpected exceptions only; `ToolError` messages produced by `_auto_retry` pass through, so Hermes sees the reason.

## 4. Drive

### 4.1 Name validation (`core/drive.py`)

`_is_unsafe_name(name: str) -> bool` is true for an empty name, `"."`, `".."`, and any name containing a forward slash or a backslash. `get_file` uses it in place of its inline checks on downloaded names, without stripping, so its behaviour and its `unsafe filename` error message do not change. `_validate_name(name: str) -> str` is for user input: it strips surrounding whitespace, applies the predicate to the result, and raises `DriveError("invalid name: <repr>")`, so whitespace-only names are rejected too.

### 4.2 Core functions (`core/drive.py`)

- `rename_file(service, *, file_id: str, new_name: str) -> FileRef`: validates the name, then `files().update(fileId=file_id, body={"name": name}, fields="id,name,mimeType")`. Works on files and folders alike. Returns the stored id, name and MIME type.
- `create_folder(service, *, name: str, parent_folder_id: str | None = None) -> FileRef`: validates the name, then `files().create(body=..., fields="id,name,mimeType")` with `mimeType = "application/vnd.google-apps.folder"` and `parents = [parent_folder_id]` only when a parent is given. Returns the stored id, name and MIME type. A response without `id` raises `DriveError("unexpected create response format")`.

### 4.3 Tools (`mcp_server.py`)

- `drive_rename(file_id: str, new_name: str) -> {"id", "name", "mime_type"}`. Annotations: `destructiveHint` False, `idempotentHint` True, `openWorldHint` False. Requires user confirmation before calling.
- `drive_create_folder(name: str, parent_folder_id: str | None = None) -> {"id", "name", "mime_type", "parent_folder_id"}`. The parent resolves as `parent_folder_id or cfg.drive_default_parent_folder_id`, exactly like `drive_upload`; `None` means the Hermes account's My Drive root and is kept deliberately. Annotations: `destructiveHint` False, `idempotentHint` False, `openWorldHint` False. The docstring states that Drive allows several folders with the same name in one parent, so Hermes lists the parent first. Requires user confirmation before calling.

### 4.4 Live configuration (rollout, not code)

`~/.config/hermes-google/config.toml` gains:

```toml
[drive]
default_parent_folder_id = "1dEDn33-BN6DlF_sUnjQt-FmZZb-mAlaD"
```

That is the shared "Hermes" folder Jimmy can see. The README recommends the setting; the code path already exists.

## 5. Gmail drafts-only

### 5.1 Removed

The `mail_send_draft` tool, `send_draft` and `_build_raw` in `core/mail.py`, their tests, the README's return-path description, and the README instruction to create a "replies from Hermes" label filter. Mimir task #355 (make the send tool's `to` optional) is dropped as moot.

### 5.2 Header parsing (`core/forward.py`), fixes #950

`OriginalMessage` gains `message_id`, `references`, `to`, `cc` and `reply_to`, all `str | None`. `in_reply_to`, `message_id` and `references` are whitespace-normalised with `" ".join(value.split())`, which preserves multi-id values such as a two-id In-Reply-To.

- **No forward delimiter found.** Mail addressed to Hermes directly, or delivered by a Gmail forwarding filter (believed to keep the original headers intact; no such message was available to check on 2026-11-09, and the rule does not depend on it). All five fields and `in_reply_to` come straight from the message headers; `message_id` is the message's own Message-ID.
- **Manual forward (a delimiter is found).** `to`, `cc` and `reply_to` come from the inner header block (`_KEEP_HEADERS` gains `cc` and `reply-to`). `message_id` is `None`: the forwarded message's id is not in the block. `in_reply_to` and `references` are the wrapper's own headers, which Gmail, Outlook and Titan set to the forwarded message's Message-ID and its thread chain; all six manual forwards in the Hermes inbox on 2026-11-09 carried both. They are what lets a reply draft thread in the external recipient's mailbox.

`MessageDetail` exposes the new fields as `rfc_message_id`, `references`, `original_to`, `original_cc` and `original_reply_to`, appended with default `None` so existing positional construction keeps working; `mail_get` returns them. The Gmail id stays in `id`.

### 5.3 Draft building (`core/drafts.py`, new module)

```python
def build_draft_raw(*, to, subject, body, cc=None, attachments=None,
                    attachment_parts=None, in_reply_to=None, references=None) -> str
```

Returns the base64url-encoded RFC 822 message Gmail expects in `message.raw`. All draft code lives in the new `core/drafts.py`, mirroring hermes-imap; `core/mail.py` keeps reading, labels and `MessageDetail`.

- `EmailMessage` with To, optional Cc, Subject, plain-text utf-8 body. No From header: Gmail fills in the account's address. In-Reply-To and References are set when given.
- **Recipients** are strings of the form `addr` or `Name <addr>`. They are parsed with the `email.headerregistry` address parser (`email.policy.default.header_factory("To", value).addresses`), which respects quoting and decodes encoded words, so `"Larsson, Jimmy" <j@x.com>` is one recipient. Each address part must be ASCII and match `[^\s@]+@[^\s@]+` (the hermes-imap rule); otherwise `MailError("invalid recipient: <repr>")`. Display names may be non-ASCII. At least one To recipient is required. The subject must be a single line.
- `attachments` are local `Path`s. A missing file raises `MailError("attachment not found: <path>")`. The MIME type comes from `mimetypes.guess_type`, defaulting to `application/octet-stream`. `attachment_parts` are MIME parts carried over from a stored draft on update.

`DraftRef` (frozen dataclass): `draft_id`, `message_id` (Gmail id of the draft's message), `thread_id`, `to: list[str]`, `cc: list[str]`, `subject`, `warning: str | None`. It is the return type of every draft write. Recipient strings in `to` and `cc` are rendered with `str(email.headerregistry.Address(display_name=..., addr_spec=...))`, which quotes a name containing a comma and keeps a non-ASCII name readable, so they survive a round trip through the parser above.

- `create_draft(service, *, to, subject, body, cc=None, attachments=None, in_reply_to=None, references=None, thread_id=None) -> DraftRef`: `users().drafts().create(userId="me", body={"message": {"raw": raw, "threadId": thread_id}})`, `threadId` omitted when `None`. The response is a Draft resource `{"id", "message": {"id", "threadId", ...}}`: `draft_id` is `resp["id"]`, `message_id` and `thread_id` come from `resp["message"]`. Test fixtures use this nested shape.
- `reply_context(detail: MessageDetail, *, user_email: str, hermes_email: str) -> ReplyContext`: a pure function returning `to`, `cc`, `subject`, `in_reply_to`, `references`, `thread_id` and `warning`.
  - **Recipients (reply-all, as decided).** Header values are parsed with the same address parser. To starts with the addresses of `original_reply_to` when present, otherwise `original_sender`, followed by those of `original_to`. Cc is `original_cc`. Both lists drop `user_email` and `hermes_email` (case-insensitive comparison of the address part) and drop duplicates, and Cc drops anything already in To. A header entry whose address part is missing, non-ASCII or fails the address rule is dropped and named in `warning`; it never fails the call. If To is empty after filtering, To falls back to the single unfiltered reply-to-or-sender address, so a note Jimmy mails to Hermes directly comes back to him. If even that address is unusable, `MailError("no usable reply recipient; pass to explicitly")`.
  - **Subject.** `original_subject` prefixed with `"Re: "` unless it already starts with `re:` (case-insensitive).
  - **Threading**, decided by whether `rfc_message_id` is set.
    - Intact headers (`rfc_message_id` set): `in_reply_to = rfc_message_id`; `references` is the original's References, or its In-Reply-To when it has no References, followed by `rfc_message_id`; `thread_id` is the Gmail thread id, so the draft sits in the same conversation in the Hermes mailbox. Gmail requires `threadId`, RFC-compliant In-Reply-To and References, and a matching Subject for a draft to join a thread; this satisfies all three.
    - Manual forward (`rfc_message_id` is `None`): `in_reply_to` is the wrapper's In-Reply-To and `references` is the wrapper's References, or its In-Reply-To when it has none. The wrapper's own Message-ID is never added, because the external recipient never saw the wrapper. `thread_id` is `None`: the draft starts its own conversation in the Hermes mailbox, since whether Gmail accepts a `threadId` together with ids foreign to the mailbox is unverified. When the wrapper has no In-Reply-To either, no threading headers are set.
- `update_draft(service, *, draft_id, to=None, cc=None, subject=None, body=None, attachments=None) -> DraftRef`: when every field is `None`, `MailError("nothing to update")`. Otherwise it fetches the stored draft with `drafts().get(userId="me", id=draft_id, format="raw")`, reads `raw` and `threadId` from `resp["message"]`, parses To, Cc, Subject, the `text/plain` body, In-Reply-To and References, and takes the stored attachments as `EmailMessage.iter_attachments()`. Merge: a `None` field keeps the stored value; `cc=[]` clears Cc; `attachments=[]` removes all attachments; a non-empty list replaces them; `attachments=None` carries the stored parts over. In-Reply-To, References and `threadId` are always carried over. Then `drafts().update(userId="me", id=draft_id, body={"message": {"raw": raw, "threadId": thread_id}})`, `threadId` omitted when `None`. The draft id is unchanged.
- `delete_draft(service, *, draft_id) -> None`: `drafts().delete(userId="me", id=draft_id)`.

### 5.4 Tools (`mcp_server.py`)

- `mail_create_draft(to: list[str], subject: str, body: str, cc: list[str] | None = None, attachments: list[str] | None = None)` returns the `DraftRef` as a dict. Annotations: `destructiveHint` False, `idempotentHint` False.
- `mail_create_reply_draft(message_id: str, body: str, to: list[str] | None = None, cc: list[str] | None = None, attachments: list[str] | None = None)`: `message_id` is the Gmail id from `mail_list_pending` or `mail_get`. Fetches the message with `get_message`, computes `reply_context` with `cfg.user_email` and `cfg.hermes_account_email`, replaces To and Cc with the explicit arguments when given (an explicit `to` with no `cc` keeps the computed Cc, filtered against the final To list), creates the draft. Same annotations as create.
- `mail_update_draft(draft_id: str, to=None, cc=None, subject=None, body=None, attachments=None)` returns the `DraftRef` dict. Annotations: `destructiveHint` False, `idempotentHint` True.
- `mail_delete_draft(draft_id: str)` returns `{"draft_id"}`. Annotations: `destructiveHint` True.
- `attachments` are local file paths, absolute or `~`-prefixed (expanded with `expanduser`). Any file the server process can read can be attached, the same surface hermes-imap has; chat confirmation is the gate. All four require user confirmation, and the draft content is presented in chat before creation.

### 5.5 Server instructions

Policy 2 becomes: "No send capability: this server creates drafts in the Hermes account's Gmail only; the user reviews and sends from Gmail. Present the draft content in chat before creating it. Revise an existing draft with `mail_update_draft` rather than deleting and recreating it. Call `mail_delete_draft` only when replacing a draft the user has reviewed or when the user explicitly asks to discard one." Policy 4's confirm-first list adds the four draft tools, `drive_rename` and `drive_create_folder`. Policy 1's "after delivering a draft" becomes "after creating a draft".

Other text that still refers to sending is updated in the same commit: the `mail_get` docstring sentence telling Hermes to use `sender` as the `to` for replies, the `mcp_server.py` module docstring, and the README's pointer to the design spec, which links this one next to the original.

### 5.6 Known limitation

A draft sent from the Hermes mailbox goes out as the Hermes address. Jimmy may configure his own address as a "Send mail as" alias in that account; the server does not set From.

## 6. Tests

All against `MagicMock` services, following the existing fixtures.

- `test_auth.py`: `SCOPES` is exactly the four scopes; `stored_scopes` returns the file's list and `[]` without the key; `load_credentials` raises `AuthError` naming the missing scope when the token file lacks `drive`; a token with a superset of scopes loads; a token file without a `scopes` key is rejected.
- `test_drive.py`: `rename_file` sends the name body and `fields`, returns a `FileRef`; `rename_file` rejects `""`, `"   "`, `".."`, `"a/b"` and `"a\\b"`; `create_folder` sends the folder MIME type and parents, omits parents when `None`, returns a `FileRef`, and rejects a response without `id`; `get_file` still rejects a traversal name; an `HttpError` with status 403 yields a message containing `403` and the reason, and a plain exception yields its type and text.
- `test_forward.py`: a non-forwarded message exposes normalised `message_id`, `references`, `to`, `cc`, `reply_to`; a two-id In-Reply-To survives normalisation (pins #950); a manual forward yields `None` for `message_id`, takes `in_reply_to` and `references` from the wrapper headers, and takes `to`, `cc`, `reply_to` from the inner block.
- `test_mail.py`: `build_draft_raw` sets To, Cc, Subject, In-Reply-To, References and omits From; accepts `"Larsson, Jimmy" <j@x.com>` as one recipient and a non-ASCII display name; rejects an invalid recipient, an empty To list, a multi-line subject and a missing attachment; includes an attachment part with the right filename. `reply_context` drops the user and Hermes addresses, honours Reply-To, prefixes `Re: ` once, threads with `threadId` when `rfc_message_id` is set, uses the wrapper's In-Reply-To and References without `threadId` for a manual forward, sets nothing when the wrapper has neither, drops a bad header entry into `warning`, falls back to the sender when every recipient was filtered out, and renders a comma name quoted so it round-trips through `build_draft_raw`. `create_draft` passes `threadId` and `raw` and reads the nested Draft response; `update_draft` raises on all-`None`, keeps omitted fields, clears Cc with `[]`, replaces, drops and carries attachments, and carries `threadId` and the threading headers; `delete_draft` calls `drafts().delete`.
- `test_mcp_server.py`: the tool inventory (no `mail_send_draft`; the six new tools present); `mail_core` has no `send_draft` and `core/mail.py` contains no `.send(` call (the structural no-send guarantee); `drive_rename` and `mail_update_draft` are idempotent; `mail_delete_draft` is destructive; the instructions mention drafts-only and name the new tools; `drive_create_folder` uses the configured default parent; `mail_create_reply_draft` passes the config emails and applies explicit overrides; `auth_status` reports the stored scopes and surfaces the `AuthError` text; the existing positional `MessageDetail` construction still passes.

## 7. Documentation

README:

- Setup: list the four scopes and say what each is for.
- Gmail setup: keep the forwarding filter; remove the "replies from Hermes" label step; explain that Hermes writes reply drafts into the Hermes account's Drafts folder, where the user reviews and sends; mention the optional send-as alias.
- Calendar and Drive setup: recommend `[drive].default_parent_folder_id`.
- Tool list: updated.
- Upgrading from 0.3.x: run `hermes-google auth login --headless` to re-consent; the server refuses the old token with a message naming the missing scopes.
- Revocation: drop the line about deleting the Hermes label filter.

The server `INSTRUCTIONS` string is updated per 5.5. The MCP tool docstrings are the primary tool documentation.

## 8. Release and rollout

Branch `feat/drive-tools-gmail-drafts`, one PR to `main`, one commit per change: ignore rule for worktrees, this spec, scopes and token check, API error reasons, Drive name validation and rename, create-folder, forward header parsing, Gmail drafts replacing send, README, the missing-local-file fix for upload and update, version bump to 0.4.0.

Rollout, each step confirmed with Jimmy:

1. Merge the PR and tag `0.4.0`. `release.yml` publishes `hermes-google-mcp` to PyPI and the image to GHCR.
2. Add the `[drive]` section to the live `config.toml` (section 4.4).
3. Re-consent: run `hermes-google auth login --headless` from the `main` checkout in the `hermes-google` conda env, so it requests the new `SCOPES`. The flow uses PKCE and must be one process: Hermes starts it with a FIFO on stdin, relays the Google URL, Jimmy authorises as the Hermes account in his browser and pastes the redirect URL back, Hermes writes it to the FIFO. The token file is shared with the MCP server.
4. Reconnect `hermes-google` in `/mcp`. The launcher runs `uvx hermes-google-mcp@latest`, so the respawn resolves 0.4.0. The running 0.3.0 process may fail between the re-consent and the reconnect; Jimmy is the only user and no mitigation is planned.
5. Live check: `auth_status` shows the four scopes read from the token file; `drive_create_folder` and `drive_rename` on a scratch folder inside the Hermes folder; `mail_create_draft` addressed to Jimmy appears in the Hermes account's Drafts; `mail_create_reply_draft` on a real manual forward in the Hermes inbox is addressed to the forwarded message's sender and recipients (not to Jimmy or Hermes), carries the wrapper's In-Reply-To and References, and nothing is sent; if a filter-forwarded message exists, one reply draft on it too, confirming it joins the existing conversation in the Hermes mailbox; clean up the scratch folder and drafts with explicit consent.

Afterwards: resolve Mimir tasks #1103, #1106 and #950 as done and #355 as dropped; archive fact #354 (send destination); record the new scope set and tool surface as facts on thread #231.

## 9. Out of scope

- Exporting Google-native files in `drive_get` (task #900).
- A folder-tree guard on Drive writes.
- Draft signatures, HTML bodies, or setting From for a send-as alias.
- CLI subcommands for the new operations; the CLI stays debug-only.
- A local draft sidecar or restore tool; Gmail draft ids are stable and Gmail has no Titan-style wipe.
- Verifying that Gmail filter forwarding preserves the original headers; the parsing rule does not depend on it.
