"""M30 repository checks (stdlib only). Run from the repo root: python .github/scripts/security_checks.py

1. No secrets in tracked files (API keys, Fernet keys, private keys, tokens) and no tracked .env / backups.
2. Localhost binding: only `web` publishes a port, and only on 127.0.0.1.
3. No raw-HTML rendering in the frontend.
4. The security headers are configured for every page.
5. No browser pop-ups (window.confirm / prompt / alert) in the frontend: in-app dialogs only (F1).
"""
import re
import subprocess
import sys
from pathlib import Path

SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "Google API key (new format)": re.compile(r"AQ\.Ab8[0-9A-Za-z_-]{20,}"),
    "Fernet key": re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}=(?![A-Za-z0-9_=-])"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    "Gmail app password": re.compile(r"(?i)app_?password\s*[=:]\s*['\"]?[a-z]{4} ?[a-z]{4} ?[a-z]{4} ?[a-z]{4}\b"),
}
FORBIDDEN_FILES = re.compile(r"(^|/)(\.env(\.(?!example$)[^/]+)?|[^/]+\.dump|backups/.*)$")
HEADERS = ("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy")


def self_test():
    """The scanner must catch fake-but-realistic samples and ignore the templates."""
    fake = {"Google API key": "AIza" + "x" * 35, "Fernet key": "k=" + "A" * 43 + "=",
            "private key": "-----BEGIN RSA PRIVATE KEY-----", "Gmail app password": "APP_PASSWORD=abcd efgh ijkl mnop"}
    for name, sample in fake.items():
        assert SECRET_PATTERNS[name].search(sample), name
    assert FORBIDDEN_FILES.search(".env") and FORBIDDEN_FILES.search("backend/.env.local")
    assert FORBIDDEN_FILES.search("backups/crm-1.dump") and not FORBIDDEN_FILES.search(".env.example")


def tracked() -> list[str]:
    return subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()


def check_secrets(files) -> list[str]:
    problems = [f"forbidden tracked file: {f}" for f in files if FORBIDDEN_FILES.search(f)]
    for f in files:
        p = Path(f)
        if not p.is_file() or p.suffix in (".png", ".jpg", ".pdf", ".ico", ".woff", ".woff2"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for name, rx in SECRET_PATTERNS.items():
            if f.endswith("security_checks.py"):
                continue
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"possible {name} in {f}:{line}")
    return problems


def check_ports(compose: str) -> list[str]:
    problems, service, in_services, in_ports = [], None, False, False
    for line in compose.splitlines():
        if re.match(r"^\S", line):
            in_services, in_ports = line.startswith("services:"), False
            continue
        if in_services and (m := re.match(r"^  ([A-Za-z0-9_-]+):", line)):
            service, in_ports = m.group(1), False
            continue
        if in_services and re.match(r"^    ports:", line):
            in_ports = True
            continue
        if in_ports and (m := re.match(r'^      - "?([^"#]+)"?', line)):
            port = m.group(1).strip()
            if service != "web" or not port.startswith("127.0.0.1:"):
                problems.append(f"service {service} publishes {port} (only web on 127.0.0.1 is allowed)")
        elif in_ports and re.match(r"^    \S", line):
            in_ports = False
    return problems


def main() -> int:
    self_test()
    files = tracked()
    problems = check_secrets(files)
    problems += check_ports(Path("docker-compose.yml").read_text(encoding="utf-8"))
    problems += [f"raw HTML rendering in {f}" for f in files
                 if f.startswith("frontend/app/") and f.endswith((".js", ".jsx"))
                 and "dangerouslySetInnerHTML" in Path(f).read_text(encoding="utf-8")]
    problems += [f"browser pop-up in {f} (use the in-app dialog from app/ui)" for f in files
                 if f.startswith("frontend/app/") and f.endswith((".js", ".jsx"))
                 and re.search(r"\bwindow\.(confirm|prompt|alert)\s*\(|(?<![.\w])(confirm|prompt|alert)\s*\(\s*[`'\"]",
                               Path(f).read_text(encoding="utf-8"))]
    config = Path("frontend/next.config.mjs").read_text(encoding="utf-8")
    problems += [f"security header {h} not configured" for h in HEADERS if h not in config]
    for p in problems:
        print("FAIL", p)
    print(f"security checks: {'FAILED' if problems else 'all green'} ({len(files)} tracked files scanned)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
