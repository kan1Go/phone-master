"""Version string comparison shared across app stores and update checks."""

from typing import Optional


def compare_versions(v1: Optional[str], v2: Optional[str]) -> int:
    """Compare two dotted version strings.

    Returns 1 if v1 > v2, -1 if v1 < v2, 0 if equal or either is unparseable.
    """
    if not v1 or not v2:
        return 0
    try:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]

        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0

            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1

        return 0
    except ValueError:
        return 0


def is_newer(candidate: Optional[str], current: Optional[str]) -> bool:
    """True if candidate is a real, parseable version strictly newer than current."""
    if not candidate:
        return False
    if not current or current == "not installed":
        return True
    return compare_versions(candidate, current) > 0
