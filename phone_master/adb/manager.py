"""ADB Manager for app management."""

import os
from typing import List, Optional, Dict, Any
from ..models import App, AppSource, AppStatus
from .client import ADBClient


class ADBManager:
    """Manages Android devices via ADB."""
    
    def __init__(self, adb_path: str = "adb", device_serial: Optional[str] = None):
        """Initialize ADB Manager.
        
        Args:
            adb_path: Path to ADB executable
            device_serial: Target device serial (auto-detect if None)
        """
        self.client = ADBClient(adb_path, device_serial)
        self.device_serial = device_serial or self._detect_device()
        if self.device_serial:
            self.client.device_serial = self.device_serial
    
    def _detect_device(self) -> Optional[str]:
        """Auto-detect connected device."""
        try:
            devices = self.client.get_devices()
            if devices:
                return devices[0].serial
        except RuntimeError:
            pass
        return None
    
    def get_installed_apps(self, third_party_only: bool = True) -> List[App]:
        """Get list of installed apps with details.

        Args:
            third_party_only: Exclude preinstalled system packages
        """
        apps = []
        packages = self.client.get_installed_packages(third_party_only)
        installers = self.client.get_package_installers(third_party_only)

        for package_name in packages:
            try:
                info = self.client.get_package_info(package_name)
                installer = installers.get(package_name)
                source = AppSource.GOOGLE_PLAY if installer == "com.android.vending" else AppSource.SIDELOAD
                app = App(
                    package_name=package_name,
                    app_name=package_name,  # Can be improved with package manager
                    version=info.get("version", "unknown"),
                    version_code=info.get("version_code", 0),
                    source=source,
                    installed=True
                )
                apps.append(app)
            except Exception as e:
                print(f"Error getting info for {package_name}: {e}")

        return apps
    
    def install_apk(self, apk_path: str, package_name: str = "", reinstall: bool = False) -> bool:
        """Install APK on device.
        
        Args:
            apk_path: Path to APK file
            package_name: Package name (for logging)
            reinstall: Force reinstall
            
        Returns:
            True if successful
        """
        if not os.path.exists(apk_path):
            print(f"APK not found: {apk_path}")
            return False
        
        try:
            return self.client.install_app(apk_path, reinstall)
        except RuntimeError as e:
            print(f"Error installing APK: {e}")
            return False
    
    def uninstall_app(self, package_name: str) -> bool:
        """Uninstall app from device."""
        try:
            return self.client.uninstall_app(package_name)
        except RuntimeError as e:
            print(f"Error uninstalling app: {e}")
            return False
    
    def check_device_connection(self) -> bool:
        """Check if device is connected."""
        try:
            devices = self.client.get_devices()
            return len(devices) > 0
        except RuntimeError:
            return False
