import csv
import json
from pathlib import Path

import pytest
from sqlmodel import Session

from app.db import init_db, make_engine

IL_COLUMNS = [
    "score", "company", "segment", "city", "region", "website", "instagram", "facebook_page",
    "contact_name", "contact_title", "email", "phone", "whatsapp", "evidence_type", "evidence_url",
    "signal_notes", "offer_fit", "suggested_package", "legal_route", "first_touch_wa",
    "first_touch_email", "followup_1", "followup_2", "channel", "needs_manual", "date_found",
]

# Synthetic businesses only. Real lead files contain personal data and never go in the repo.
_SEGMENTS = ["local_service", "dtc", "agency"]
_CITIES = ["תל אביב", "חיפה", "רמת גן", "הרצליה", "באר שבע", "ירושלים", "פתח תקווה", "נתניה"]
_ROUTES = ["call", "dm", "group_reply", "consented_email", "ad_disclosed"]


def lead_row(i: int, **overrides) -> dict:
    """Row i of the synthetic set. Every fourth lead has placeholder drafts only."""
    route = _ROUTES[i % len(_ROUTES)]
    has_drafts = i % 4 != 0
    row = {
        "score": str(95 - i),
        "company": f"עסק בדיקה {i:02d}",
        "segment": _SEGMENTS[i % len(_SEGMENTS)],
        "city": _CITIES[i % len(_CITIES)],
        "region": "גוש דן",
        "website": f"https://www.test-business-{i:02d}.co.il/" if i % 3 else "",
        "instagram": f"@test_{i:02d}",
        "facebook_page": "https://www.facebook.com/testpage" if i % 5 == 0 else "",
        "contact_name": f"איש קשר {i:02d}" if i % 2 else "—",
        "contact_title": "בעלים",
        "email": f"owner{i:02d}@example.com" if route in ("consented_email", "ad_disclosed") else "",
        "phone": f"052-{1000000 + i}",
        "whatsapp": f"052-{1000000 + i}" if route == "dm" else "",
        "evidence_type": "meta_ad",
        "evidence_url": f"https://www.facebook.com/ads/library/?id=TEST{i}",
        "signal_notes": f"א'30 + ב'20 + ג'{i % 20} + ד'10 + ה'5. ראיה סינתטית {i}.",
        "offer_fit": f"זווית בדיקה {i:02d}: נפח קריאייטיב לקמפיין שכבר רץ",
        "suggested_package": "Growth",
        "legal_route": route,
        "first_touch_wa": (
            f"היי, ראיתי את המודעה של עסק בדיקה {i:02d}. אשמח להראות לך בכמה דקות למה אני מתכוון."
            if has_drafts and route in ("dm", "call", "group_reply")
            else "[נכתב בזמן הריצה]"
        ),
        "first_touch_email": (
            f"נושא: שאלה קצרה\n\nהיי, ראיתי את הקמפיין של עסק בדיקה {i:02d}. יש לך רבע שעה השבוע?"
            if has_drafts and route in ("consented_email", "ad_disclosed")
            else ""
        ),
        "followup_1": f"קפצתי שוב לגבי עסק בדיקה {i:02d}." if has_drafts else "",
        "followup_2": "",
        "channel": "meta_ad_library",
        "needs_manual": "yes" if i % 2 else "no",
        "date_found": "2026-09-01",
    }
    row.update(overrides)
    return row


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    columns = columns or IL_COLUMNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    return path


def profile_data(company: str, url: str = "") -> dict:
    return {
        "company": company,
        "what_they_sell": "שירות בדיקה",
        "audience": "בעלי עסקים",
        "positioning": "מקומי",
        "price_points": [{"item": "חבילה", "price": "1,000", "url": "https://example.com/prices"}],
        "avg_ticket": {"value": 1000, "basis": "מחירון", "confidence": "בינוני"},
        "site_audit": {"url": url, "main_cta": "", "lead_capture": "", "video_on_site": "",
                       "trust_signals": "", "dedicated_landing_pages": "", "issues": []},
        "reviews": {"rating": None, "count": None, "source": ""},
        "ads": "3 מודעות פעילות",
        "weaknesses": [{"point": "אין וידאו באתר", "evidence": "", "source": "https://example.com", "confidence": "גבוה"}],
        "opportunities": ["סט מודעות וידאו"],
        "recommended_services": [{"service": "סט מודעות", "what_exactly": "6 גרסאות", "why": "בדיקה"}],
        "package": "Growth",
        "roi": {"monthly_investment": "", "avg_ticket": "", "margin_assumption": "", "breakeven": "",
                "one_liner": "שתי מכירות בחודש מכסות את ההשקעה", "confidence": "בינוני", "sources": []},
        "call_only_notes": "להזכיר בעדינות את דף הנחיתה",
        "not_verified": ["מספר הסניפים"],
    }


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def leads_dir(tmp_path) -> Path:
    """A folder shaped like the client finder output: 32 leads plus two profiles."""
    folder = tmp_path / "finder"
    write_csv(folder / "leads_2026-09-01.csv", [lead_row(i) for i in range(1, 33)])
    profiles = folder / "profiles"
    profiles.mkdir()
    (profiles / "01.json").write_text(
        json.dumps(profile_data("עסק בדיקה 01", "https://test-business-01.co.il"), ensure_ascii=False), encoding="utf-8"
    )
    (profiles / "02.json").write_text(json.dumps(profile_data("עסק בדיקה 02 בע\"מ"), ensure_ascii=False), encoding="utf-8")
    return folder
