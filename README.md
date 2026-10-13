# outreach-agent

כלי פנייה ללקוחות עם אישור אנושי על כל הודעה. המפרט המלא: [SPEC.md](SPEC.md).

**מצב נוכחי: אבן דרך M0.** שלד, מסד נתונים, ייבוא הקבצים הקיימים ומסך לידים לקריאה בלבד.
אין בקוד שום דרך לשלוח הודעה.

## הפעלה

```bash
pip install -r requirements.txt
cp .env.example .env

# ייבוא: תיקייה עם leads_*.csv, profiles/NN.json ו-suppression.csv (אם יש)
python -m app.cli import ~/path/to/il-client-finder-output

# הממשק, על 127.0.0.1 בלבד
python -m app.cli serve
# http://127.0.0.1:8000/leads
```

ייבוא חוזר בטוח: לידים מזוהים לפי דומיין, אחר כך טלפון, אחר כך שם חברה מנורמל.
שדות קיימים לא נדרסים, וליד שהוסר (suppressed) לא משתנה יותר.

## בדיקות

```bash
python -m pytest -q
```

הנתונים (`data/`), `.env` וטוקנים לא נכנסים ל-git. קבצי הלידים כוללים מידע אישי.
