# hermes-google

MCP server giving Hermes (Claude Code running as a personal assistant) scoped
access to Gmail, Google Calendar, and Google Drive through a dedicated Hermes
Google account — without granting access to your personal Google account.

See [`docs/superpowers/specs/2026-04-23-hermes-google-design.md`](docs/superpowers/specs/2026-04-23-hermes-google-design.md)
for the full design.

## Install

### 1. Register the MCP server with Claude Code

Pick the scope that fits your use case:

```bash
# Project scope — shared via .mcp.json, committed to git (recommended for teams)
claude mcp add -s project hermes-google -- uvx hermes-google-mcp

# User scope — available in all your projects
claude mcp add -s user hermes-google -- uvx hermes-google-mcp

# Local scope — private to you in this project only (default if -s is omitted)
claude mcp add hermes-google -- uvx hermes-google-mcp
```

### 2. Create a Hermes Google account (one-time)

1. Sign up for a plain Gmail account (e.g., `hermes-yourname@gmail.com`)
2. In Google Cloud Console: create a project, enable Gmail, Calendar, and
   Drive APIs
3. Create an OAuth 2.0 Client ID (type: Desktop application) and download
   `client_secret.json`
4. Place it at `~/.config/hermes-google/client_secret.json`

### 3. Run setup

```bash
# Clone and run the setup script
git clone https://github.com/jimmy-larsson/hermes-google.git
cd hermes-google
./scripts/setup.sh
```

The setup script creates the config, runs the OAuth flow, and prints the
remaining manual steps (Gmail filters, Calendar/Drive sharing).

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
