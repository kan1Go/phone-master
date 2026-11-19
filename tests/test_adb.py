"""Tests for ADB integration."""

import pytest
from unittest.mock import patch

from phone_master.adb import ADBClient, ADBManager
from phone_master.adb.client import DeviceInfo


def test_pair_sends_code_over_stdin_not_process_arguments():
    from subprocess import CompletedProcess
    output = "Enter pairing code: Successfully paired to 192.168.1.107:41857 [guid=phone]"
    with patch("phone_master.adb.client.subprocess.run", return_value=CompletedProcess([], 0, output, "")) as run:
        result = ADBClient().pair("192.168.1.107:41857", "123456")
    assert "Successfully paired" in result
    assert run.call_args.args[0] == ["adb", "pair", "192.168.1.107:41857"]
    assert run.call_args.kwargs["input"] == "123456\n"
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("returncode", [0, 1])
def test_pair_reports_failure_even_with_zero_exit_code_and_redacts_code(returncode):
    from subprocess import CompletedProcess
    with patch("phone_master.adb.client.subprocess.run", return_value=CompletedProcess([], returncode, "Failed pairing 123456", "")):
        with pytest.raises(RuntimeError) as error:
            ADBClient().pair("192.168.1.107:41857", "123456")
    assert "123456" not in str(error.value)
    assert "Failed pairing" in str(error.value)


def test_pair_rejects_invalid_code_before_running_adb():
    with patch("phone_master.adb.client.subprocess.run") as run:
        with pytest.raises(ValueError, match="6 digits"):
            ADBClient().pair("192.168.1.107:41857", "123")
    run.assert_not_called()


def test_device_identity_prefers_marketing_name_and_targets_correct_phone():
    client = ADBClient("custom-adb", "other-phone")
    device = DeviceInfo("wifi:5555", "device", "CPH2449")
    output = """[ro.product.brand]: [OnePlus]
[ro.product.model]: [CPH2449]
[ro.product.marketname]: [OnePlus 11]
[ro.build.version.release]: [14]
"""
    from subprocess import CompletedProcess
    with patch("phone_master.adb.client.subprocess.run", return_value=CompletedProcess([], 0, output, "")) as run:
        client.populate_device_info(device)
    assert device.display_name == "OnePlus 11"
    assert device.android_version == "14"
    assert run.call_args.args[0] == ["custom-adb", "-s", "wifi:5555", "shell", "getprop"]
    assert client.device_serial == "other-phone"


def test_device_identity_fallback_and_unauthorized_devices():
    client = ADBClient()
    device = DeviceInfo("usb", "device", "Pixel_8")
    with patch.object(ADBClient, "_run_command", side_effect=RuntimeError("offline")):
        client.populate_device_info(device)
    assert device.display_name == "Pixel 8"
    with patch.object(ADBClient, "_run_command") as run:
        locked = DeviceInfo("locked", "unauthorized")
        client.populate_device_info(locked)
    run.assert_not_called()
    assert locked.display_name == "Unknown device"


def test_wireless_discovery_connects_debug_services_but_never_pairing():
    client = ADBClient()
    services = """List of discovered mdns services
phone _adb-tls-connect._tcp 192.168.1.2:37895
phone _adb-tls-connect._tcp 192.168.1.2:37895
pair _adb-tls-pairing._tcp 192.168.1.2:40000
old _adb._tcp. 192.168.1.3:5555
"""
    def run(*args, **kwargs):
        if args == ("mdns", "services"):
            return services
        if args[0] == "connect":
            return f"connected to {args[1]}"
        return "List of devices attached\nusb device model:Pixel device:pixel\n192.168.1.2:37895 device model:Phone\n"
    with patch.object(client, "_run_command", side_effect=run) as command:
        devices = client.get_devices()
    assert [(d.serial, d.model) for d in devices] == [("usb", "Pixel"), ("192.168.1.2:37895", "Phone")]
    assert [c.args for c in command.call_args_list if c.args[0] == "connect"] == [
        ("connect", "192.168.1.2:37895"), ("connect", "192.168.1.3:5555")
    ]


def test_unsupported_mdns_preserves_usb_detection():
    with patch.object(ADBClient, "_run_command", side_effect=[
        RuntimeError("unknown command mdns"), "List of devices attached\nusb device\n"
    ]):
        assert ADBClient().get_devices()[0].serial == "usb"


def test_failed_wifi_connection_preserves_usb_detection():
    with patch.object(ADBClient, "_run_command", side_effect=[
        "phone _adb-tls-connect._tcp 192.168.1.2:1234",
        "failed to connect", "List of devices attached\nusb device\n"
    ]):
        assert ADBClient().get_devices()[0].serial == "usb"


def test_manager_skips_unauthorized_and_checks_selected_device():
    with patch.object(ADBClient, "get_devices", return_value=[
        DeviceInfo("usb", "unauthorized"), DeviceInfo("wifi:5555", "device")
    ]):
        manager = ADBManager()
        assert manager.device_serial == "wifi:5555"
        assert manager.check_device_connection()
        selected = ADBManager(device_serial="missing")
        assert not selected.check_device_connection()


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


@pytest.mark.parametrize("stdout, stderr, expected", [
    ("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]", "", "INSTALL_FAILED_UPDATE_INCOMPATIBLE"),
    ("", "device offline", "device offline"),
    ("", "", "exit code 1 (no output)"),
    ("install failure", "extra detail", "install failure\nextra detail"),
])
def test_adb_failure_includes_both_output_streams(stdout, stderr, expected):
    from subprocess import CompletedProcess
    with patch("phone_master.adb.client.subprocess.run",
               return_value=CompletedProcess([], 1, stdout, stderr)):
        with pytest.raises(RuntimeError) as error:
            ADBClient()._run_command("shell", "pm", "install", "/tmp/app.apk")
    assert expected in str(error.value)


def test_device_install_failure_cleans_staging_and_reports_reason():
    client = ADBClient()
    with patch.object(client, "_run_command", side_effect=["", "Failure [INSTALL_FAILED_INVALID_APK]", ""]) as run:
        with pytest.raises(RuntimeError, match="INSTALL_FAILED_INVALID_APK"):
            client.install_from_device_path("/sdcard/Download/app.apk", True)
    assert run.call_args.args == ("shell", "rm", "-f", "/data/local/tmp/app.apk")
