"""M8: strict rendering engine (pure functions)."""
import pytest

from app.templating import VARIABLES, RenderError, problems, render, render_strict

ALL = {v: f"<{v}>" for v in VARIABLES}


def test_exactly_26_variables():
    assert len(VARIABLES) == 26


@pytest.mark.parametrize("text", [
    "Hi {{contact_first_name | there}}, I'm {{my_full_name}}.",
    "{{ company_name }} in {{company_city}}",
    "No variables at all { single braces } are fine",
    "",
])
def test_valid_texts(text):
    assert problems(text) == []


@pytest.mark.parametrize("text,expected", [
    ("Hi {{compnay_name}}", "unknown variable {{compnay_name}}"),
    ("Hi {{Company_Name}}", "unknown variable {{Company_Name}}"),
    ("Hi {{}}", "empty variable {{}}"),
    ("Hi {{contact_first_name | }}", "empty fallback in {{contact_first_name | }}"),
    ("Hi {{company_name}", "malformed braces"),
    ("Hi {company_name}}", "malformed braces"),
    ("Hi {{company name}}", "malformed braces"),
    ("Hi {{company_name | a {b} }}", "malformed braces"),
])
def test_invalid_texts(text, expected):
    assert any(expected in p for p in problems(text)), problems(text)


def test_render_all_resolved():
    out, unresolved = render("Dear {{contact_name}} at {{company_name}}", {**ALL})
    assert (out, unresolved) == ("Dear <contact_name> at <company_name>", [])


def test_fallback_only_when_empty():
    assert render("Hi {{contact_first_name | there}}", {"contact_first_name": "Anna"})[0] == "Hi Anna"
    assert render("Hi {{contact_first_name | there}}", {"contact_first_name": ""})[0] == "Hi there"
    assert render("Hi {{contact_first_name|there}}", {"contact_first_name": "   "})[0] == "Hi there"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_empty_values_are_never_rendered_blank(value):
    vals = {**ALL, "company_city": value}
    with pytest.raises(RenderError) as e:
        render_strict("About {{company_name}}", "Your team in {{company_city}}", vals)
    assert e.value.unresolved == ["company_city"]


def test_missing_key_is_unresolved_and_all_are_listed():
    with pytest.raises(RenderError) as e:
        render_strict("{{company_name}} {{my_phone}}", "{{contact_role}} {{company_name}} {{my_phone}}", {})
    assert e.value.unresolved == ["company_name", "contact_role", "my_phone"]


def test_values_are_trimmed_and_not_reinterpreted():
    out = render_strict("{{company_name}}", "{{company_city}}", {**ALL, "company_name": "  Acme  ",
                                                                  "company_city": "{{my_phone}}"})
    assert out == {"subject": "Acme", "body": "{{my_phone}}"}  # values are inserted literally, never re-rendered
