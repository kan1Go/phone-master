"""Tests for ADB integration."""

import pytest
from phone_master.adb import ADBClient


@pytest.fixture
def adb_client():
    """Create ADB client for testing."""
    return ADBClient()


def test_adb_client_init():
    """Test ADB client initialization."""
    client = ADBClient(adb_path="adb")
    assert client.adb_path == "adb"
    assert client.device_serial is None
