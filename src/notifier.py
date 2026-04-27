import logging
import time

import requests

MAX_MESSAGE_CHARS = 4000

logger = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


def format_event_line(event: dict) -> str:
    title = event.get("title", "").strip()
    link = event.get("link", "")
    when = event.get("when", "")
    line = f"• [{title}]({link})"
    if when:
        line += f" — When: {when}"
    return line


def build_startup_message(event_count: int) -> str:
    return (
        f"✅ DMS Calendar Bot is running! "
        f"Found {event_count} events in the calendar. "
        f"I'll notify you when new ones are added."
    )


def build_messages(new_events: list[dict]) -> list[str]:
    if not new_events:
        return []

    header = f"🆕 *New DMS Events* ({len(new_events)} new)\n\n"
    continuation = "🆕 *New DMS Events* (cont.)\n\n"

    chunks = []
    current_header = header
    current_chunk = current_header

    for event in new_events:
        line = format_event_line(event) + "\n"
        if len(current_chunk) + len(line) > MAX_MESSAGE_CHARS:
            chunks.append(current_chunk.rstrip())
            current_header = continuation
            current_chunk = current_header + line
        else:
            current_chunk += line

    if current_chunk.strip() != current_header.strip():
        chunks.append(current_chunk.rstrip())

    return chunks


def send_message(
    bot_token: str, chat_id: str, text: str, session: requests.Session
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    response = session.post(url, json=payload, timeout=15)
    if not response.ok:
        raise TelegramError(
            f"Telegram API error {response.status_code}: {response.text}"
        )


def send_error(bot_token: str, chat_id: str, error_msg: str) -> None:
    text = f"⚠️ DMS Bot Error: {error_msg}"
    try:
        with requests.Session() as session:
            send_message(bot_token, chat_id, text, session)
    except Exception as exc:
        logger.error("Failed to send error notification to Telegram: %s", exc)


def send_new_events(
    bot_token: str, chat_id: str, new_events: list[dict]
) -> None:
    chunks = build_messages(new_events)
    if not chunks:
        return
    with requests.Session() as session:
        for i, chunk in enumerate(chunks):
            send_message(bot_token, chat_id, chunk, session)
            if i < len(chunks) - 1:
                time.sleep(0.1)
