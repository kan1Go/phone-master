"""Find and inspect stray APK files already sitting on the device.

Some apps (e.g. self-updating Chinese apps) download their own update APK to
local storage without going through any app store - checking for these first
means a real update that's already on the device doesn't need to be fetched
again from anywhere. There's no on-device way to read an arbitrary APK's real
package/version without aapt (not guaranteed present), so this pulls the file
and reads it locally with androguard instead.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

# androguard logs its manifest-parsing internals at INFO/DEBUG by default (via
# loguru, not stdlib logging), which is far too noisy for a CLI tool inspecting
# dozens of files - silence both before importing it.
from loguru import logger as _loguru_logger

_loguru_logger.remove()
logging.disable(logging.CRITICAL)

from androguard.core.apk import APK  # noqa: E402


SEARCH_DIRS = ["/sdcard/Download", "/sdcard/Downloads", "/storage/emulated/0/Download"]


def find_candidate_paths(client, package_names: List[str]) -> List[str]:
    """Search common storage locations and each package's own data folder for .apk files."""
    dirs = list(SEARCH_DIRS) + [f"/sdcard/Android/data/{pkg}" for pkg in package_names]

    paths = []
    seen = set()
    for directory in dirs:
        for path in client.find_files(directory, "*.apk"):
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def inspect_apk(client, device_path: str, tmp_dir: str) -> Optional[Dict]:
    """Pull an APK from the device and read its real package/version.

    The local copy is deleted again immediately - it's a throwaway used only
    to answer "what is this file", not kept around.
    """
    local_path = Path(tmp_dir) / f"_inspect_{Path(device_path).name}"
    try:
        if not client.pull_file(device_path, str(local_path)):
            return None
        apk = APK(str(local_path))
        return {
            "device_path": device_path,
            "package_name": apk.get_package(),
            "version_name": apk.get_androidversion_name(),
        }
    except Exception:
        return None
    finally:
        if local_path.exists():
            local_path.unlink()
