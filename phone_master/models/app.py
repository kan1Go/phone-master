"""App data models."""

from dataclasses import dataclass
from typing import Optional
from enum import Enum


class AppSource(str, Enum):
    """App store source."""
    GOOGLE_PLAY = "google_play"
    APKPURE = "apkpure"
    CHINESE_STORE = "chinese_store"
    SIDELOAD = "sideload"
    UNKNOWN = "unknown"


class AppStatus(str, Enum):
    """App update status."""
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    OUTDATED = "outdated"
    NOT_FOUND = "not_found"


@dataclass
class App:
    """Android app information."""
    package_name: str
    app_name: str
    version: str
    version_code: int
    source: AppSource
    installed: bool = True
    path: Optional[str] = None
    size: Optional[int] = None
    last_update: Optional[str] = None
    
    def __str__(self) -> str:
        return f"{self.app_name} ({self.package_name}) v{self.version}"


@dataclass
class AppUpdate:
    """App update information."""
    package_name: str
    current_version: str
    new_version: str
    source: AppSource
    download_url: str
    size: Optional[int] = None
    release_date: Optional[str] = None
    
    def __str__(self) -> str:
        return f"{self.package_name}: {self.current_version} → {self.new_version}"
