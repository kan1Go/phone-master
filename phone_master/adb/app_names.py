"""Resolve human-readable app display names, with a persistent local cache.

Package names (e.g. com.instagram.android) aren't meant for humans. Android's own
package manager doesn't expose the localized display label without parsing app
resources directly, so this looks it up from Google Play's public listing page
(which, unlike APKPure/Uptodown, serves plain HTML with no bot-blocking) and
caches the result to disk so we don't re-fetch on every run.
"""

import html
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import requests


class AppNameResolver:
    """Resolves package_name -> display name, caching results to disk."""

    CACHE_FILENAME = "app_names.json"

    def __init__(self, cache_dir: str, known_names: Optional[Dict[str, str]] = None):
        """
        Args:
            cache_dir: Directory to store the name cache in (config.cache_dir)
            known_names: package_name -> app_name overrides that skip the lookup
                (e.g. from managed_apps, which already records the real name)
        """
        self.cache_path = Path(cache_dir) / self.CACHE_FILENAME
        self.known_names = known_names or {}
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict[str, str]:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def resolve_many(self, package_names: List[str]) -> Dict[str, str]:
        """Get display names for a list of packages, only hitting the network for unseen ones."""
        result = {}
        changed = False

        for package_name in package_names:
            if package_name in self._cache:
                result[package_name] = self._cache[package_name]
                continue

            name = (
                self.known_names.get(package_name)
                or self._lookup_play_store(package_name)
                or package_name
            )
            self._cache[package_name] = name
            result[package_name] = name
            changed = True

        if changed:
            self._save_cache()

        return result

    @staticmethod
    def _lookup_play_store(package_name: str) -> Optional[str]:
        try:
            response = requests.get(
                f"https://play.google.com/store/apps/details?id={package_name}&hl=en",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                timeout=10,
            )
            if response.status_code != 200:
                return None

            match = re.search(r'itemprop="name"[^>]*>([^<]+)<', response.text)
            if match:
                return html.unescape(match.group(1).strip())

            match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.S)
            if match:
                title = match.group(1).split(" - Apps on Google Play")[0].strip()
                return html.unescape(title)

            return None
        except requests.RequestException:
            return None
