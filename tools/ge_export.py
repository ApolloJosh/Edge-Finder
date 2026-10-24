"""Run Gridiron Edge in a headless browser and click "Export for Edge Finder".

Used by GitHub Actions on NFL days, so Gridiron Edge's read lands on the board
without anyone opening it. Gridiron Edge is loaded from a checkout of its repo
(file://, the same way it runs on the Mac), scans the slate from ESPN, and
the downloaded export is saved to inputs/.

  python tools/ge_export.py path/to/Gridiron-Edge/index.html inputs/
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BUTTON = "button:has-text('Export for Edge Finder')"


def main(index_html, out_dir, timeout_s=240):
    os.makedirs(out_dir, exist_ok=True)
    url = "file://" + os.path.abspath(index_html)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(accept_downloads=True, viewport={"width": 1400, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_selector(BUTTON, timeout=timeout_s * 1000)
        # The button is disabled while the scan runs and enabled once rows exist.
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if page.is_enabled(BUTTON):
                break
            time.sleep(2)
        else:
            raise SystemExit("Gridiron Edge never finished scanning (errors: %s)" % errors[:3])
        time.sleep(3)  # let practice reports and weather settle into the rows
        with page.expect_download(timeout=60000) as dl:
            page.click(BUTTON)
        d = dl.value
        dest = os.path.join(out_dir, d.suggested_filename)
        d.save_as(dest)
        browser.close()
    print("Saved %s" % dest)
    return dest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
