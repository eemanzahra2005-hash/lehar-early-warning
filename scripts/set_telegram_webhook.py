"""Register LEHAR's Telegram webhook with the Bot API (LEHAR Phase 3).

Tells Telegram to POST every update for your bot to

    <PUBLIC_BASE_URL>/api/v1/alerts/telegram/webhook

with TELEGRAM_WEBHOOK_SECRET in the X-Telegram-Bot-Api-Secret-Token header
(the endpoint refuses anything without it), and registers the bot's command
menu. Run it once after deploying, and again whenever PUBLIC_BASE_URL or the
secret changes. LEHAR uses webhook mode only — never polling.

    .venv\\Scripts\\python scripts\\set_telegram_webhook.py            register
    .venv\\Scripts\\python scripts\\set_telegram_webhook.py --info     show what Telegram has
    .venv\\Scripts\\python scripts\\set_telegram_webhook.py --delete   unregister
    .venv\\Scripts\\python scripts\\set_telegram_webhook.py --url https://abc.ngrok-free.app

Reads TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and PUBLIC_BASE_URL from
backend/.env (or the environment). The bot token is never printed. Telegram
only delivers to HTTPS URLs, so a local test needs a tunnel — see
docs/ALERTS.md.
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.services.alerts.channels.telegram import TelegramChannel  # noqa: E402

# The menu Telegram shows when a user types "/". Same commands the webhook
# handles in app/services/alerts/channels/telegram.py.
COMMANDS = [
    {"command": "start", "description": "Subscribe to a district: /start <district_code>"},
    {"command": "stop", "description": "Stop all alerts"},
    {"command": "level", "description": "Minimum alert level: /level <1-5>"},
    {"command": "lang", "description": "Language: /lang en or /lang ur"},
    {"command": "status", "description": "Your subscription and today's levels"},
]

# Only the update types the webhook handles; Telegram then never sends the rest.
ALLOWED_UPDATES = ["message", "callback_query"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="public https:// base URL to use instead of PUBLIC_BASE_URL")
    parser.add_argument("--info", action="store_true", help="print Telegram's current webhook info and exit")
    parser.add_argument("--delete", action="store_true", help="remove the webhook and exit")
    parser.add_argument(
        "--drop-pending", action="store_true", help="discard updates Telegram queued while no webhook was reachable"
    )
    args = parser.parse_args()

    settings = get_settings()
    channel = TelegramChannel()
    if not channel.enabled:
        print("TELEGRAM_BOT_TOKEN is not set in backend/.env — nothing to do.", file=sys.stderr)
        return 1

    if args.info:
        outcome = channel.api_call("getWebhookInfo", {})
        if not outcome.ok:
            print(f"getWebhookInfo failed: {outcome.error}", file=sys.stderr)
            return 1
        for key, value in (outcome.body or {}).get("result", {}).items():
            print(f"{key}: {value}")
        return 0

    if args.delete:
        outcome = channel.api_call("deleteWebhook", {"drop_pending_updates": args.drop_pending})
        print("Webhook removed." if outcome.ok else f"deleteWebhook failed: {outcome.error}")
        return 0 if outcome.ok else 1

    base_url = (args.url or settings.public_base_url).rstrip("/")
    if not base_url.startswith("https://"):
        print(
            "Telegram only delivers webhooks to https:// URLs. Set PUBLIC_BASE_URL (or pass --url) to your "
            "deployed API or an HTTPS tunnel — see docs/ALERTS.md.",
            file=sys.stderr,
        )
        return 1
    if not settings.telegram_webhook_secret:
        print("TELEGRAM_WEBHOOK_SECRET is not set in backend/.env — the webhook would refuse every call.", file=sys.stderr)
        return 1

    webhook_url = f"{base_url}{settings.api_v1_prefix}/alerts/telegram/webhook"
    outcome = channel.api_call(
        "setWebhook",
        {
            "url": webhook_url,
            "secret_token": settings.telegram_webhook_secret,
            "allowed_updates": ALLOWED_UPDATES,
            "drop_pending_updates": args.drop_pending,
            # One connection at a time: the API runs a single worker on a
            # 512 MB host (CLAUDE.md rule 11).
            "max_connections": 1,
        },
    )
    if not outcome.ok:
        print(f"setWebhook failed: {outcome.error}", file=sys.stderr)
        return 1
    print(f"Webhook registered: {webhook_url}")

    commands = channel.api_call("setMyCommands", {"commands": COMMANDS})
    print("Command menu registered." if commands.ok else f"setMyCommands failed (webhook still set): {commands.error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
