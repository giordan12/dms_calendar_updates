import html
import re
import xml.etree.ElementTree as ET

import requests

RSS_URL = "https://calendar.dallasmakerspace.org/events/feed/rss"

_WHEN_PATTERN = re.compile(
    r"<td><strong>When</strong></td>\s*<td>(.*?)</td>", re.DOTALL
)
_INNER_TAGS = re.compile(r"<[^>]+>")
_EVENT_ID_PATTERN = re.compile(r"/events/view/(\d+)$")


class FeedParseError(Exception):
    pass


def fetch_feed(url: str = RSS_URL, timeout: int = 30) -> str:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "dms-calendar-bot/1.0"},
    )
    response.raise_for_status()
    return response.text


def extract_when(description_html: str) -> str:
    unescaped = html.unescape(description_html)
    match = _WHEN_PATTERN.search(unescaped)
    if not match:
        return ""
    cell = _INNER_TAGS.sub("", match.group(1))
    return " ".join(cell.split())


def parse_feed(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedParseError(f"Failed to parse RSS feed: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        return []

    events = []
    for item in channel.findall("item"):
        guid = (item.findtext("guid") or "").strip()
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        description = item.findtext("description") or ""
        pub_date = (item.findtext("pubDate") or "").strip()

        id_match = _EVENT_ID_PATTERN.search(guid)
        event_id = id_match.group(1) if id_match else ""

        categories = [
            cat.text
            for cat in item.findall("category")
            if cat.get("domain") == "event:category" and cat.text
        ]

        events.append(
            {
                "guid": guid,
                "event_id": event_id,
                "title": title,
                "link": link,
                "when": extract_when(description),
                "pub_date": pub_date,
                "categories": categories,
            }
        )

    return events
