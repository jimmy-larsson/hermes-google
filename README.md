# hermes-google

MCP server giving Hermes (Claude Code running as a personal assistant) scoped
access to Gmail, Google Calendar, and Google Drive through a dedicated Hermes
Google account — without granting access to your personal Google account.

See [`docs/superpowers/specs/2026-04-23-hermes-google-design.md`](docs/superpowers/specs/2026-04-23-hermes-google-design.md)
for the full design.

## Quick Start

Add hermes-google to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "hermes-google": {
      "type": "stdio",
      "command": "uvx",
      "args": ["hermes-google-mcp@latest"]
    }
  }
}
```

## Google Account Setup

1. Sign up for a plain Gmail account (e.g., `hermes-yourname@gmail.com`)
2. In [Google Cloud Console](https://console.cloud.google.com/): create a
   project, enable the Gmail, Calendar, and Drive APIs
3. Create an **OAuth 2.0 Client ID** (type: Desktop application) and download
   the client secret JSON
4. Save it as `~/.config/hermes-google/oauth_client.json`
5. Run the setup script:

```bash
git clone https://github.com/jimmy-larsson/hermes-google.git
cd hermes-google
./scripts/setup.sh
```

The setup script creates the config, runs the OAuth flow (saving the token to
`~/.config/hermes-google/token.json`), and prints the remaining manual steps.

### Host-Side OAuth

The OAuth flow opens a browser for consent — it must run on your host machine,
not inside a headless container.

If your config and credentials live inside a container (e.g. Docker-mounted
`~/.config/hermes-google/`), you need to:

1. Copy `config.toml` and `oauth_client.json` to the **host** filesystem at
   `~/.config/hermes-google/`
2. Run the OAuth flow from the host:
   ```bash
   uvx hermes-google-mcp@latest auth login
   ```
3. The resulting `token.json` is saved on the host — it will be picked up by
   the container through the volume mount

## Gmail Setup

Create filters in your **personal** Gmail to route emails to the Hermes account:

1. For each sender you want Hermes to handle: create a filter that **both**
   labels the email (e.g. `hermes-review`) **and** forwards it to
   `hermes-yourname@gmail.com` — in a single filter
2. For replies from Hermes: `from:hermes-yourname@gmail.com` → apply label
   `hermes`

### Gotchas

- **Filters don't chain.** Gmail evaluates all filters in a single pass against
  the original message properties. A label applied by filter A will *not*
  trigger filter B that matches on that label. You must combine label + forward
  into one filter per sender/criteria.
- **"Apply to existing" skips forwarding.** When you click "Also apply filter to
  matching conversations", Gmail only runs local actions (label, archive, star).
  Forwarding only fires on new incoming messages.

## Calendar & Drive Setup

- **Calendar:** Share your calendar with the Hermes account at "Make changes to
  events" permission level. Set `[user].calendar_id` in `config.toml`.
- **Drive:** Share specific files/folders with the Hermes account. Optionally
  set `[drive].default_parent_folder_id` in `config.toml` for a default upload
  folder.

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

- Delete the forwarding filter in your personal Gmail
- Unshare your calendar with the Hermes account
- Unshare a Drive file or folder
- `hermes-google auth revoke` — removes the refresh token locally
- `claude mcp remove hermes-google` — Hermes loses the tools; Google data
  untouched
- Delete the Hermes Google account entirely

## Development

```bash
conda activate hermes-google
pytest
ruff check src tests
```

### Releasing

```bash
# 1. Bump version in pyproject.toml, commit and push
git commit -am "chore: bump version to X.Y.Z"
git push

# 2. Tag locally and push — triggers the CI pipeline
git tag X.Y.Z
git push origin X.Y.Z

# 3. After CI passes, create the GitHub release
gh release create X.Y.Z --verify-tag --generate-notes
```

## Alternative Install Methods

```bash
# User scope — available in all your projects
claude mcp add -s user hermes-google -- uvx hermes-google-mcp

# Local scope — private to you in this project only
claude mcp add hermes-google -- uvx hermes-google-mcp
```
