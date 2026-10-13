import json

from sqlmodel import func, select

from app.leads.importer import import_paths
from app.models import AuditEvent, Contact, Draft, Lead, Profile, Suppression
from tests.conftest import lead_row, profile_data, write_csv


def count(session, model):
    return session.exec(select(func.count(model.id))).one()


def lead_by_company(session, company):
    return session.exec(select(Lead).where(Lead.company == company)).one()


# ---------------------------------------------------------------- M0 acceptance


def test_imports_all_32_leads_with_angle_and_drafts(session, leads_dir):
    report = import_paths(session, [leads_dir])

    assert report.leads_created == 32
    assert count(session, Lead) == 32
    lead = lead_by_company(session, "עסק בדיקה 07")
    assert lead.angle == "זווית בדיקה 07: נפח קריאייטיב לקמפיין שכבר רץ"
    assert lead.score == 88
    assert lead.status == "drafted"

    drafts = session.exec(select(Draft)).all()
    assert len(drafts) == 48  # 24 leads with real drafts, 2 each
    assert {d.generated_by for d in drafts} == {"human"}
    assert {d.status for d in drafts} == {"pending"}


def test_reimport_creates_no_duplicates(session, leads_dir):
    import_paths(session, [leads_dir])
    before = {m.__name__: count(session, m) for m in (Lead, Contact, Draft, Profile)}

    report = import_paths(session, [leads_dir])

    after = {m.__name__: count(session, m) for m in (Lead, Contact, Draft, Profile)}
    assert after == before
    assert report.leads_created == 0
    assert report.leads_matched == 32
    assert report.drafts_created == 0
    assert report.contacts_created == 0
    assert report.profiles_created == 0


# ---------------------------------------------------------------- dedup order


def test_dedup_by_domain_ignores_scheme_www_and_path(session, tmp_path):
    write_csv(tmp_path / "leads_a.csv", [lead_row(1, website="https://www.shop-x.co.il/about", phone="")])
    write_csv(tmp_path / "leads_b.csv", [lead_row(2, company="שם אחר לגמרי", website="shop-x.co.il", phone="")])

    import_paths(session, [tmp_path / "leads_a.csv", tmp_path / "leads_b.csv"])

    assert count(session, Lead) == 1


def test_dedup_by_phone_across_formats(session, tmp_path):
    write_csv(tmp_path / "leads_a.csv", [lead_row(1, website="", phone="050-1234567")])
    write_csv(tmp_path / "leads_b.csv", [lead_row(2, company="שם אחר", website="", phone="+972 50 123 4567")])

    import_paths(session, [tmp_path / "leads_a.csv", tmp_path / "leads_b.csv"])

    assert count(session, Lead) == 1


def test_dedup_by_normalized_company_name(session, tmp_path):
    write_csv(tmp_path / "leads_a.csv", [lead_row(1, company='קפה הגפן בע"מ', website="", phone="")])
    write_csv(tmp_path / "leads_b.csv", [lead_row(2, company="  קפה   הגפן ", website="", phone="")])

    import_paths(session, [tmp_path / "leads_a.csv", tmp_path / "leads_b.csv"])

    assert count(session, Lead) == 1


def test_social_profile_url_is_not_a_dedup_key(session, tmp_path):
    rows = [
        lead_row(1, website="https://facebook.com/pageA", phone=""),
        lead_row(2, website="https://facebook.com/pageB", phone=""),
    ]
    write_csv(tmp_path / "leads.csv", rows)

    import_paths(session, [tmp_path / "leads.csv"])

    assert count(session, Lead) == 2


def test_placeholder_phone_is_not_a_dedup_key(session, tmp_path):
    rows = [lead_row(1, website="", phone="050-0000000"), lead_row(2, website="", phone="050-0000000")]
    write_csv(tmp_path / "leads.csv", rows)

    import_paths(session, [tmp_path / "leads.csv"])

    assert count(session, Lead) == 2


# ---------------------------------------------------------------- drafts


def test_placeholder_drafts_are_not_imported(session, tmp_path):
    write_csv(tmp_path / "leads.csv", [lead_row(4)])  # i % 4 == 0: placeholder only

    import_paths(session, [tmp_path / "leads.csv"])

    assert count(session, Draft) == 0
    assert lead_by_company(session, "עסק בדיקה 04").status == "new"


def test_email_draft_subject_is_split_out(session, tmp_path):
    write_csv(tmp_path / "leads.csv", [lead_row(3)])  # route consented_email

    import_paths(session, [tmp_path / "leads.csv"])

    draft = session.exec(select(Draft).where(Draft.kind == "first_touch")).one()
    assert draft.channel == "email"
    assert draft.subject == "שאלה קצרה"
    assert draft.body.startswith("היי")
    followup = session.exec(select(Draft).where(Draft.kind == "followup_1")).one()
    assert followup.channel == "email"


def test_changed_draft_supersedes_untouched_imported_draft(session, tmp_path):
    write_csv(tmp_path / "leads_a.csv", [lead_row(1)])
    import_paths(session, [tmp_path / "leads_a.csv"])

    write_csv(tmp_path / "leads_b.csv", [lead_row(1, followup_1="נוסח חדש לפולואפ")])
    report = import_paths(session, [tmp_path / "leads_b.csv"])

    followups = session.exec(select(Draft).where(Draft.kind == "followup_1").order_by(Draft.id)).all()
    assert [d.status for d in followups] == ["superseded", "pending"]
    assert followups[1].body == "נוסח חדש לפולואפ"
    assert report.drafts_superseded == 1


def test_changed_draft_does_not_replace_one_already_in_progress(session, tmp_path):
    write_csv(tmp_path / "leads_a.csv", [lead_row(1)])
    import_paths(session, [tmp_path / "leads_a.csv"])
    draft = session.exec(select(Draft).where(Draft.kind == "followup_1")).one()
    draft.status = "approved"
    session.add(draft)
    session.commit()

    write_csv(tmp_path / "leads_b.csv", [lead_row(1, followup_1="נוסח חדש")])
    report = import_paths(session, [tmp_path / "leads_b.csv"])

    followups = session.exec(select(Draft).where(Draft.kind == "followup_1")).all()
    assert len(followups) == 1 and followups[0].status == "approved"
    assert report.warnings


# ---------------------------------------------------------------- fields


def test_reimport_fills_empty_fields_but_never_overwrites(session, tmp_path):
    write_csv(tmp_path / "leads_a.csv", [lead_row(1, city="")])
    import_paths(session, [tmp_path / "leads_a.csv"])
    lead = lead_by_company(session, "עסק בדיקה 01")
    lead.angle = "זווית שאוהד ערך"
    session.add(lead)
    session.commit()

    write_csv(tmp_path / "leads_b.csv", [lead_row(1, city="חיפה", offer_fit="זווית אחרת מהקובץ")])
    report = import_paths(session, [tmp_path / "leads_b.csv"])

    session.refresh(lead)
    assert lead.city == "חיפה"
    assert lead.angle == "זווית שאוהד ערך"
    assert report.fields_kept >= 1


def test_unknown_legal_route_is_left_empty_with_warning(session, tmp_path):
    write_csv(tmp_path / "leads.csv", [lead_row(1, legal_route="spam_everyone")])

    report = import_paths(session, [tmp_path / "leads.csv"])

    assert lead_by_company(session, "עסק בדיקה 01").legal_route is None
    assert any("legal_route" in w for w in report.warnings)


def test_score_breakdown_parsed_from_signal_notes(session, tmp_path):
    write_csv(tmp_path / "leads.csv", [lead_row(1)])

    import_paths(session, [tmp_path / "leads.csv"])

    assert lead_by_company(session, "עסק בדיקה 01").score_breakdown == {"א": 30, "ב": 20, "ג": 1, "ד": 10, "ה": 5}


def test_contact_flags(session, tmp_path):
    write_csv(tmp_path / "leads.csv", [lead_row(1)])

    import_paths(session, [tmp_path / "leads.csv"])

    contact = session.exec(select(Contact)).one()
    assert contact.phone_norm == "972521000001"
    assert contact.is_mobile_only is True
    assert contact.needs_manual is True


def test_us_schema_variant(session, tmp_path):
    columns = [
        "score", "company", "segment", "city", "state", "website", "instagram", "contact_name",
        "contact_title", "email", "phone", "evidence_type", "evidence_url", "signal_notes", "offer_fit",
        "suggested_package", "first_touch", "followup_1", "followup_2", "channel", "needs_manual", "date_found",
    ]
    row = {
        "score": "85", "company": "Example Agency", "segment": "agency", "city": "Austin", "state": "TX",
        "website": "https://example-agency.com", "email": "hello@example-agency.com",
        "signal_notes": "SCORE: A=30 + B=20 + C=18 + D=7 + E=10 = 85.", "offer_fit": "Overflow editing.",
        "first_touch": "Subject: overflow editing\n\nSaw the role you posted.",
        "followup_1": "Following up.", "channel": "glassdoor", "needs_manual": "no",
    }
    write_csv(tmp_path / "leads_us.csv", [row], columns)

    import_paths(session, [tmp_path / "leads_us.csv"])

    lead = lead_by_company(session, "Example Agency")
    assert lead.region == "TX"
    assert lead.angle == "Overflow editing."
    assert lead.source_channel == "glassdoor"
    assert lead.score_breakdown == {"A": 30, "B": 20, "C": 18, "D": 7, "E": 10}
    first = session.exec(select(Draft).where(Draft.kind == "first_touch")).one()
    assert (first.channel, first.subject, first.body) == ("email", "overflow editing", "Saw the role you posted.")


# ---------------------------------------------------------------- profiles


def test_profiles_matched_by_company_and_domain(session, leads_dir):
    import_paths(session, [leads_dir])

    assert count(session, Profile) == 2
    lead2 = lead_by_company(session, "עסק בדיקה 02")
    profile = session.exec(select(Profile).where(Profile.lead_id == lead2.id)).one()
    assert profile.data["roi"]["one_liner"] == "שתי מכירות בחודש מכסות את ההשקעה"
    assert "https://example.com/prices" in profile.sources


def test_profile_moves_new_lead_to_researched(session, tmp_path):
    folder = tmp_path / "run"
    write_csv(folder / "leads.csv", [lead_row(4)])  # no drafts, status new
    (folder / "profiles").mkdir()
    (folder / "profiles" / "01.json").write_text(json.dumps(profile_data("עסק בדיקה 04")), encoding="utf-8")

    import_paths(session, [folder])

    assert lead_by_company(session, "עסק בדיקה 04").status == "researched"


def test_profile_falls_back_to_row_number(session, tmp_path):
    folder = tmp_path / "run"
    write_csv(folder / "leads.csv", [lead_row(1), lead_row(2)])
    (folder / "profiles").mkdir()
    (folder / "profiles" / "02.json").write_text(json.dumps(profile_data("שם שלא מופיע ב-CSV")), encoding="utf-8")

    import_paths(session, [folder])

    profile = session.exec(select(Profile)).one()
    assert profile.lead_id == lead_by_company(session, "עסק בדיקה 02").id


def test_unmatched_profile_is_reported(session, tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "07.json").write_text(json.dumps(profile_data("לא קיים")), encoding="utf-8")

    report = import_paths(session, [profiles])

    assert report.profiles_unmatched == ["07.json"]
    assert count(session, Profile) == 0


def test_changed_profile_updates_in_place(session, leads_dir):
    import_paths(session, [leads_dir])
    path = leads_dir / "profiles" / "01.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["ads"] = "5 מודעות פעילות"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    report = import_paths(session, [leads_dir])

    assert report.profiles_updated == 1
    assert count(session, Profile) == 2


# ---------------------------------------------------------------- suppression and audit


def test_suppression_list_blocks_drafts_on_import(session, tmp_path):
    folder = tmp_path / "run"
    write_csv(folder / "leads.csv", [lead_row(1), lead_row(2)])
    (folder / "suppression.csv").write_text(
        "email,phone,company,reason,date_added\n,052-1000001,,ביקש הסרה,2026-09-01\n", encoding="utf-8"
    )

    import_paths(session, [folder])

    suppressed = lead_by_company(session, "עסק בדיקה 01")
    assert suppressed.status == "suppressed"
    assert session.exec(select(Draft).where(Draft.lead_id == suppressed.id)).all() == []
    assert lead_by_company(session, "עסק בדיקה 02").status == "drafted"
    assert count(session, Suppression) == 1


def test_suppressed_lead_is_never_touched_again(session, tmp_path):
    write_csv(tmp_path / "leads.csv", [lead_row(1, city="")])
    import_paths(session, [tmp_path / "leads.csv"])
    lead = lead_by_company(session, "עסק בדיקה 01")
    lead.status = "suppressed"
    session.add(lead)
    session.commit()
    drafts_before = count(session, Draft)

    write_csv(tmp_path / "leads_b.csv", [lead_row(1, city="חיפה", followup_2="עוד הודעה")])
    import_paths(session, [tmp_path / "leads_b.csv"])

    session.refresh(lead)
    assert lead.status == "suppressed"
    assert lead.city is None
    assert count(session, Draft) == drafts_before


def test_import_writes_audit_events(session, leads_dir):
    import_paths(session, [leads_dir])

    actions = session.exec(select(AuditEvent.action)).all()
    assert actions.count("lead_imported") == 32
    assert actions.count("draft_imported") == 48
    assert actions.count("profile_imported") == 2
    assert actions.count("import") == 1
