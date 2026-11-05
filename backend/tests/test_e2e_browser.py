"""Browser end-to-end tests: the built frontend + the real API + the warehouse, driven by
Playwright through Microsoft Edge or Chrome (installed browsers; nothing is downloaded).

Opt-in (starts two servers and a browser):
    npm --prefix frontend run build
    RUN_E2E=1 uv run --all-groups pytest -m e2e backend/tests/test_e2e_browser.py

The API runs against the isolated test_app_* schema from conftest (users created here), on
:8000 because `vite preview` proxies /api there (vite.config.ts).
"""

import contextlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import sqlalchemy as sa

pytestmark = [
    pytest.mark.db,
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("RUN_E2E") != "1", reason="set RUN_E2E=1"),
]
REPO = Path(__file__).resolve().parents[2]
WEB = "http://127.0.0.1:4173"


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait(url: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"{url} did not come up within {seconds}s")


@pytest.fixture(scope="module")
def servers(app_schema, tmp_path_factory):
    """API (uvicorn) + built frontend (vite preview), both inheriting APP_SCHEMA."""
    node = shutil.which("node")
    if node is None or not (REPO / "frontend" / "dist" / "index.html").is_file():
        pytest.skip("needs node and a built frontend (npm --prefix frontend run build)")
    for port in (8000, 4173):
        if not _port_free(port):
            pytest.skip(f"port {port} is in use (stop the dev servers first)")
    logs = tmp_path_factory.mktemp("e2e-logs")
    commands = [
        (
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            REPO,
            "api.log",
        ),
        (
            [
                node,
                "node_modules/vite/bin/vite.js",
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                "4173",
                "--strictPort",
            ],
            REPO / "frontend",
            "web.log",
        ),
    ]
    with contextlib.ExitStack() as stack:
        procs = []
        for cmd, cwd, log in commands:
            out = stack.enter_context((logs / log).open("wb"))
            procs.append(subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT))
        try:
            _wait("http://127.0.0.1:8000/api/health")
            _wait(WEB)
            yield logs
        finally:
            for p in procs:
                p.terminate()
            for p in procs:
                p.wait(timeout=20)


@pytest.fixture(scope="module")
def browser(servers):
    sync_api = pytest.importorskip("playwright.sync_api", reason="uv sync --group e2e")
    with sync_api.sync_playwright() as pw:
        last_error = None
        for channel in ("msedge", "chrome"):
            try:
                b = pw.chromium.launch(channel=channel, headless=True)
                break
            except Exception as exc:  # browser channel not installed
                last_error = exc
        else:
            pytest.skip(f"no installed Edge/Chrome for Playwright: {last_error}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
    pg = context.new_page()
    pg.console_errors = []
    pg.on("console", lambda m: m.type == "error" and pg.console_errors.append(m.text))
    pg.on("pageerror", lambda e: pg.console_errors.append(str(e)))
    yield pg
    context.close()


def login(page, user) -> None:
    page.goto(f"{WEB}/login")
    page.get_by_label("Email").fill(user["email"])
    page.get_by_label("Password").fill(user["password"])
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("button", name="Log out").wait_for()


def test_viewer_sees_dashboard_values_from_the_warehouse(page, make_user, warehouse):
    gmv = warehouse.execute(sa.text("select gmv from marts.kpi_overview")).scalar_one()
    login(page, make_user("viewer"))
    # Intl en-US BRL with no decimals, exactly as lib/format.ts renders it.
    expected = f"R${round(float(gmv)):,}"
    page.get_by_text(expected, exact=True).first.wait_for()

    page.goto(f"{WEB}/customers")
    page.get_by_text("requires the").wait_for()  # RoleGate, no customer rows
    assert page.locator("table").count() == 0
    assert page.console_errors == [], page.console_errors


def test_session_survives_reload_and_logout_ends_it(page, make_user):
    login(page, make_user("viewer"))
    page.reload()  # access token is in memory only; the refresh token restores the session
    page.get_by_role("button", name="Log out").wait_for()
    page.get_by_role("button", name="Log out").click()
    page.wait_for_url(f"{WEB}/login")
    page.goto(f"{WEB}/")
    page.wait_for_url(f"{WEB}/login")  # protected route redirects
    # A 401 during startup/logout is expected network noise; JS errors are not.
    js_errors = [e for e in page.console_errors if "401" not in e]
    assert js_errors == [], js_errors


def test_transient_refresh_failure_does_not_end_the_session(page, make_user):
    """A 429 on /auth/refresh (rate limit) must not discard the still-valid refresh token."""
    login(page, make_user("viewer"))

    def rate_limited(route):
        route.fulfill(status=429, content_type="application/json", body='{"code":"x"}')

    page.route("**/api/auth/refresh", rate_limited)
    page.reload()
    page.wait_for_url(f"{WEB}/login")  # no session for now
    page.unroute("**/api/auth/refresh")
    page.goto(f"{WEB}/")
    page.get_by_role("button", name="Log out").wait_for()  # restored with the kept token
    js_errors = [e for e in page.console_errors if "429" not in e and "401" not in e]
    assert js_errors == [], js_errors


def test_analyst_opens_customer_360(page, make_user):
    login(page, make_user("analyst"))
    page.goto(f"{WEB}/customers")
    first = page.locator("table a[href^='/customers/']").first
    first.wait_for()
    href = first.get_attribute("href")
    first.click()
    customer_id = href.rsplit("/", 1)[1]
    page.get_by_text(customer_id, exact=True).wait_for()
    assert page.console_errors == [], page.console_errors


def test_assistant_tools_only_mode_runs_a_tool(page, make_user, monkeypatch):
    if os.environ.get("ANTHROPIC_API_KEY") or _env_file_has_key():
        pytest.skip("an LLM key is configured; this test covers tools-only mode")
    login(page, make_user("viewer"))
    page.goto(f"{WEB}/assistant")
    page.get_by_text("not configured").wait_for()
    card = page.locator("section", has=page.locator("code", has_text="get_kpi_overview")).first
    card.get_by_role("button", name="Run").click()
    card.locator("pre").wait_for()
    assert '"gmv"' in card.locator("pre").inner_text()
    assert page.console_errors == [], page.console_errors


def _env_file_has_key() -> bool:
    env = REPO / ".env"
    if not env.is_file():
        return False
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return bool(line.split("=", 1)[1].strip())
    return False
