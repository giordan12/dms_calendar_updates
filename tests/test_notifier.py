from unittest.mock import MagicMock, patch, call

import pytest
import requests

from src.notifier import (
    MAX_MESSAGE_CHARS,
    TelegramError,
    build_messages,
    build_startup_message,
    format_event_line,
    send_error,
    send_message,
    send_new_events,
)

SAMPLE_EVENT = {
    "guid": "http://example.com/events/view/1",
    "event_id": "1",
    "title": "Laser Cutter Basics",
    "link": "http://calendar.dallasmakerspace.org/events/view/27975",
    "when": "Mon Apr 27 10am — 4pm Central",
    "pub_date": "",
    "categories": ["Class"],
}

EVENT_NO_WHEN = {**SAMPLE_EVENT, "when": ""}


def make_events(n: int, title_prefix: str = "Event") -> list[dict]:
    return [
        {
            "guid": f"http://example.com/events/view/{i}",
            "event_id": str(i),
            "title": f"{title_prefix} {i}",
            "link": f"http://calendar.dallasmakerspace.org/events/view/{i}",
            "when": "Mon Apr 27 10am — 4pm Central",
            "pub_date": "",
            "categories": [],
        }
        for i in range(n)
    ]


class TestFormatEventLine:
    def test_with_when(self):
        line = format_event_line(SAMPLE_EVENT)
        assert line == "• [Laser Cutter Basics](http://calendar.dallasmakerspace.org/events/view/27975) — When: Mon Apr 27 10am — 4pm Central"

    def test_without_when(self):
        line = format_event_line(EVENT_NO_WHEN)
        assert line == "• [Laser Cutter Basics](http://calendar.dallasmakerspace.org/events/view/27975)"
        assert "When:" not in line


class TestBuildStartupMessage:
    def test_contains_count(self):
        msg = build_startup_message(162)
        assert "162" in msg

    def test_contains_running_indicator(self):
        msg = build_startup_message(10)
        assert "running" in msg.lower()

    def test_mentions_notification(self):
        msg = build_startup_message(5)
        assert "notify" in msg.lower()


class TestBuildMessages:
    def test_empty_returns_empty_list(self):
        assert build_messages([]) == []

    def test_single_chunk_for_few_events(self):
        events = make_events(3)
        chunks = build_messages(events)
        assert len(chunks) == 1

    def test_first_chunk_has_header(self):
        events = make_events(3)
        chunks = build_messages(events)
        assert "New DMS Events" in chunks[0]
        assert "3 new" in chunks[0]

    def test_multi_chunk_for_many_events(self):
        # Create events with long titles to force chunking
        events = make_events(200, title_prefix="A" * 50)
        chunks = build_messages(events)
        assert len(chunks) > 1

    def test_each_chunk_under_limit(self):
        events = make_events(200, title_prefix="A" * 50)
        for chunk in build_messages(events):
            assert len(chunk) <= MAX_MESSAGE_CHARS

    def test_continuation_header_on_second_chunk(self):
        events = make_events(200, title_prefix="A" * 50)
        chunks = build_messages(events)
        assert "cont." in chunks[1]


class TestSendMessage:
    def test_success_no_exception(self):
        mock_response = MagicMock()
        mock_response.ok = True
        session = MagicMock()
        session.post.return_value = mock_response
        send_message("token", "chat_id", "hello", session)
        session.post.assert_called_once()

    def test_api_error_raises_telegram_error(self):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        session = MagicMock()
        session.post.return_value = mock_response
        with pytest.raises(TelegramError):
            send_message("token", "chat_id", "hello", session)

    def test_sends_with_markdown_parse_mode(self):
        mock_response = MagicMock()
        mock_response.ok = True
        session = MagicMock()
        session.post.return_value = mock_response
        send_message("token", "chat_id", "hello", session)
        _, kwargs = session.post.call_args
        assert kwargs["json"]["parse_mode"] == "Markdown"

    def test_disables_web_page_preview(self):
        mock_response = MagicMock()
        mock_response.ok = True
        session = MagicMock()
        session.post.return_value = mock_response
        send_message("token", "chat_id", "hello", session)
        _, kwargs = session.post.call_args
        assert kwargs["json"]["disable_web_page_preview"] is True


class TestSendError:
    def test_sends_error_message(self):
        mock_response = MagicMock()
        mock_response.ok = True
        with patch("src.notifier.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.post.return_value = mock_response
            mock_session_cls.return_value = mock_session
            send_error("token", "chat_id", "something went wrong")
        _, kwargs = mock_session.post.call_args
        assert "something went wrong" in kwargs["json"]["text"]
        assert "⚠️" in kwargs["json"]["text"]

    def test_does_not_raise_on_telegram_failure(self):
        with patch("src.notifier.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.post.side_effect = requests.exceptions.ConnectionError
            mock_session_cls.return_value = mock_session
            # Should not raise
            send_error("token", "chat_id", "error")


class TestSendNewEvents:
    def test_no_events_never_calls_send(self):
        with patch("src.notifier.requests.Session"):
            with patch("src.notifier.send_message") as mock_send:
                send_new_events("token", "chat_id", [])
        mock_send.assert_not_called()

    def test_single_chunk_calls_send_once(self):
        events = make_events(3)
        with patch("src.notifier.send_message") as mock_send:
            with patch("src.notifier.requests.Session"):
                send_new_events("token", "chat_id", events)
        assert mock_send.call_count == 1

    def test_multiple_chunks_calls_send_multiple_times(self):
        events = make_events(200, title_prefix="A" * 50)
        expected_chunks = len(build_messages(events))
        with patch("src.notifier.send_message") as mock_send:
            with patch("src.notifier.requests.Session"):
                with patch("src.notifier.time.sleep"):
                    send_new_events("token", "chat_id", events)
        assert mock_send.call_count == expected_chunks
