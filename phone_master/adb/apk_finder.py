"""Find and inspect stray APK files already sitting on the device.

Some apps (e.g. self-updating Chinese apps) download their own update APK to
local storage without going through any app store - checking for these first
means a real update that's already on the device doesn't need to be fetched
again from anywhere. There's no on-device way to read an arbitrary APK's real
package/version without aapt (not guaranteed present), so this pulls the file
and reads it locally with androguard instead.
"""

import logging
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

# androguard logs its manifest-parsing internals at INFO/DEBUG by default (via
# loguru, not stdlib logging), which is far too noisy for a CLI tool inspecting
# dozens of files - silence both before importing it.
from loguru import logger as _loguru_logger

_loguru_logger.remove()
logging.disable(logging.CRITICAL)

from androguard.core.apk import APK  # noqa: E402


SEARCH_DIRS = ["/sdcard/Download", "/sdcard/Downloads"]

# 应用宝 keeps completed downloads in these scoped-storage directories on
# current Android releases. The second path is used by some older releases.
TENCENT_MYAPP_DIRS = [
    "/sdcard/Android/data/com.tencent.android.qqdownloader/files/tassistant/apk",
    "/sdcard/Android/data/com.tencent.android.qqdownloader/files/apk",
]


def find_candidate_paths(client, package_names: List[str]) -> List[str]:
    """Search common storage locations and each package's own data folder for .apk files."""
    dirs = (
        list(SEARCH_DIRS)
        + list(TENCENT_MYAPP_DIRS)
        + [f"/sdcard/Android/data/{pkg}" for pkg in package_names]
    )

    paths = []
    seen = set()
    for path in client.find_files_many(dirs, "*.apk"):
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def read_package_name(local_path: str) -> Optional[str]:
    """Read the real package name straight out of an APK file already on disk."""
    try:
        return APK(local_path).get_package()
    except Exception:
        return None


def inspect_apk(client, device_path: str, tmp_dir: str) -> Optional[Dict]:
    """Pull an APK from the device and read its real package/version.

    The local copy is deleted again immediately - it's a throwaway used only
    to answer "what is this file", not kept around.
    """
    cache_root = Path(tmp_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(device_path.encode("utf-8")).hexdigest()
    metadata_path = cache_root / f"apk-{cache_key}.json"
    signature = client.file_signature(device_path)
    if signature and metadata_path.exists():
        try:
            cached = json.loads(metadata_path.read_text(encoding="utf-8"))
            if cached.get("signature") == signature:
                return cached["info"]
        except (OSError, ValueError, KeyError):
            pass

    local_path = cache_root / f"_inspect_{cache_key}.apk"
    try:
        if not client.pull_file(device_path, str(local_path)):
            return None
        apk = APK(str(local_path))
        info = {
            "device_path": device_path,
            "package_name": apk.get_package(),
            "version_name": apk.get_androidversion_name(),
        }
        if signature:
            metadata_path.write_text(
                json.dumps({"signature": signature, "info": info}, ensure_ascii=False),
                encoding="utf-8",
            )
        return info
    except Exception:
        return None
    finally:
        if local_path.exists():
            local_path.unlink()
