"""Capture docs/screenshots/*.png from the running app (real API, real warehouse data).

Start the API and the built frontend first, then run with an account that can see every page
(admin), passed through the environment so it never appears on the command line:

    uv run --all-groups uvicorn app.main:app --app-dir backend
    npm --prefix frontend run build && npm --prefix frontend run preview   # :4173
    SCREENSHOT_EMAIL=... SCREENSHOT_PASSWORD=... \
        uv run --all-groups python backend/scripts/capture_screenshots.py

Uses an installed Edge or Chrome through Playwright (`uv sync --group e2e`).
"""

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "screenshots"
PAGES = [
    ("executive", "/"),
    ("sales", "/sales"),
    ("forecast", "/forecast"),
    ("anomalies", "/anomalies"),
    ("segments", "/segments"),
    ("customers", "/customers"),
    ("churn", "/churn"),
    ("clv", "/clv"),
    ("recommendations", "/recommendations"),
    ("assistant", "/assistant"),
    ("models", "/models"),
    ("data-quality", "/data-quality"),
]


NAVIGATE = "p => { history.pushState({}, '', p); dispatchEvent(new PopStateEvent('popstate')); }"


def settle(page) -> None:
    page.wait_for_timeout(300)  # let the route start its requests
    page.wait_for_load_state("networkidle")
    # The <Loading> skeleton (components/ui.tsx) stays until every query on the page resolved.
    page.wait_for_function("() => !document.querySelector('.animate-pulse')", timeout=60_000)
    page.mouse.move(0, 0)  # no hover tooltip in the picture
    page.wait_for_timeout(700)  # chart transitions


def launch(pw):
    for channel in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(channel=channel, headless=True)
        except Exception:  # channel not installed
            continue
    sys.exit("no installed Edge or Chrome found")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:4173")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--width", type=int, default=1440)
    args = parser.parse_args()
    email, password = os.environ.get("SCREENSHOT_EMAIL"), os.environ.get("SCREENSHOT_PASSWORD")
    if not (email and password):
        sys.exit("set SCREENSHOT_EMAIL and SCREENSHOT_PASSWORD")
    args.out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as pw:
        browser = launch(pw)
        context = browser.new_context(
            viewport={"width": args.width, "height": 900}, locale="en-US", color_scheme="light"
        )
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{args.base_url}/login")
        settle(page)
        page.screenshot(path=args.out / "login.png")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(password)
        page.get_by_role("button", name="Sign in").click()
        page.get_by_role("button", name="Log out").wait_for()

        for name, path in PAGES:
            # Client-side navigation, as a user clicking the sidebar. A full reload per page
            # would call /api/auth/refresh each time and hit its 10/minute rate limit.
            page.evaluate(NAVIGATE, path)
            settle(page)
            page.screenshot(path=args.out / f"{name}.png", full_page=True)
            print(f"{name:16} {path}")
            if name == "customers":
                page.locator("table a[href^='/customers/']").first.click()
                settle(page)
                page.screenshot(path=args.out / "customer-360.png", full_page=True)
                print(f"{'customer-360':16} (first customer in the list)")
        browser.close()

    if errors:
        print("JavaScript errors:", *errors, sep="\n  ")
        return 1
    print(f"saved to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
