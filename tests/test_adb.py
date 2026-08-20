"""Tests for ADB integration."""

import pytest
from unittest.mock import patch

from phone_master.adb import ADBClient, ADBManager


@pytest.fixture
def adb_client():
    """Create ADB client for testing."""
    return ADBClient()


def test_adb_client_init():
    """Test ADB client initialization."""
    client = ADBClient(adb_path="adb")
    assert client.adb_path == "adb"
    assert client.device_serial is None


def test_get_package_infos_parses_all_packages():
    client = ADBClient()
    output = """Packages:
  Package [one.app] (abc):
    versionCode=12 minSdk=23 targetSdk=35
    versionName=1.2.0-beta
  Package [two.app] (def):
    versionCode=99 minSdk=26 targetSdk=35
    versionName=2026.08
"""
    with patch.object(client, "_run_command", return_value=output) as run:
        assert client.get_package_infos() == {
            "one.app": {"version_code": 12, "version": "1.2.0-beta"},
            "two.app": {"version_code": 99, "version": "2026.08"},
        }
    run.assert_called_once_with("shell", "dumpsys", "package", "packages", timeout=120)


def test_get_installed_apps_uses_one_bulk_package_query():
    manager = ADBManager.__new__(ADBManager)
    manager.client = client = ADBClient()
    with (
        patch.object(client, "get_installed_packages", return_value=["one.app", "two.app"]),
        patch.object(client, "get_package_installers", return_value={}),
        patch.object(
            client,
            "get_package_infos",
            return_value={
                "one.app": {"version": "1.0", "version_code": 1},
                "two.app": {"version": "2.0", "version_code": 2},
            },
        ) as bulk,
        patch.object(client, "get_package_info") as individual,
    ):
        apps = manager.get_installed_apps()

    assert [app.version for app in apps] == ["1.0", "2.0"]
    bulk.assert_called_once_with()
    individual.assert_not_called()
