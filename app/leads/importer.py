"""Import existing lead files from the il-client-finder skill (SPEC 5.1).

Accepts:
  - leads_YYYY-MM-DD.csv  (the il-client-finder schema; the US variant with "state" and a
                           single "first_touch" column is also understood)
  - profiles/NN.json      (deep profile per business, SPEC section 9)
  - suppression*.csv      (email,phone,company,reason,date_added)
  - a directory holding any of the above

Re-importing is safe: leads are matched by website domain, then phone, then normalized
company name. Existing lead fields are only filled when empty, so edits made in the app
are never overwritten. A suppressed lead is never touched again.
"""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import or_
from sqlmodel import Session, select

from app.audit import audit
from app.leads.normalize import (
    clean,
    is_israeli_mobile,
    is_placeholder,
    normalize_company,
    normalize_domain,
    normalize_email,
    normalize_phone,
    parse_bool,
    parse_int,
    parse_score_breakdown,
    split_subject,
)
from app.models import LEGAL_ROUTES, Contact, Draft, Lead, Profile, Suppression, utcnow

# CSV column -> Lead attribute. Values only fill empty fields on re-import.
_LEAD_FIELDS = {
    "segment": "segment",
    "city": "city",
    "region": "region",
    "state": "region",
    "website": "website",
    "instagram": "instagram",
    "facebook_page": "facebook_page",
    "evidence_type": "evidence_type",
    "evidence_url": "evidence_url",
    "signal_notes": "signal_notes",
    "offer_fit": "angle",
    "suggested_package": "suggested_package",
    "channel": "source_channel",
    "date_found": "date_found",
}

# CSV column -> (draft kind, fixed channel or None to infer)
_DRAFT_COLUMNS = (
    ("first_touch_wa", "first_touch", "whatsapp"),
    ("first_touch_email", "first_touch", "email"),
    ("first_touch", "first_touch", None),
    ("followup_1", "followup_1", None),
    ("followup_2", "followup_2", None),
)

_ROUTE_CHANNEL = {
    "consented_email": "email",
    "ad_disclosed": "email",
    "dm": "instagram_dm",
}

# Statuses the importer may still move forward. Anything later belongs to the workflow.
_EARLY_STATUSES = ("new", "researched")


@dataclass
class ImportReport:
    files: list[str] = field(default_factory=list)
    rows: int = 0
    leads_created: int = 0
    leads_matched: int = 0
    fields_filled: int = 0
    fields_kept: int = 0
    contacts_created: int = 0
    drafts_created: int = 0
    drafts_skipped: int = 0
    drafts_superseded: int = 0
    profiles_created: int = 0
    profiles_updated: int = 0
    profiles_skipped: int = 0
    profiles_unmatched: list[str] = field(default_factory=list)
    suppressions_added: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"קבצים: {len(self.files)}  שורות: {self.rows}",
            f"לידים חדשים: {self.leads_created}  לידים שכבר היו: {self.leads_matched}",
            f"שדות שהושלמו: {self.fields_filled}  שדות שנשמרו כמו שהם: {self.fields_kept}",
            f"אנשי קשר חדשים: {self.contacts_created}",
            f"טיוטות חדשות: {self.drafts_created}  דולגו: {self.drafts_skipped}  הוחלפו: {self.drafts_superseded}",
            f"פרופילים חדשים: {self.profiles_created}  עודכנו: {self.profiles_updated}  ללא שינוי: {self.profiles_skipped}",
            f"רשומות הסרה חדשות: {self.suppressions_added}",
        ]
        if self.profiles_unmatched:
            lines.append("פרופילים בלי ליד תואם: " + ", ".join(self.profiles_unmatched))
        lines.extend(f"אזהרה: {w}" for w in self.warnings)
        return "\n".join(lines)


# ---------------------------------------------------------------- entry points


def import_paths(session: Session, paths: Iterable[str | Path]) -> ImportReport:
    """Import every recognized file under the given files or directories, then commit."""
    report = ImportReport()
    lead_csvs: list[Path] = []
    profile_files: list[Path] = []
    suppression_csvs: list[Path] = []

    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.is_file())
        elif path.is_file():
            files = [path]
        else:
            report.warnings.append(f"לא נמצא: {path}")
            continue
        for file in files:
            name = file.name.lower()
            if name.endswith(".csv") and name.startswith("suppression"):
                suppression_csvs.append(file)
            elif name.endswith(".csv") and name.startswith("leads"):
                lead_csvs.append(file)
            elif name.endswith(".json") and (file.parent.name == "profiles" or file == path):
                profile_files.append(file)

    # Suppression first, so leads imported in the same run are already checked against it.
    for file in suppression_csvs:
        import_suppression_csv(session, file, report)

    row_leads: list[int | None] = []
    for file in lead_csvs:
        row_leads = import_leads_csv(session, file, report)

    # profiles/NN.json fall back to row NN of the CSV only when exactly one CSV was imported.
    fallback = row_leads if len(lead_csvs) == 1 else []
    for file in profile_files:
        import_profile_file(session, file, report, fallback)

    audit(
        session,
        "system",
        "import",
        "import",
        details={
            "files": report.files,
            "leads_created": report.leads_created,
            "leads_matched": report.leads_matched,
            "drafts_created": report.drafts_created,
            "profiles_created": report.profiles_created,
            "warnings": len(report.warnings),
        },
    )
    session.commit()
    return report


def import_leads_csv(session: Session, path: Path, report: ImportReport) -> list[int | None]:
    """Import one leads CSV. Returns the lead id for each data row (None for skipped rows)."""
    report.files.append(str(path))
    row_leads: list[int | None] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_no, raw_row in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): v for k, v in raw_row.items()}
            report.rows += 1
            lead = _import_row(session, row, path.name, line_no, report)
            row_leads.append(lead.id if lead else None)
    return row_leads


def import_suppression_csv(session: Session, path: Path, report: ImportReport) -> None:
    report.files.append(str(path))
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw_row in csv.DictReader(handle):
            row = {(k or "").strip().lower(): v for k, v in raw_row.items()}
            email = normalize_email(row.get("email"))
            phone = normalize_phone(row.get("phone"))
            company = normalize_company(row.get("company")) or None
            if not (email or phone or company):
                continue
            exists = session.exec(
                select(Suppression).where(
                    Suppression.email == email, Suppression.phone == phone, Suppression.company == company
                )
            ).first()
            if exists:
                continue
            entry = Suppression(email=email, phone=phone, company=company, reason=clean(row.get("reason")))
            session.add(entry)
            session.flush()
            audit(session, "system", "suppression_imported", "suppression", entry.id, {"file": path.name})
            report.suppressions_added += 1


def import_profile_file(
    session: Session, path: Path, report: ImportReport, row_leads: list[int | None] | None = None
) -> None:
    report.files.append(str(path))
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        report.warnings.append(f"{path.name}: JSON לא תקין ({exc})")
        return
    if not isinstance(data, dict):
        report.warnings.append(f"{path.name}: מבנה לא צפוי, דולג")
        return

    lead = _find_lead_for_profile(session, data, path, row_leads or [])
    if lead is None:
        report.profiles_unmatched.append(path.name)
        return
    if lead.status == "suppressed":
        report.profiles_skipped += 1
        return

    sources = _profile_sources(data)
    existing = session.exec(select(Profile).where(Profile.lead_id == lead.id)).first()
    if existing and existing.data == data:
        report.profiles_skipped += 1
        return
    if existing:
        existing.data = data
        existing.sources = sources
        existing.created_at = utcnow()
        session.add(existing)
        action = "profile_updated"
        report.profiles_updated += 1
        profile = existing
    else:
        profile = Profile(lead_id=lead.id, data=data, sources=sources, model="import")
        session.add(profile)
        action = "profile_imported"
        report.profiles_created += 1

    if lead.status == "new":
        lead.status = "researched"
        lead.updated_at = utcnow()
        session.add(lead)
    session.flush()
    audit(session, "system", action, "profile", profile.id, {"file": path.name, "lead_id": lead.id})


# ---------------------------------------------------------------- rows


def _import_row(session: Session, row: dict[str, Any], file_name: str, line_no: int, report: ImportReport) -> Lead | None:
    company = clean(row.get("company"))
    if not company:
        report.warnings.append(f"{file_name} שורה {line_no}: אין שם חברה, דולג")
        return None

    company_norm = normalize_company(company)
    domain = normalize_domain(row.get("website"))
    phones = [p for p in (normalize_phone(row.get("phone")), normalize_phone(row.get("whatsapp"))) if p]
    email = normalize_email(row.get("email"))

    legal_route = clean(row.get("legal_route"))
    if legal_route and legal_route not in LEGAL_ROUTES:
        report.warnings.append(f"{file_name} שורה {line_no}: legal_route לא מוכר '{legal_route}', נשאר ריק")
        legal_route = None

    lead = _find_lead(session, domain, phones, company_norm)
    if lead is None:
        lead = Lead(company=company, company_norm=company_norm, domain=domain, source_file=file_name)
        session.add(lead)
        session.flush()
        report.leads_created += 1
        audit(session, "system", "lead_imported", "lead", lead.id, {"file": file_name, "line": line_no})
    else:
        report.leads_matched += 1
        if lead.status == "suppressed":
            return lead

    values: dict[str, Any] = {attr: clean(row.get(col)) for col, attr in _LEAD_FIELDS.items() if col in row}
    values["score"] = parse_int(row.get("score"))
    values["score_breakdown"] = parse_score_breakdown(row.get("signal_notes"))
    values["legal_route"] = legal_route
    values["domain"] = domain
    _fill_empty(lead, values, report)

    contact = _upsert_contact(session, lead, row, phones, email, report)

    if _is_suppressed(session, company_norm, email, phones):
        lead.status = "suppressed"
        report.warnings.append(f"{company}: נמצא ברשימת ההסרה, סומן suppressed ולא יובאו טיוטות")
        audit(session, "system", "lead_suppressed_on_import", "lead", lead.id, {"file": file_name})
    else:
        created = _import_drafts(session, lead, contact, row, file_name, report)
        if created and lead.status in _EARLY_STATUSES:
            lead.status = "drafted"

    lead.updated_at = utcnow()
    session.add(lead)
    session.flush()
    return lead


def _find_lead(session: Session, domain: str | None, phones: list[str], company_norm: str) -> Lead | None:
    if domain:
        lead = session.exec(select(Lead).where(Lead.domain == domain)).first()
        if lead:
            return lead
    if phones:
        lead = session.exec(
            select(Lead)
            .join(Contact, Contact.lead_id == Lead.id)
            .where(or_(Contact.phone_norm.in_(phones), Contact.whatsapp_norm.in_(phones)))
        ).first()
        if lead:
            return lead
    if company_norm:
        return session.exec(select(Lead).where(Lead.company_norm == company_norm)).first()
    return None


def _fill_empty(obj: Any, values: dict[str, Any], report: ImportReport) -> None:
    for attr, value in values.items():
        if value in (None, "", {}):
            continue
        current = getattr(obj, attr)
        if current in (None, "", {}):
            setattr(obj, attr, value)
            report.fields_filled += 1
        elif current != value:
            report.fields_kept += 1


def _upsert_contact(
    session: Session, lead: Lead, row: dict[str, Any], phones: list[str], email: str | None, report: ImportReport
) -> Contact | None:
    name = clean(row.get("contact_name"))
    if name in ("—", "-", "–"):
        name = None
    phone_norm = normalize_phone(row.get("phone"))
    whatsapp_norm = normalize_phone(row.get("whatsapp"))
    if not (name or email or phone_norm or whatsapp_norm):
        return None

    conditions = []
    if email:
        conditions.append(Contact.email == email)
    if phones:
        conditions.append(Contact.phone_norm.in_(phones))
        conditions.append(Contact.whatsapp_norm.in_(phones))
    if name:
        conditions.append(Contact.name == name)
    contact = session.exec(select(Contact).where(Contact.lead_id == lead.id, or_(*conditions))).first()

    known = [p for p in (phone_norm, whatsapp_norm) if p]
    values = {
        "name": name,
        "role": clean(row.get("contact_title")),
        "email": email,
        "phone": clean(row.get("phone")) if phone_norm else None,
        "phone_norm": phone_norm,
        "whatsapp": clean(row.get("whatsapp")) if whatsapp_norm else None,
        "whatsapp_norm": whatsapp_norm,
    }
    if contact is None:
        contact = Contact(
            lead_id=lead.id,
            is_mobile_only=bool(known) and all(is_israeli_mobile(p) for p in known),
            needs_manual=parse_bool(row.get("needs_manual")),
            **values,
        )
        session.add(contact)
        session.flush()
        report.contacts_created += 1
    else:
        _fill_empty(contact, values, report)
        session.add(contact)
    return contact


def _is_suppressed(session: Session, company_norm: str, email: str | None, phones: list[str]) -> bool:
    conditions = []
    if company_norm:
        conditions.append(Suppression.company == company_norm)
    if email:
        conditions.append(Suppression.email == email)
    if phones:
        conditions.append(Suppression.phone.in_(phones))
    if not conditions:
        return False
    return session.exec(select(Suppression).where(or_(*conditions))).first() is not None


def _infer_channel(row: dict[str, Any], body: str, has_subject: bool) -> str:
    if has_subject:
        return "email"
    if not is_placeholder(row.get("first_touch_email")):
        return "email"
    if not is_placeholder(row.get("first_touch_wa")):
        return "whatsapp"
    route = clean(row.get("legal_route"))
    if route in _ROUTE_CHANNEL:
        return _ROUTE_CHANNEL[route]
    if normalize_email(row.get("email")):
        return "email"
    return "whatsapp"


def _import_drafts(
    session: Session, lead: Lead, contact: Contact | None, row: dict[str, Any], file_name: str, report: ImportReport
) -> int:
    created = 0
    for column, kind, fixed_channel in _DRAFT_COLUMNS:
        text = row.get(column)
        if is_placeholder(text):
            continue
        subject, body = split_subject(text)
        channel = fixed_channel or _infer_channel(row, body, subject is not None)
        if channel != "email" and subject:
            body = text.strip()
            subject = None

        existing = session.exec(
            select(Draft).where(Draft.lead_id == lead.id, Draft.kind == kind, Draft.channel == channel)
        ).all()
        if any(d.body == body and d.subject == subject for d in existing):
            report.drafts_skipped += 1
            continue
        replaceable = [d for d in existing if d.status == "pending" and (d.source or "").startswith("import:")]
        blocking = [d for d in existing if d not in replaceable and d.status != "superseded"]
        if blocking:
            report.drafts_skipped += 1
            report.warnings.append(
                f"{lead.company}: טיוטת {kind}/{channel} חדשה בקובץ, אבל כבר קיימת טיוטה בטיפול. לא יובאה"
            )
            continue
        for old in replaceable:
            old.status = "superseded"
            old.updated_at = utcnow()
            session.add(old)
            report.drafts_superseded += 1

        draft = Draft(
            lead_id=lead.id,
            contact_id=contact.id if contact else None,
            kind=kind,
            channel=channel,
            subject=subject,
            body=body,
            generated_by="human",
            status="pending",
            source=f"import:{file_name}",
        )
        session.add(draft)
        session.flush()
        audit(session, "system", "draft_imported", "draft", draft.id, {"file": file_name, "lead_id": lead.id})
        report.drafts_created += 1
        created += 1
    return created


# ---------------------------------------------------------------- profiles


def _find_lead_for_profile(session: Session, data: dict[str, Any], path: Path, row_leads: list[int | None]) -> Lead | None:
    company_norm = normalize_company(data.get("company"))
    if company_norm:
        lead = session.exec(select(Lead).where(Lead.company_norm == company_norm)).first()
        if lead:
            return lead
    site = data.get("site_audit") if isinstance(data.get("site_audit"), dict) else {}
    domain = normalize_domain(site.get("url"))
    if domain:
        lead = session.exec(select(Lead).where(Lead.domain == domain)).first()
        if lead:
            return lead
    number = re.match(r"(\d+)", path.stem)
    if number and row_leads:
        index = int(number.group(1)) - 1
        if 0 <= index < len(row_leads) and row_leads[index] is not None:
            return session.get(Lead, row_leads[index])
    return None


def _profile_sources(data: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and value.startswith(("http://", "https://")) and value not in found:
            found.append(value)

    walk(data)
    return found


def main(argv: list[str] | None = None) -> None:
    import argparse

    from app.db import get_engine, init_db

    parser = argparse.ArgumentParser(description="ייבוא לידים, פרופילים ורשימת הסרה")
    parser.add_argument("paths", nargs="+", help="קבצי CSV/JSON או תיקיות")
    args = parser.parse_args(argv)

    engine = get_engine()
    init_db(engine)
    with Session(engine) as session:
        report = import_paths(session, args.paths)
    print(report.summary())


if __name__ == "__main__":
    main()
