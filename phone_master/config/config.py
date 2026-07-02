"""Configuration management."""

import os
from pathlib import Path
from typing import Dict, List, Optional
import yaml
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    """Configuration for specific apps to manage."""
    package_name: str
    app_name: str
    sources: List[str] = ["google_play"]  # ['google_play', 'apkpure', 'chinese_store']
    auto_update: bool = False
    
    class Config:
        env_prefix = "PHONE_MASTER_"


class Config(BaseSettings):
    """Main configuration for phone-master."""
    
    # ADB configuration
    adb_path: str = "adb"
    device_serial: Optional[str] = None
    
    # App store configuration
    check_updates_interval: int = 3600  # seconds
    auto_update: bool = False
    
    # Chinese app stores
    chinese_stores: Dict[str, str] = {
        "appstorage": "https://cn.appstorage.com",
        "xmind": "https://store.xmind.com",
    }
    
    # Apps to manage - specific to your needs
    managed_apps: List[Dict[str, any]] = [
        {
            "package_name": "com.qiwu.app",
            "app_name": "小宇宙",
            "sources": ["apkpure", "chinese_store"],
            "auto_update": True,
        },
        {
            "package_name": "com.volcengine.live",
            "app_name": "豆包",
            "sources": ["google_play", "apkpure"],
            "auto_update": True,
        },
        {
            "package_name": "com.ss.android.ugc.aweme",
            "app_name": "抖音（国内版）",
            "sources": ["chinese_store"],
            "auto_update": True,
        },
        {
            "package_name": "com.gotokeep.app",
            "app_name": "Keep健身国内版",
            "sources": ["chinese_store", "apkpure"],
            "auto_update": True,
        },
    ]
    
    # Download configuration
    download_dir: str = "./downloads"
    cache_dir: str = "./cache"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "PHONE_MASTER_"
    
    def __init__(self, **data):
        super().__init__(**data)
        # Create necessary directories
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def from_file(cls, config_path: str = ".phone-master.yaml") -> "Config":
        """Load configuration from YAML file."""
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()
    
    def save_to_file(self, config_path: str = ".phone-master.yaml") -> None:
        """Save configuration to YAML file."""
        config_dict = self.dict()
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_dict, f, allow_unicode=True, default_flow_style=False)
