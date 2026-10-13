"""Hebrew display labels for stored enum values."""

STATUS = {
    "new": "חדש",
    "researched": "נחקר",
    "drafted": "יש טיוטות",
    "awaiting_approval": "ממתין לאישור",
    "contacted": "נוצר קשר",
    "replied": "ענו",
    "call_booked": "נקבעה שיחה",
    "proposal_sent": "נשלחה הצעה",
    "won": "נסגר",
    "lost": "לא נסגר",
    "no_reply": "אין מענה",
    "archived": "בארכיון",
    "suppressed": "הוסר",
}

LEGAL_ROUTE = {
    "call": "שיחה",
    "dm": "הודעה פרטית",
    "group_reply": "תגובה בקבוצה",
    "consented_email": "מייל בהסכמה",
    "ad_disclosed": "מייל פרסומת",
}

SEGMENT = {
    "local_service": "עסק שירות מקומי",
    "dtc": "מותג ישיר לצרכן",
    "agency": "סוכנות",
    "real_estate": "נדל\"ן",
    "ecommerce": "איקומרס",
}

DRAFT_KIND = {
    "first_touch": "פנייה ראשונה",
    "followup_1": "פולואפ 1",
    "followup_2": "פולואפ 2",
    "reply": "תשובה",
    "offer": "הצעה",
    "call_script": "סקריפט שיחה",
}

CHANNEL = {
    "email": "מייל",
    "whatsapp": "וואטסאפ",
    "instagram_dm": "אינסטגרם",
    "call": "טלפון",
}

DRAFT_STATUS = {
    "pending": "ממתינה",
    "approved": "אושרה",
    "rejected": "נדחתה",
    "sent": "נשלחה",
    "failed": "נכשלה",
    "superseded": "הוחלפה",
}


def label(mapping: dict[str, str], value: str | None) -> str:
    if not value:
        return ""
    return mapping.get(value, value)
