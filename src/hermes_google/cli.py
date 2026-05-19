"""hermes-google debug CLI.

Shares core modules with mcp_server.py. Primary surface is the MCP server;
this CLI exists for:

  - one-time auth bootstrap (`auth login`)
  - auth troubleshooting (`auth status`, `auth revoke`)
  - debug invocations of individual operations (mail/cal/drive subcommands)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from hermes_google.core import auth as auth_core
from hermes_google.core import cal as cal_core
from hermes_google.core import drive as drive_core
from hermes_google.core import mail as mail_core
from hermes_google.core.auth import AuthError
from hermes_google.core.config import Config, load_config


def _cfg() -> Config:
    return load_config()


def _services() -> auth_core.Services:
    cfg = _cfg()
    creds = auth_core.load_credentials(cfg.credentials_path)
    return auth_core.build_services(creds)


def _print_json(value) -> None:
    print(json.dumps(value, indent=2, default=str))


def cmd_auth_login(args: argparse.Namespace) -> int:
    cfg = _cfg()
    client_secret = Path(args.client_secret).expanduser()
    auth_core.run_install_flow(client_secret, cfg.credentials_path, headless=args.headless)
    print(f"credentials saved to {cfg.credentials_path}")
    return 0


def cmd_auth_status(_args: argparse.Namespace) -> int:
    cfg = _cfg()
    try:
        creds = auth_core.load_credentials(cfg.credentials_path)
    except AuthError as exc:
        _print_json({"valid": False, "error": str(exc)})
        return 1
    _print_json(
        {
            "valid": bool(creds.valid),
            "expired": bool(creds.expired),
            "scopes": list(getattr(creds, "scopes", []) or []),
        }
    )
    return 0


def cmd_auth_revoke(_args: argparse.Namespace) -> int:
    cfg = _cfg()
    auth_core.revoke_credentials(cfg.credentials_path)
    print(f"credentials removed at {cfg.credentials_path}")
    return 0


def cmd_mail_list(args: argparse.Namespace) -> int:
    services = _services()
    msgs = mail_core.list_pending(services.gmail, limit=args.limit)
    _print_json([asdict(m) for m in msgs])
    return 0


def cmd_mail_get(args: argparse.Namespace) -> int:
    services = _services()
    cfg = _cfg()
    detail = mail_core.get_message(services.gmail, message_id=args.id, cache_dir=cfg.cache_dir)
    data = asdict(detail)
    data["attachment_paths"] = [str(p) for p in detail.attachment_paths]
    _print_json(data)
    return 0


def cmd_cal_list(args: argparse.Namespace) -> int:
    services = _services()
    cfg = _cfg()
    cid = cal_core.resolve_calendar_id(args.calendar, user_calendar_id=cfg.user_calendar_id)
    events = cal_core.list_events(
        services.calendar, calendar_id=cid, time_min=args.start, time_max=args.end
    )
    _print_json([asdict(e) for e in events])
    return 0


def cmd_drive_search(args: argparse.Namespace) -> int:
    services = _services()
    files = drive_core.search(
        services.drive, query=args.query, mime_type=args.mime_type, limit=args.limit
    )
    _print_json([asdict(f) for f in files])
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hermes-google")
    sub = p.add_subparsers(dest="command", required=True)

    p_auth = sub.add_parser("auth", help="OAuth management")
    s_auth = p_auth.add_subparsers(dest="auth_cmd", required=True)

    login = s_auth.add_parser("login")
    login.add_argument(
        "--client-secret",
        default="~/.config/hermes-google/oauth_client.json",
        help="path to OAuth client secret JSON",
    )
    login.add_argument(
        "--headless",
        action="store_true",
        help="use console flow (prints URL, paste auth code) for headless environments",
    )
    login.set_defaults(func=cmd_auth_login)

    status = s_auth.add_parser("status")
    status.set_defaults(func=cmd_auth_status)

    revoke = s_auth.add_parser("revoke")
    revoke.set_defaults(func=cmd_auth_revoke)

    p_mail = sub.add_parser("mail", help="Gmail debug ops")
    s_mail = p_mail.add_subparsers(dest="mail_cmd", required=True)

    m_list = s_mail.add_parser("list")
    m_list.add_argument("--limit", type=int, default=20)
    m_list.set_defaults(func=cmd_mail_list)

    m_get = s_mail.add_parser("get")
    m_get.add_argument("id")
    m_get.set_defaults(func=cmd_mail_get)

    p_cal = sub.add_parser("cal", help="Calendar debug ops")
    s_cal = p_cal.add_subparsers(dest="cal_cmd", required=True)

    c_list = s_cal.add_parser("list")
    c_list.add_argument("--calendar", default="user")
    c_list.add_argument("--start", required=True)
    c_list.add_argument("--end", required=True)
    c_list.set_defaults(func=cmd_cal_list)

    p_drive = sub.add_parser("drive", help="Drive debug ops")
    s_drive = p_drive.add_subparsers(dest="drive_cmd", required=True)

    d_search = s_drive.add_parser("search")
    d_search.add_argument("query")
    d_search.add_argument("--mime-type")
    d_search.add_argument("--limit", type=int, default=20)
    d_search.set_defaults(func=cmd_drive_search)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
