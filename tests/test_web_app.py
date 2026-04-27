# Created: 21:55 27-Apr-2026
"""Tests for web/app.py — _highlight, _parse_date, _month_presets, port pick."""
from __future__ import annotations

import socket
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from web import app as web_app


pytestmark = pytest.mark.unit


# ---- _highlight ----------------------------------------------------------


def test_highlight_no_query_just_escapes() -> None:
    assert web_app._highlight("<b>x</b>", "") == "&lt;b&gt;x&lt;/b&gt;"


def test_highlight_empty_text_returns_empty() -> None:
    assert web_app._highlight("", "anything") == ""
    assert web_app._highlight(None, "anything") == ""


def test_highlight_wraps_match_in_mark() -> None:
    assert web_app._highlight("hello world", "world") == "hello <mark>world</mark>"


def test_highlight_is_case_insensitive() -> None:
    assert web_app._highlight("Hello WORLD", "world") == "Hello <mark>WORLD</mark>"


def test_highlight_escapes_query_metacharacters() -> None:
    # `re.escape` makes '.' literal; the dot in the query must not
    # match every char.
    out = web_app._highlight("a.b a-b", ".")
    assert out == "a<mark>.</mark>b a-b"


def test_highlight_escapes_html_in_text_around_match() -> None:
    out = web_app._highlight("<script>alert(1)</script>", "alert")
    assert "<script>" not in out  # raw tag never appears
    assert "&lt;script&gt;" in out
    assert "<mark>alert</mark>" in out


def test_highlight_handles_multiple_matches() -> None:
    out = web_app._highlight("ab AB ab", "ab")
    assert out == "<mark>ab</mark> <mark>AB</mark> <mark>ab</mark>"


def test_highlight_does_not_double_escape_match() -> None:
    # The match itself contains chars that need HTML escaping.
    out = web_app._highlight("foo<bar>baz", "<bar>")
    assert "<mark>&lt;bar&gt;</mark>" in out


# ---- _parse_date ---------------------------------------------------------


def test_parse_date_none_returns_none() -> None:
    assert web_app._parse_date(None) is None
    assert web_app._parse_date("") is None


def test_parse_date_invalid_format_returns_none() -> None:
    assert web_app._parse_date("nope") is None
    assert web_app._parse_date("2026/01/01") is None
    assert web_app._parse_date("2026-13-40") is None


def test_parse_date_start_of_day_local() -> None:
    ts = web_app._parse_date("2026-01-15")
    # Decode back through the local TZ — must round-trip to midnight.
    dt = datetime.fromtimestamp(ts).replace(microsecond=0)
    assert dt == datetime(2026, 1, 15, 0, 0, 0)


def test_parse_date_end_of_day_uses_235959() -> None:
    ts = web_app._parse_date("2026-01-15", end_of_day=True)
    dt = datetime.fromtimestamp(ts)
    assert (dt.hour, dt.minute, dt.second) == (23, 59, 59)


def test_parse_date_dst_spring_forward_does_not_raise() -> None:
    # 2026-03-08 is US spring-forward day. The naive timestamp() approach
    # is platform-dependent; the localized version must always succeed.
    ts = web_app._parse_date("2026-03-08")
    assert ts is not None
    # And end-of-day should still resolve.
    ts_eod = web_app._parse_date("2026-03-08", end_of_day=True)
    assert ts_eod is not None
    assert ts_eod > ts


def test_parse_date_orders_correctly() -> None:
    a = web_app._parse_date("2026-01-15")
    b = web_app._parse_date("2026-01-16")
    assert a < b


# ---- _month_presets ------------------------------------------------------


def test_month_presets_returns_three_prior_months() -> None:
    out = web_app._month_presets(date(2026, 4, 21), count=3)
    labels = [p["label"] for p in out]
    assert labels == ["Mar 2026", "Feb 2026", "Jan 2026"]


def test_month_presets_handles_year_boundary() -> None:
    out = web_app._month_presets(date(2026, 1, 5), count=3)
    labels = [p["label"] for p in out]
    assert labels == ["Dec 2025", "Nov 2025", "Oct 2025"]


def test_month_presets_each_entry_has_full_month_range() -> None:
    out = web_app._month_presets(date(2026, 4, 21), count=1)
    p = out[0]
    assert p["date_from"] == "2026-03-01"
    assert p["date_to"] == "2026-03-31"


def test_month_presets_february_leap_year() -> None:
    # 2024 was a leap year — Feb has 29 days.
    out = web_app._month_presets(date(2024, 3, 5), count=1)
    p = out[0]
    assert p["date_from"] == "2024-02-01"
    assert p["date_to"] == "2024-02-29"


# ---- pick_open_port ------------------------------------------------------


def test_pick_open_port_returns_an_integer() -> None:
    # Pick from a high range that's unlikely to collide locally.
    p = web_app.pick_open_port(preferred=49152, attempts=4)
    assert isinstance(p, int)
    assert 1 <= p <= 65535


def test_pick_open_port_falls_through_when_preferred_taken() -> None:
    # Hold a known port to force the picker onto the next slot.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy_port = s.getsockname()[1]
    try:
        chosen = web_app.pick_open_port(preferred=busy_port, attempts=10)
        assert chosen != busy_port
    finally:
        s.close()


# ---- _is_local_origin ----------------------------------------------------


class _FakeRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_is_local_origin_accepts_no_headers() -> None:
    # WKWebView / pywebview fetch may omit Origin entirely. Allowed.
    req = _FakeRequest({})
    assert web_app._is_local_origin(req) is True


def test_is_local_origin_accepts_localhost() -> None:
    req = _FakeRequest({"origin": "http://127.0.0.1:8765"})
    assert web_app._is_local_origin(req) is True
    req = _FakeRequest({"referer": "http://localhost:8765/"})
    assert web_app._is_local_origin(req) is True


def test_is_local_origin_rejects_external() -> None:
    req = _FakeRequest({"origin": "https://evil.example.com"})
    assert web_app._is_local_origin(req) is False
