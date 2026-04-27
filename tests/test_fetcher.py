from unittest.mock import MagicMock, patch

import pytest
import requests

from src.fetcher import FeedParseError, extract_when, fetch_feed, parse_feed

SAMPLE_RSS_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>DMS Events</title>
    <link>https://calendar.dallasmakerspace.org/events/feed/rss</link>
    <description>Events and Classes available at the Dallas Makerspace</description>
    <pubDate>Sun, 26 Apr 2026 23:57:16 +0000</pubDate>

    <item>
      <title>  Laser Cutter Basics  </title>
      <link>http://calendar.dallasmakerspace.org/events/view/27975</link>
      <guid>http://calendar.dallasmakerspace.org/events/view/27975</guid>
      <pubDate>Sun, 26 Apr 2026 15:39:00 +0000</pubDate>
      <author>Jane Doe</author>
      <category domain="event:category">Class</category>
      <category>Class</category>
      <category domain="event:category">Laser</category>
      <description>&lt;table&gt;&lt;tr&gt;&lt;td&gt;&lt;strong&gt;When&lt;/strong&gt;&lt;/td&gt;&lt;td&gt;Mon Apr 27 10am &amp;mdash; 4pm Central&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</description>
    </item>

    <item>
      <title>Machine Shop Tour</title>
      <link>http://calendar.dallasmakerspace.org/events/view/28000</link>
      <guid>http://calendar.dallasmakerspace.org/events/view/28000</guid>
      <pubDate>Sat, 25 Apr 2026 10:00:00 +0000</pubDate>
      <author>Bob Smith</author>
      <category domain="event:category">Event</category>
      <category>Event</category>
      <description>&lt;table&gt;&lt;tr&gt;&lt;td&gt;&lt;strong&gt;Where&lt;/strong&gt;&lt;/td&gt;&lt;td&gt;Machine Shop&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</description>
    </item>

    <item>
      <title>3D Printing Workshop</title>
      <link>http://calendar.dallasmakerspace.org/events/view/28001</link>
      <guid>http://calendar.dallasmakerspace.org/events/view/28001</guid>
      <pubDate>Fri, 24 Apr 2026 09:00:00 +0000</pubDate>
      <author>Carol Lee</author>
      <category domain="event:category">Class</category>
      <category>Class</category>
      <description></description>
    </item>
  </channel>
</rss>
"""

# The RSS feed HTML-encodes its description once; after html.unescape() the em-dash
# appears as the literal Unicode character U+2014 (—), not as &mdash;.
DESCRIPTION_WITH_WHEN = (
    "&lt;table&gt;"
    "&lt;tr&gt;&lt;td&gt;&lt;strong&gt;When&lt;/strong&gt;&lt;/td&gt;"
    "&lt;td&gt;Mon Apr 27 10am — 4pm Central&lt;/td&gt;&lt;/tr&gt;"
    "&lt;/table&gt;"
)

DESCRIPTION_WITH_WHITESPACE_WHEN = (
    "&lt;table&gt;"
    "&lt;tr&gt;&lt;td&gt;&lt;strong&gt;When&lt;/strong&gt;&lt;/td&gt;"
    "&lt;td&gt;\n  Mon Apr 27\n  10am — 4pm Central\n&lt;/td&gt;&lt;/tr&gt;"
    "&lt;/table&gt;"
)


class TestParseFeed:
    def test_returns_all_items(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert len(events) == 3

    def test_extracts_guid(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert events[0]["guid"] == "http://calendar.dallasmakerspace.org/events/view/27975"

    def test_extracts_event_id(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert events[0]["event_id"] == "27975"
        assert events[1]["event_id"] == "28000"

    def test_strips_title(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert events[0]["title"] == "Laser Cutter Basics"

    def test_extracts_link(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert events[0]["link"] == "http://calendar.dallasmakerspace.org/events/view/27975"

    def test_extracts_categories_with_domain_only(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert events[0]["categories"] == ["Class", "Laser"]

    def test_extracts_when_from_description(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert "10am" in events[0]["when"]

    def test_when_empty_if_no_when_row(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert events[1]["when"] == ""

    def test_malformed_xml_raises_feed_parse_error(self):
        with pytest.raises(FeedParseError):
            parse_feed("<not valid xml")

    def test_empty_channel_returns_empty_list(self):
        xml = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        assert parse_feed(xml) == []

    def test_pub_date_extracted(self):
        events = parse_feed(SAMPLE_RSS_XML)
        assert events[0]["pub_date"] == "Sun, 26 Apr 2026 15:39:00 +0000"

    def test_no_channel_returns_empty_list(self):
        xml = '<?xml version="1.0"?><rss version="2.0"></rss>'
        assert parse_feed(xml) == []


class TestExtractWhen:
    def test_normal_when(self):
        result = extract_when(DESCRIPTION_WITH_WHEN)
        assert result == "Mon Apr 27 10am — 4pm Central"

    def test_missing_when_returns_empty(self):
        result = extract_when("<table><tr><td>No when here</td></tr></table>")
        assert result == ""

    def test_collapses_whitespace(self):
        result = extract_when(DESCRIPTION_WITH_WHITESPACE_WHEN)
        assert "\n" not in result
        assert "  " not in result

    def test_empty_description_returns_empty(self):
        assert extract_when("") == ""


class TestFetchFeed:
    def test_success_returns_text(self):
        mock_response = MagicMock()
        mock_response.text = "<rss/>"
        mock_response.raise_for_status = MagicMock()
        with patch("src.fetcher.requests.get", return_value=mock_response) as mock_get:
            result = fetch_feed("http://example.com")
        assert result == "<rss/>"
        mock_get.assert_called_once()

    def test_timeout_propagates(self):
        with patch("src.fetcher.requests.get", side_effect=requests.exceptions.Timeout):
            with pytest.raises(requests.exceptions.Timeout):
                fetch_feed("http://example.com")

    def test_http_error_raises(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        with patch("src.fetcher.requests.get", return_value=mock_response):
            with pytest.raises(requests.exceptions.HTTPError):
                fetch_feed("http://example.com")
