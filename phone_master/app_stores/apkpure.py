"""APKPure integration."""

import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from ..models import App, AppUpdate, AppSource


class APKPureStore:
    """APKPure app store integration."""
    
    BASE_URL = "https://apkpure.com"
    
    def search(self, query: str) -> List[App]:
        """Search for apps on APKPure.
        
        Args:
            query: App name or package name
            
        Returns:
            List of found apps
        """
        try:
            url = f"{self.BASE_URL}/search?q={query}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, "html.parser")
            apps = []
            
            # Parse APKPure search results
            for item in soup.find_all("div", class_="app-item"):
                try:
                    name_elem = item.find("h2")
                    link_elem = item.find("a")
                    if name_elem and link_elem:
                        app = App(
                            package_name=link_elem.get("data-package", ""),
                            app_name=name_elem.text.strip(),
                            version="",
                            version_code=0,
                            source=AppSource.APKPURE,
                            installed=False
                        )
                        apps.append(app)
                except Exception as e:
                    print(f"Error parsing app item: {e}")
            
            return apps
        except Exception as e:
            print(f"Error searching APKPure: {e}")
            return []
    
    def get_latest_version(self, package_name: str, current_version: str) -> Optional[AppUpdate]:
        """Get latest version from APKPure.
        
        Args:
            package_name: Package name
            current_version: Current installed version
            
        Returns:
            AppUpdate if newer version found
        """
        try:
            url = f"{self.BASE_URL}/app/{package_name}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Find version info - simplified
            version_elem = soup.find("div", class_="version")
            if version_elem:
                new_version = version_elem.text.strip()
                
                if self._compare_versions(new_version, current_version) > 0:
                    download_url = self.get_download_url(package_name, new_version)
                    if download_url:
                        return AppUpdate(
                            package_name=package_name,
                            current_version=current_version,
                            new_version=new_version,
                            source=AppSource.APKPURE,
                            download_url=download_url
                        )
            
            return None
        except Exception as e:
            print(f"Error checking APKPure version: {e}")
            return None
    
    def get_download_url(self, package_name: str, version: str = "") -> Optional[str]:
        """Get APK download URL.
        
        Args:
            package_name: Package name
            version: Specific version (empty = latest)
            
        Returns:
            Download URL
        """
        try:
            url = f"{self.BASE_URL}/app/{package_name}"
            if version:
                url += f"/{package_name}-{version}-APK-Download"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
            
            # Look for download link
            soup = BeautifulSoup(response.content, "html.parser")
            download_btn = soup.find("a", class_="download-apk")
            if download_btn:
                return download_btn.get("href", "")
            
            return None
        except Exception as e:
            print(f"Error getting APK download URL: {e}")
            return None
    
    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """Compare two version strings. Returns 1 if v1 > v2, -1 if v1 < v2, 0 if equal."""
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
        except Exception:
            return 0
