"""Rule-based email classification (M5). No AI.

Looks at the local part (before @): each token split on . _ - and the whole part with
separators removed. Priority: unsuitable > careers > generic > personal.
German role names are included because the first leads are Berlin companies.
"""
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

UNSUITABLE = {
    "noreply", "donotreply", "nichtantworten", "mailerdaemon", "postmaster", "hostmaster", "webmaster",
    "abuse", "privacy", "datenschutz", "dsb", "dpo", "gdpr", "dsgvo", "billing", "invoice", "invoices",
    "rechnung", "rechnungen", "accounting", "buchhaltung", "press", "presse", "media", "legal", "recht",
    "compliance", "security", "newsletter", "unsubscribe", "bounce", "bounces", "root", "admin",
}
CAREERS = {
    "jobs", "job", "careers", "career", "karriere", "bewerbung", "bewerbungen", "hr", "humanresources",
    "recruiting", "recruitment", "recruiter", "talent", "talents", "hiring", "personal",
    "personalabteilung", "people", "joinus",
}
GENERIC = {
    "info", "information", "contact", "kontakt", "hello", "hallo", "hi", "hey", "office", "buero",
    "team", "mail", "email", "support", "service", "sales", "vertrieb", "marketing", "enquiries",
    "inquiries", "anfrage", "anfragen", "general", "welcome", "post", "business", "partner", "partners",
}


def classify_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        return "unsuitable"
    local = email.split("@", 1)[0].split("+", 1)[0]
    words = set(re.split(r"[._-]+", local)) | {re.sub(r"[._-]+", "", local)}
    for cls, names in (("unsuitable", UNSUITABLE), ("careers", CAREERS), ("generic", GENERIC)):
        if words & names:
            return cls
    return "personal"
