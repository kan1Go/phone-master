"""Chinese app stores integration."""

import requests
from bs4 import BeautifulSoup
from typing import List, Optional, Dict
from ..models import App, AppUpdate, AppSource


class ChineseAppStore:
    """Chinese app stores integration (multiple sources)."""
    
    # Chinese app store URLs
    STORES = {
        "coolapk": "https://www.coolapk.com",
        "appchina": "https://www.appchina.com",
        "anzhuo": "https://www.anzhuo.cn",
    }
    
    def __init__(self):
        """Initialize Chinese app store manager."""
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36"
        }
    
    def search(self, query: str) -> List[App]:
        """Search for apps in Chinese stores.
        
        Args:
            query: App name or package name
            
        Returns:
            List of found apps
        """
        apps = []
        
        # Try Coolapk first (most popular for Chinese apps)
        try:
            coolapk_apps = self._search_coolapk(query)
            apps.extend(coolapk_apps)
        except Exception as e:
            print(f"Error searching Coolapk: {e}")
        
        return apps
    
    def _search_coolapk(self, query: str) -> List[App]:
        """Search Coolapk app store."""
        try:
            url = f"{self.STORES['coolapk']}/apk/search"
            params = {"q": query}
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, "html.parser")
            apps = []
            
            for item in soup.find_all("div", class_="app-item"):
                try:
                    name_elem = item.find("h2")
                    package_elem = item.find("span", class_="package")
                    version_elem = item.find("span", class_="version")
                    
                    if name_elem and package_elem:
                        app = App(
                            package_name=package_elem.text.strip(),
                            app_name=name_elem.text.strip(),
                            version=version_elem.text.strip() if version_elem else "",
                            version_code=0,
                            source=AppSource.CHINESE_STORE,
                            installed=False
                        )
                        apps.append(app)
                except Exception as e:
                    print(f"Error parsing Coolapk item: {e}")
            
            return apps
        except Exception as e:
            print(f"Error searching Coolapk: {e}")
            return []
    
    def get_latest_version(self, package_name: str, current_version: str) -> Optional[AppUpdate]:
        """Get latest version from Chinese stores.
        
        Specifically optimized for:
        - 小宇宙 (com.qiwu.app)
        - 豆包 (com.volcengine.live)
        - 抖音国内版 (com.ss.android.ugc.aweme)
        - Keep健身国内版 (com.gotokeep.app)
        """
        try:
            # Try Coolapk first
            url = f"{self.STORES['coolapk']}/apk/{package_name}"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Find version info
            version_elem = soup.find("span", class_="version-number")
            if version_elem:
                new_version = version_elem.text.strip()
                
                if self._compare_versions(new_version, current_version) > 0:
                    download_url = self.get_download_url(package_name, new_version)
                    if download_url:
                        return AppUpdate(
                            package_name=package_name,
                            current_version=current_version,
                            new_version=new_version,
                            source=AppSource.CHINESE_STORE,
                            download_url=download_url
                        )
            
            return None
        except Exception as e:
            print(f"Error checking version in Chinese stores: {e}")
            return None
    
    def get_download_url(self, package_name: str, version: str = "") -> Optional[str]:
        """Get APK download URL from Chinese stores.
        
        Args:
            package_name: Package name
            version: Specific version (empty = latest)
            
        Returns:
            Download URL
        """
        try:
            url = f"{self.STORES['coolapk']}/apk/{package_name}"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Look for download button
            download_btn = soup.find("a", class_="download-link")
            if download_btn:
                return download_btn.get("href", "")
            
            # Alternative: look for data-download-url attribute
            container = soup.find("div", class_="app-info")
            if container:
                download_url = container.get("data-download-url")
                if download_url:
                    return download_url
            
            return None
        except Exception as e:
            print(f"Error getting download URL from Chinese stores: {e}")
            return None
    
    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """Compare two version strings."""
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
