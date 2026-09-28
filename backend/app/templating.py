"""M8: strict template rendering. Unknown or malformed variables fail at save time;
variables without a value fail at render time. Nothing ever renders blank.

Syntax: {{name}} or {{name | fallback}} (fallback used when the value is empty).
"""
import re

MY_VARIABLES = (
    "my_full_name", "my_first_name", "my_email", "my_phone", "my_location", "my_headline", "my_summary",
    "my_skills", "my_top_skills", "my_current_title", "my_current_company", "my_linkedin", "my_github",
    "my_portfolio", "my_target_role", "my_availability",
)
COMPANY_VARIABLES = ("company_name", "company_domain", "company_website", "company_city", "company_country",
                     "company_industry")
CONTACT_VARIABLES = ("contact_name", "contact_first_name", "contact_role", "contact_email")
VARIABLES = frozenset(MY_VARIABLES + COMPANY_VARIABLES + CONTACT_VARIABLES)

# {{ name }} or {{ name | fallback }}; fallback cannot contain braces or '|'.
TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]*)\s*(?:\|([^{}|]*))?\}\}")


class RenderError(ValueError):
    def __init__(self, unresolved: list[str]):
        self.unresolved = unresolved
        super().__init__("unresolved variables: " + ", ".join(unresolved))


def problems(text: str) -> list[str]:
    """Save-time check. Empty list means the text is valid."""
    found = []
    for m in TOKEN_RE.finditer(text):
        name, fallback = m.group(1), m.group(2)
        if not name:
            found.append(f"empty variable {m.group(0)}")
        elif name not in VARIABLES:
            found.append(f"unknown variable {{{{{name}}}}}")
        if fallback is not None and not fallback.strip():
            found.append(f"empty fallback in {m.group(0)}")
    leftover = TOKEN_RE.sub("", text)
    if "{{" in leftover or "}}" in leftover:
        found.append("malformed braces: every {{ needs a matching }} around one variable name")
    return found


def render(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Return (rendered text, unresolved variable names). Callers must treat any unresolved as failure."""
    unresolved = []

    def sub(m):
        name, fallback = m.group(1), m.group(2)
        value = (values.get(name) or "").strip()
        if value:
            return value
        if fallback is not None and fallback.strip():
            return fallback.strip()
        unresolved.append(name)
        return m.group(0)

    return TOKEN_RE.sub(sub, text), unresolved


def render_strict(subject: str, body: str, values: dict[str, str]) -> dict[str, str]:
    subject_out, u1 = render(subject, values)
    body_out, u2 = render(body, values)
    if u1 or u2:
        raise RenderError(sorted(set(u1 + u2)))
    # A variable (e.g. an imported company name) must never put a line break into the Subject header (M30).
    return {"subject": re.sub(r"\s*[\r\n]+\s*", " ", subject_out), "body": body_out}
