#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="hermes-google"
CONFIG_DIR="${HOME}/.config/hermes-google"
CACHE_DIR="${HOME}/.cache/hermes-google"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

# 1. Conda env
if ! conda env list | grep -qE "^${ENV_NAME}\s"; then
    green "Creating conda env: ${ENV_NAME}"
    conda env create -f conda-env.yml
else
    green "Conda env ${ENV_NAME} already exists"
fi

# 2. Config + cache dirs
mkdir -p "${CONFIG_DIR}" "${CACHE_DIR}"
chmod 700 "${CONFIG_DIR}"

# 3. Config file
if [[ ! -f "${CONFIG_DIR}/config.toml" ]]; then
    yellow "Writing default config to ${CONFIG_DIR}/config.toml"
    read -rp "Your personal email (where drafts are delivered): " USER_EMAIL
    read -rp "Hermes Google account email: " HERMES_EMAIL
    cat > "${CONFIG_DIR}/config.toml" <<EOF
[user]
email = "${USER_EMAIL}"
# calendar_id = "${USER_EMAIL}"   # uncomment after sharing your calendar to Hermes

[hermes_account]
email = "${HERMES_EMAIL}"

[paths]
credentials = "${CONFIG_DIR}/credentials.json"
cache = "${CACHE_DIR}"
log = "${CACHE_DIR}/log.jsonl"

[mcp]
name = "hermes-google"
EOF
fi

# 4. OAuth client secret
if [[ ! -f "${CONFIG_DIR}/client_secret.json" ]]; then
    yellow "Place your Google Cloud OAuth client secret at:"
    yellow "  ${CONFIG_DIR}/client_secret.json"
    yellow "Then re-run this script."
    exit 0
fi

# 5. OAuth login
if [[ ! -f "${CONFIG_DIR}/credentials.json" ]]; then
    green "Running OAuth flow"
    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "${ENV_NAME}"
    hermes-google auth login --client-secret "${CONFIG_DIR}/client_secret.json"
fi

# 6. Register MCP server with Claude Code
green "Registering MCP server with Claude Code"
claude mcp add hermes-google -- python -m hermes_google.mcp_server || true

# 7. Print remaining manual steps
cat <<EOF

$(green "Setup complete.") Remaining manual steps:

  1. Gmail filters in your PERSONAL Gmail:
     - label:hermes-review → forward to ${HERMES_EMAIL:-<Hermes account>}
     - from:${HERMES_EMAIL:-<Hermes account>} to:me → apply label "hermes"

  2. Share your primary Google Calendar with ${HERMES_EMAIL:-<Hermes account>}
     at "Make changes to events" level. Then uncomment
     [user].calendar_id in config.toml with your calendar ID.

  3. Share specific Drive files/folders with ${HERMES_EMAIL:-<Hermes account>}.
     Create a top-level "Hermes" folder in your Drive and note its folder ID
     if you want drive_upload to default there (set [drive].default_parent_folder_id
     in config.toml).

  4. Restart your Hermes session to pick up the new MCP tools.

EOF
