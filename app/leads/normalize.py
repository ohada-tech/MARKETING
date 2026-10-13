"""Normalization for dedup keys and for parsing the existing CSV exports."""

import re
import unicodedata
from urllib.parse import urlparse

# A "website" on one of these hosts is a profile page, not the business's own domain.
# Deduping on it would merge unrelated businesses.
_SHARED_HOSTS = {
    "facebook.com",
    "m.facebook.com",
    "instagram.com",
    "linkedin.com",
    "linktr.ee",
    "wa.me",
    "api.whatsapp.com",
    "tiktok.com",
    "youtube.com",
    "google.com",
    "maps.google.com",
    "sites.google.com",
}

_COMPANY_SUFFIXES = {"בעמ", "ltd", "llc", "inc", "corp", "limited"}


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_domain(url: str | None) -> str | None:
    url = clean(url)
    if not url:
        return None
    candidate = url.lower()
    if "://" not in candidate:
        candidate = "http://" + candidate
    host = urlparse(candidate).hostname
    if not host or "." not in host:
        return None
    if host.startswith("www."):
        host = host[4:]
    if host in _SHARED_HOSTS:
        return None
    return host


def normalize_phone(phone: str | None) -> str | None:
    """Digits only, Israeli local numbers converted to 972 form. Placeholders return None."""
    phone = clean(phone)
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) in (9, 10):
        digits = "972" + digits[1:]
    if len(digits) < 7:
        return None
    if set(digits[-7:]) == {"0"}:  # "050-0000000" style placeholders
        return None
    return digits


def is_israeli_mobile(phone_norm: str | None) -> bool:
    return bool(phone_norm) and phone_norm.startswith("9725") and len(phone_norm) == 12


def normalize_company(name: str | None) -> str:
    name = clean(name)
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).lower()
    text = re.sub(r"\[[^\]]*\]", " ", text)  # "[דוגמה]" and similar tags
    text = re.sub("[\"'׳״]", "", text)  # quotes, geresh, gershayim: בע"מ -> בעמ
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t not in _COMPANY_SUFFIXES]
    return " ".join(tokens)


def normalize_email(email: str | None) -> str | None:
    email = clean(email)
    if not email or "@" not in email:
        return None
    return email.lower()


def is_placeholder(text: str | None) -> bool:
    """True for empty text or a bracketed stub like "[נכתב בזמן הריצה]"."""
    text = clean(text)
    return text is None or re.fullmatch(r"\[[^\[\]]*\]", text) is not None


_SUBJECT_RE = re.compile(r"^\s*(?:subject|נושא)\s*:\s*(.+?)\s*$", re.IGNORECASE)


def split_subject(body: str) -> tuple[str | None, str]:
    """Pull a leading "Subject:" / "נושא:" line out of an email draft."""
    lines = body.strip().splitlines()
    if lines:
        match = _SUBJECT_RE.match(lines[0])
        if match:
            return match.group(1), "\n".join(lines[1:]).strip()
    return None, body.strip()


def parse_int(value: str | None) -> int | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_bool(value: str | None) -> bool:
    return (clean(value) or "").lower() in ("yes", "true", "1", "כן", "y")


def parse_score_breakdown(notes: str | None) -> dict[str, int] | None:
    """Pull score components out of signal_notes.

    Understands the formats the client finder writes: "א'35 + ב'25 ...",
    "A=30 + B=20 ...", "spend 30 + gap 20 ...", and a "פחות 3" / "MINUS 15" penalty.
    """
    notes = clean(notes)
    if not notes:
        return None
    breakdown: dict[str, int] = {}
    for key, number in re.findall(r"(?<![א-ת])([א-ה])['׳](\d+)", notes):
        breakdown.setdefault(key, int(number))
    for key, number in re.findall(r"\b([A-E])\s*=\s*(\d+)", notes):
        breakdown.setdefault(key, int(number))
    for key, number in re.findall(r"\b(spend|gap|pay|reach|timing)\s+(\d+)", notes, flags=re.IGNORECASE):
        breakdown.setdefault(key.lower(), int(number))
    penalty = re.search(r"(?:פחות|MINUS)\s+(\d+)", notes, flags=re.IGNORECASE)
    if penalty:
        breakdown["penalty"] = -int(penalty.group(1))
    return breakdown or None
