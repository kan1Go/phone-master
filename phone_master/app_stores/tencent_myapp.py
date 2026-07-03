"""应用宝 (Tencent MyApp) version lookup - used as an authoritative cross-check.

应用宝 doesn't offer a plain APK download (it pushes its own client app), so
this is only used to confirm the version number another source (Uptodown, a
file found on the device) reports as "latest" against a first-party Chinese
app store listing, not to fetch files.
"""

import re
from typing import Dict, List, Optional
from playwright.sync_api import sync_playwright

BASE_URL = "https://sj.qq.com/appdetail"

# A bare X.Y.Z version number, but not a YYYY.M.D update-date (which matches
# the same shape and appears right next to it on the page).
_VERSION_RE = re.compile(r"^\d{1,3}\.\d+\.\d+$")
_DATE_RE = re.compile(r"^20\d{2}\.\d+\.\d+$")


class TencentMyAppStore:
    """Looks up an app's currently listed version on 应用宝."""

    def get_version(self, package_name: str) -> Optional[str]:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                return self._get_version_on_page(page, package_name)
            finally:
                browser.close()

    def get_version_batch(self, package_names: List[str]) -> Dict[str, Optional[str]]:
        """Look up multiple packages, reusing one browser instance."""
        results = {}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for package_name in package_names:
                    page = browser.new_page(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    )
                    try:
                        results[package_name] = self._get_version_on_page(page, package_name)
                    except Exception:
                        results[package_name] = None
                    finally:
                        page.close()
            finally:
                browser.close()
        return results

    @staticmethod
    def _get_version_on_page(page, package_name: str) -> Optional[str]:
        page.goto(f"{BASE_URL}/{package_name}", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)

        for line in page.inner_text("body").split("\n"):
            line = line.strip()
            if _VERSION_RE.match(line) and not _DATE_RE.match(line):
                return line
        return None
