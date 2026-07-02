"""App Store Manager."""

from typing import List, Optional
from ..models import App, AppUpdate, AppSource
from .google_play import GooglePlayStore
from .apkpure import APKPureStore
from .chinese_stores import ChineseAppStore


class AppStoreManager:
    """Manages multiple app stores."""
    
    def __init__(self):
        """Initialize app store manager with all available stores."""
        self.stores = {
            AppSource.GOOGLE_PLAY: GooglePlayStore(),
            AppSource.APKPURE: APKPureStore(),
            AppSource.CHINESE_STORE: ChineseAppStore(),
        }
    
    def search_app(self, app_name: str, stores: Optional[List[AppSource]] = None) -> List[App]:
        """Search for app across stores.
        
        Args:
            app_name: App name or package name to search
            stores: List of stores to search (None = all)
            
        Returns:
            List of found apps
        """
        results = []
        search_stores = stores or list(self.stores.keys())
        
        for store_type in search_stores:
            if store_type in self.stores:
                try:
                    apps = self.stores[store_type].search(app_name)
                    results.extend(apps)
                except Exception as e:
                    print(f"Error searching in {store_type}: {e}")
        
        return results
    
    def check_updates(self, package_name: str, current_version: str) -> Optional[AppUpdate]:
        """Check for app updates across all stores.
        
        Args:
            package_name: Package name to check
            current_version: Current version installed
            
        Returns:
            AppUpdate if newer version found, else None
        """
        for store_type, store in self.stores.items():
            try:
                update = store.get_latest_version(package_name, current_version)
                if update:
                    return update
            except Exception as e:
                print(f"Error checking {store_type}: {e}")
        
        return None
    
    def get_download_url(self, package_name: str, version: str = "") -> Optional[str]:
        """Get download URL for app.
        
        Args:
            package_name: Package name
            version: Specific version (empty = latest)
            
        Returns:
            Download URL if found
        """
        for store in self.stores.values():
            try:
                url = store.get_download_url(package_name, version)
                if url:
                    return url
            except Exception:
                continue
        
        return None
