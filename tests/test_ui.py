import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlmodel import select

from app.leads.importer import import_paths
from app.main import create_app
from app.models import Lead


@pytest.fixture
def client(engine, session, leads_dir):
    import_paths(session, [leads_dir])
    with TestClient(create_app(engine)) as client:
        yield client


def test_leads_page_lists_all_imported_leads_rtl(client):
    response = client.get("/leads")

    assert response.status_code == 200
    html = response.text
    assert 'dir="rtl"' in html
    assert "מוצגים 32 מתוך 32 לידים" in html
    assert "עסק בדיקה 01" in html
    assert "זווית בדיקה 01: נפח קריאייטיב לקמפיין שכבר רץ" in html


def test_leads_filters(client):
    assert "מוצגים 24 מתוך 32" in client.get("/leads", params={"status": "drafted"}).text
    assert "מוצגים 0 מתוך 32" in client.get("/leads", params={"min_score": "100"}).text
    filtered = client.get("/leads", params={"route": "dm"}).text
    assert "עסק בדיקה 01" in filtered  # route dm
    assert "עסק בדיקה 02" not in filtered  # route group_reply
    assert "עסק בדיקה 03" not in filtered  # route consented_email


def test_htmx_request_returns_table_partial(client):
    response = client.get("/leads", params={"q": "07"}, headers={"HX-Request": "true"})

    assert "<html" not in response.text
    assert "עסק בדיקה 07" in response.text
    assert "עסק בדיקה 08" not in response.text


def test_lead_detail_shows_angle_drafts_and_profile(client, session):
    lead = session.exec(select(Lead).where(Lead.company == "עסק בדיקה 01")).one()

    html = client.get(f"/leads/{lead.id}").text

    assert "זווית בדיקה 01" in html
    assert "פנייה ראשונה" in html
    assert "היי, ראיתי את המודעה של עסק בדיקה 01" in html
    assert "שתי מכירות בחודש מכסות את ההשקעה" in html
    assert "בעל פה בלבד" in html


def test_unknown_lead_is_404(client):
    assert client.get("/leads/99999").status_code == 404


def test_m0_has_no_write_or_send_routes(client):
    """M0 is read-only: every route answers GET/HEAD only."""
    for route in client.app.routes:
        if isinstance(route, APIRoute):
            assert route.methods <= {"GET", "HEAD"}, route.path
