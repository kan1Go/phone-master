"""ADB client wrapper."""

import subprocess
import re
import posixpath
from typing import List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class DeviceInfo:
    """Android device information."""
    serial: str
    state: str
    model: str = ""
    device_name: str = ""
    android_version: str = ""


class ADBClient:
    """Wrapper around ADB command-line tool."""
    
    def __init__(self, adb_path: str = "adb", device_serial: Optional[str] = None):
        """Initialize ADB client.
        
        Args:
            adb_path: Path to ADB executable (default: 'adb' in PATH)
            device_serial: Serial number of target device (optional)
        """
        self.adb_path = adb_path
        self.device_serial = device_serial
    
    def _run_command(self, *args: str, timeout: int = 30) -> str:
        """Run ADB command and return output.

        Args:
            *args: Command arguments to pass to ADB
            timeout: Seconds to wait before giving up

        Returns:
            Command output string

        Raises:
            RuntimeError: If command fails
        """
        cmd = [self.adb_path]

        if self.device_serial:
            cmd.extend(["-s", self.device_serial])

        cmd.extend(args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"ADB command failed: {result.stderr}")
            
            return result.stdout.strip()
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"ADB command timed out: {e}")
        except FileNotFoundError:
            raise RuntimeError(f"ADB executable not found at: {self.adb_path}")
    
    def get_devices(self) -> List[DeviceInfo]:
        """Get list of connected devices."""
        output = self._run_command("devices", "-l")
        devices = []
        
        for line in output.split("\n")[1:]:  # Skip header
            if line.strip() and not line.startswith("List"):
                parts = line.split()
                if len(parts) >= 2:
                    device_info = DeviceInfo(serial=parts[0], state=parts[1])
                    devices.append(device_info)
        
        return devices
    
    def get_installed_packages(self, third_party_only: bool = True) -> List[str]:
        """Get list of installed packages.

        Args:
            third_party_only: Exclude preinstalled system packages (adb "-3" flag)
        """
        args = ["shell", "pm", "list", "packages"]
        if third_party_only:
            args.append("-3")
        output = self._run_command(*args)
        packages = []

        for line in output.split("\n"):
            if line.startswith("package:"):
                packages.append(line.replace("package:", "").strip())

        return packages

    def get_package_installers(self, third_party_only: bool = True) -> Dict[str, Optional[str]]:
        """Get installer package name for each installed package.

        Args:
            third_party_only: Exclude preinstalled system packages (adb "-3" flag)

        Returns:
            Dict mapping package_name -> installer package name (None if sideloaded)
        """
        args = ["shell", "pm", "list", "packages", "-i"]
        if third_party_only:
            args.append("-3")
        output = self._run_command(*args)
        installers: Dict[str, Optional[str]] = {}

        for line in output.split("\n"):
            match = re.match(r"package:(\S+)\s+installer=(\S+)", line.strip())
            if match:
                package_name, installer = match.groups()
                installers[package_name] = None if installer == "null" else installer

        return installers
    
    def get_package_info(self, package_name: str) -> Dict[str, Any]:
        """Get package information including version."""
        try:
            dumpsys_output = self._run_command("shell", "dumpsys", "package", package_name)
            info = self._parse_dumpsys_output(dumpsys_output)
            return info
        except RuntimeError:
            return {}
    
    def _parse_dumpsys_output(self, output: str) -> Dict[str, Any]:
        """Parse dumpsys package output."""
        info = {}
        
        for line in output.split("\n"):
            if "versionName=" in line:
                match = re.search(r"versionName=([\d.]+)", line)
                if match:
                    info["version"] = match.group(1)
            elif "versionCode=" in line:
                match = re.search(r"versionCode=(\d+)", line)
                if match:
                    info["version_code"] = int(match.group(1))
        
        return info
    
    def install_app(self, apk_path: str, reinstall: bool = False) -> bool:
        """Install APK on device.
        
        Args:
            apk_path: Path to APK file
            reinstall: Force reinstall if already installed
            
        Returns:
            True if installation succeeded
        """
        args = ["install"]
        if reinstall:
            args.append("-r")
        args.append(apk_path)

        output = self._run_command(*args, timeout=300)
        return "Success" in output
    
    def uninstall_app(self, package_name: str) -> bool:
        """Uninstall app from device."""
        output = self._run_command("uninstall", package_name)
        return "Success" in output

    def install_from_device_path(self, device_path: str, reinstall: bool = False) -> bool:
        """Install an APK that's already sitting on the device's own storage.

        Uses `pm install` (device-side) rather than `adb install` (which pushes
        a host file first) - the file never needs to leave the device. Files
        under another app's scoped-storage directory (e.g. Android/data/<pkg>)
        aren't directly readable by pm install: it runs as system_server, whose
        SELinux policy denies reading that fuse context even though `adb shell`
        itself can. So this stages a copy under /data/local/tmp first, which is
        exactly what pm install's own error message suggests doing.
        """
        staged_path = f"/data/local/tmp/{posixpath.basename(device_path)}"
        try:
            self._run_command("shell", "cp", device_path, staged_path, timeout=120)

            args = ["shell", "pm", "install"]
            if reinstall:
                args.append("-r")
            args.append(staged_path)

            output = self._run_command(*args, timeout=300)
            return "Success" in output
        finally:
            try:
                self._run_command("shell", "rm", "-f", staged_path)
            except RuntimeError:
                pass

    def find_files(self, directory: str, name_pattern: str = "*.apk") -> List[str]:
        """Find files matching a name pattern under a directory on the device."""
        try:
            output = self._run_command("shell", "find", directory, "-iname", name_pattern, timeout=30)
        except RuntimeError:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    def remove_file(self, device_path: str) -> bool:
        """Delete a file on the device."""
        try:
            self._run_command("shell", "rm", "-f", device_path)
            return True
        except RuntimeError:
            return False

    def push_file(self, local_path: str, device_path: str) -> bool:
        """Push file to device."""
        try:
            self._run_command("push", local_path, device_path)
            return True
        except RuntimeError:
            return False
    
    def pull_file(self, device_path: str, local_path: str) -> bool:
        """Pull file from device."""
        try:
            self._run_command("pull", device_path, local_path)
            return True
        except RuntimeError:
            return False
    
    def shell_command(self, command: str) -> str:
        """Execute shell command on device."""
        return self._run_command("shell", command)
