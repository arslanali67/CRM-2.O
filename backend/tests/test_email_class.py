import pytest

from app.email_class import classify_email


@pytest.mark.parametrize("email,expected", [
    # careers
    ("jobs@acme.de", "careers"),
    ("Careers@Acme.de", "careers"),
    ("karriere@firma.de", "careers"),
    ("bewerbung@firma.de", "careers"),
    ("hr@acme.com", "careers"),
    ("hr-team@acme.com", "careers"),
    ("recruiting.berlin@acme.com", "careers"),
    ("talent@acme.io", "careers"),
    ("personal@firma.de", "careers"),  # German: HR department
    ("jobs+ml@acme.de", "careers"),
    # generic
    ("info@acme.de", "generic"),
    ("kontakt@firma.de", "generic"),
    ("hello@startup.io", "generic"),
    ("office@acme.at", "generic"),
    ("info.de@acme.com", "generic"),
    # unsuitable
    ("noreply@acme.de", "unsuitable"),
    ("no-reply@acme.de", "unsuitable"),
    ("do_not_reply@acme.de", "unsuitable"),
    ("datenschutz@firma.de", "unsuitable"),
    ("privacy@acme.com", "unsuitable"),
    ("presse@firma.de", "unsuitable"),
    ("rechnung@firma.de", "unsuitable"),
    ("newsletter@acme.com", "unsuitable"),
    ("not-an-email", "unsuitable"),
    ("two@@ats.de", "unsuitable"),
    ("", "unsuitable"),
    # unsuitable wins over careers when both appear
    ("jobs-noreply@acme.de", "unsuitable"),
    # personal
    ("anna.schmidt@acme.de", "personal"),
    ("j.doe@acme.com", "personal"),
    ("max@startup.io", "personal"),
])
def test_classify_email(email, expected):
    assert classify_email(email) == expected
