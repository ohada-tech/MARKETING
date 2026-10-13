import pytest

from app.leads.normalize import (
    is_placeholder,
    normalize_company,
    normalize_domain,
    normalize_phone,
    parse_score_breakdown,
    split_subject,
)
from app.models import LEAD_STATUSES, can_transition


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.Shop.co.il/about?x=1", "shop.co.il"),
        ("shop.co.il", "shop.co.il"),
        ("http://sub.shop.co.il", "sub.shop.co.il"),
        ("https://www.facebook.com/somepage", None),
        ("https://instagram.com/someone", None),
        ("", None),
        ("not a url", None),
    ],
)
def test_normalize_domain(url, expected):
    assert normalize_domain(url) == expected


@pytest.mark.parametrize(
    "phone, expected",
    [
        ("050-1234567", "972501234567"),
        ("+972 50 123 4567", "972501234567"),
        ("00972501234567", "972501234567"),
        ("03-6123456", "97236123456"),
        ("(512) 831-5397", "5128315397"),
        ("050-0000000", None),
        ("", None),
        ("123", None),
    ],
)
def test_normalize_phone(phone, expected):
    assert normalize_phone(phone) == expected


def test_normalize_company():
    assert normalize_company('קפה הגפן בע"מ') == normalize_company("קפה  הגפן") == "קפה הגפן"
    assert normalize_company("[דוגמה] Acme Ltd.") == "acme"


def test_is_placeholder():
    assert is_placeholder("[נכתב בזמן הריצה]")
    assert is_placeholder("  ")
    assert is_placeholder(None)
    assert not is_placeholder("[שם] היי, ראיתי את המודעה")


def test_split_subject():
    assert split_subject("נושא: היי\n\nגוף") == ("היי", "גוף")
    assert split_subject("Subject: hi\nbody") == ("hi", "body")
    assert split_subject("רק גוף") == (None, "רק גוף")


def test_parse_score_breakdown_formats():
    assert parse_score_breakdown("א'35 (14 מודעות) + ב'25 + ג'20 + ד'15 + ה'0 = 95") == {
        "א": 35, "ב": 25, "ג": 20, "ד": 15, "ה": 0,
    }
    assert parse_score_breakdown("spend 30 + gap 20 + pay 18 + reach 0 + timing 10 = 78, MINUS 15") == {
        "spend": 30, "gap": 20, "pay": 18, "reach": 0, "timing": 10, "penalty": -15,
    }
    assert parse_score_breakdown("אין כאן ניקוד") is None


def test_suppressed_is_final_and_reachable_from_everywhere():
    for status in LEAD_STATUSES:
        assert not can_transition("suppressed", status)
        if status != "suppressed":
            assert can_transition(status, "suppressed")


def test_lead_state_machine_follows_spec():
    assert can_transition("new", "researched")
    assert can_transition("contacted", "no_reply")
    assert can_transition("no_reply", "archived")
    assert can_transition("proposal_sent", "won")
    assert not can_transition("new", "contacted")
    assert not can_transition("archived", "contacted")
