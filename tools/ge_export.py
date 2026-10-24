"""Run Gridiron Edge in a headless browser and click "Export for Edge Finder".

Used by GitHub Actions on NFL days, so Gridiron Edge's read lands on the board
without anyone opening it. Gridiron Edge is loaded from a checkout of its repo
(file://, the same way it runs on the Mac), scans the slate from ESPN, and
the downloaded export is saved to inputs/.

  python tools/ge_export.py path/to/Gridiron-Edge/index.html inputs/

On failure it reports what the page was doing (errors, failed requests, the
text on screen) as a GitHub annotation, since Actions logs aren't always handy.
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BUTTON = "button:has-text('Export for Edge Finder')"


def report(title, lines):
    msg = " | ".join(str(l).replace("\n", " ")[:300] for l in lines if l)[:1800]
    print("%s: %s" % (title, msg))
    if os.environ.get("GITHUB_ACTIONS"):
        print("::error title=%s::%s" % (title, msg.replace("%", "%25")))


def main(index_html, out_dir, timeout_s=300):
    os.makedirs(out_dir, exist_ok=True)
    url = "file://" + os.path.abspath(index_html)
    errors, console, failed = [], [], []
    with sync_playwright() as p:
        # Opened from a file, the page has origin "null", and ESPN's API refuses
        # cross-site reads from that origin. This private headless run reads the
        # same public data Gridiron Edge reads in your browser, so the browser's
        # cross-site check is switched off for it.
        browser = p.chromium.launch(args=["--disable-web-security"])
        page = browser.new_page(accept_downloads=True, viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console.append("%s: %s" % (m.type, m.text)) if m.type in ("error", "warning") else None)
        page.on("requestfailed", lambda r: failed.append("%s (%s)" % (r.url.split("?")[0], r.failure)))
        page.on("response", lambda r: failed.append("%s HTTP %s" % (r.url.split("?")[0], r.status)) if r.status >= 400 else None)

        def diagnose(stage):
            try:
                body = page.inner_text("body")[:500]
            except Exception as e:  # pragma: no cover
                body = "(no body: %s)" % e
            try:
                state = "button present=%s enabled=%s text=%r" % (
                    page.locator(BUTTON).count() > 0,
                    page.locator(BUTTON).count() > 0 and page.is_enabled(BUTTON),
                    page.locator("button:has-text('Export')").first.inner_text() if page.locator("button:has-text('Export')").count() else None)
            except Exception as e:  # pragma: no cover
                state = "button state unknown: %s" % e
            report("Gridiron Edge export failed at: " + stage,
                   [state, "page errors: %s" % errors[:3], "console: %s" % console[:4],
                    "failed requests: %s" % sorted(set(failed))[:6], "screen: " + body])

        try:
            page.goto(url)
            page.wait_for_selector(BUTTON, timeout=timeout_s * 1000)
        except Exception as e:
            diagnose("waiting for the Export button (%s)" % type(e).__name__)
            browser.close()
            sys.exit(1)

        # Disabled while the scan runs; enabled once rows exist.
        deadline = time.time() + timeout_s
        while time.time() < deadline and not page.is_enabled(BUTTON):
            time.sleep(2)
        if not page.is_enabled(BUTTON):
            diagnose("scan never finished")
            browser.close()
            sys.exit(1)
        time.sleep(3)  # let practice reports and weather settle into the rows
        try:
            with page.expect_download(timeout=60000) as dl:
                page.click(BUTTON)
            d = dl.value
            dest = os.path.join(out_dir, d.suggested_filename)
            d.save_as(dest)
        except Exception as e:
            diagnose("clicking Export (%s)" % type(e).__name__)
            browser.close()
            sys.exit(1)
        browser.close()
    print("Saved %s" % dest)
    if os.environ.get("GITHUB_ACTIONS"):
        print("::notice::Gridiron Edge export saved: %s (%d KB)" % (os.path.basename(dest), os.path.getsize(dest) // 1024))
    return dest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
