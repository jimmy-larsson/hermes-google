# hermes-google

MCP server giving Hermes (Claude Code running as a personal assistant) scoped
access to Gmail, Google Calendar, and Google Drive through a dedicated Hermes
Google account — without granting access to your personal Google account.

See [`docs/superpowers/specs/2026-04-23-hermes-google-design.md`](docs/superpowers/specs/2026-04-23-hermes-google-design.md)
for the full design.

## Quick install

```bash
# 1. Clone
git clone <repo-url> ~/repositories/private/hermes-google
cd ~/repositories/private/hermes-google

# 2. Create the Hermes Google account (manual step, one-time)
#    - Sign up for a plain Gmail account
#    - In Google Cloud Console: create a project, enable Gmail/Calendar/Drive
#      APIs, create an OAuth 2.0 Client ID (type: Desktop application),
#      download as client_secret.json
#    - Place client_secret.json at ~/.config/hermes-google/client_secret.json

# 3. Run setup
./scripts/setup.sh

# 4. Gmail filters + Calendar/Drive sharing (printed by setup.sh)
```

## Usage

Once installed, the following tools are available to Hermes in every session:

- `mail_list_pending`, `mail_search`, `mail_get`, `mail_send_draft`,
  `mail_mark_read`, `mail_archive`
- `cal_list_calendars`, `cal_list_events`, `cal_create_event`,
  `cal_update_event`, `cal_delete_event`
- `drive_search`, `drive_list`, `drive_get`, `drive_upload`, `drive_update`,
  `drive_move`, `drive_delete`
- `auth_status`

All write operations require user confirmation. `mail_send_draft` is
structurally restricted to your own email; it cannot send to external
recipients.

## Debug CLI

Same operations via shell:

```bash
hermes-google auth status
hermes-google mail list --limit 10
hermes-google mail get <message_id>
hermes-google cal list --start 2026-04-24T00:00:00+09:00 --end 2026-04-25T00:00:00+09:00
hermes-google drive search "Q1 report"
```

## Revocation

Any one of these fully cuts an integration surface:

- Delete the `label:hermes-review → forward` filter in your personal Gmail
- Unshare your calendar with the Hermes account
- Unshare a Drive file or folder
- `hermes-google auth revoke` — removes the refresh token locally
- `claude mcp remove hermes-google` — Hermes loses the tools; Google data untouched
- Delete the Hermes Google account entirely

## Development

```bash
conda activate hermes-google
pytest
ruff check src tests
```
