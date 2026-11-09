# hermes-google

MCP server giving Hermes (Claude Code running as a personal assistant) scoped
access to Gmail, Google Calendar, and Google Drive through a dedicated Hermes
Google account — without granting access to your personal Google account.

See [`docs/superpowers/specs/2026-04-23-hermes-google-design.md`](docs/superpowers/specs/2026-04-23-hermes-google-design.md)
for the original design and
[`docs/superpowers/specs/2026-11-09-drive-tools-and-gmail-drafts-design.md`](docs/superpowers/specs/2026-11-09-drive-tools-and-gmail-drafts-design.md)
for the 0.4.0 changes (full Drive scope, drafts-only Gmail).

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

### Host-Side OAuth

The default OAuth flow opens a browser for consent, so it must run on your
host machine. Inside a headless container use `hermes-google auth login
--headless`: it prints a URL to open in any browser and asks you to paste the
redirect URL back.

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
2. Forwarding a message to the Hermes account by hand works too

Hermes never sends mail. Reply drafts are written to the **Hermes account's
Drafts folder**: open that account in Gmail (or add it to your mail app) to
review and send. A draft sent from there goes out as the Hermes address
unless you add your own address as a "Send mail as" alias in the Hermes
account's Gmail settings.

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
- **Drive:** Share the folders you want Hermes to work in with the Hermes
  account (editor access to rename or move your own files). Set
  `[drive].default_parent_folder_id` in `config.toml` to the shared folder so
  uploads and new folders land where you can see them; without it they go to
  the Hermes account's own My Drive root.

## Usage

Once installed, the following tools are available to Hermes in every session:

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
