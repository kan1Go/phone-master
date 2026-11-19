"""Tests for phone-master CLI."""

import pytest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
from click.testing import CliRunner
from phone_master.cli import _scan_and_clean_local_apks, main
from phone_master.models import AppSource
from phone_master.config import Config
from phone_master.adb.client import DeviceInfo, WirelessService


def test_devices_list_includes_usb_wifi_and_offline(cli_runner):
    with patch("phone_master.cli.ADBClient") as client:
        client.return_value.get_devices.return_value = [
            DeviceInfo("usb", "device", "Pixel"),
            DeviceInfo("192.168.1.2:5555", "offline"),
        ]
        client.return_value.get_wireless_services.return_value = []
        result = cli_runner.invoke(main, ["devices", "list"])
    assert result.exit_code == 0
    assert "usb" in result.output
    assert "192.168.1.2:5555" in result.output
    assert "Offline" in result.output


def test_device_list_shows_friendly_names_and_actionable_status(cli_runner):
    with patch("phone_master.cli.ADBClient") as client:
        client.return_value.get_devices.return_value = [
            DeviceInfo("192.168.1.107:43049", "device", "CPH2449", market_name="OnePlus 11", android_version="14"),
            DeviceInfo("192.168.1.106:5555", "unauthorized"),
        ]
        client.return_value.get_wireless_services.return_value = [
            WirelessService("adb-phone", "_adb-tls-connect._tcp", "192.168.1.107:43049"),
            WirelessService("adb-other", "_adb._tcp", "192.168.1.105:5555"),
        ]
        result = cli_runner.invoke(main, ["devices", "list"])
    assert result.exit_code == 0, result.output
    assert "OnePlus 11" in result.output
    assert "Ready" in result.output
    assert "Needs authorization" in result.output
    assert "accept the debugging prompt" in result.output
    assert "Discovered; not connected" in result.output
    assert result.output.count("192.168.1.107:43049") == 1
    assert "_adb" not in result.output
    assert "adb pair" not in result.output


def test_device_list_verbose_retains_raw_services(cli_runner):
    with patch("phone_master.cli.ADBClient") as client:
        client.return_value.get_devices.return_value = []
        client.return_value.get_wireless_services.return_value = [
            WirelessService("adb-phone", "_adb-tls-pairing._tcp", "192.168.1.1:12345"),
        ]
        result = cli_runner.invoke(main, ["devices", "list", "--verbose"])
    assert result.exit_code == 0
    assert "Pairing available" in result.output
    assert "_adb-tls-pairing._tcp" in result.output


def test_devices_select_saves_choice_and_preserves_config(cli_runner):
    with cli_runner.isolated_filesystem():
        config = Config(download_dir="downloads", cache_dir="cache")
        config.save_to_file()
        with patch("phone_master.cli.ADBClient") as client:
            client.return_value.get_devices.return_value = [
                DeviceInfo("usb", "unauthorized"), DeviceInfo("wifi:5555", "device")
            ]
            result = cli_runner.invoke(main, ["devices", "select"], input="2\n")
        assert result.exit_code == 0, result.output
        saved = Config.from_file()
        assert saved.device_serial == "wifi:5555"
        assert saved.managed_apps == config.managed_apps


def test_devices_select_rejects_unavailable_device(cli_runner, tmp_path):
    with patch("phone_master.cli.ADBClient") as client, patch("phone_master.cli.Config.from_file") as config:
        client.return_value.get_devices.return_value = [DeviceInfo("usb", "device")]
        config.return_value.cache_dir = str(tmp_path)
        result = cli_runner.invoke(main, ["devices", "select", "missing"])
    assert result.exit_code != 0
    config.return_value.save_to_file.assert_not_called()


def test_device_numbers_preserve_last_list_order(cli_runner):
    with cli_runner.isolated_filesystem():
        with patch("phone_master.cli.ADBClient") as client:
            client.return_value.get_devices.return_value = [
                DeviceInfo("locked", "unauthorized"), DeviceInfo("wifi:5555", "device", "OnePlus 11")
            ]
            client.return_value.get_wireless_services.return_value = []
            listed = cli_runner.invoke(main, ["devices", "list"])
            assert listed.exit_code == 0, listed.output
            assert "No." in listed.output
            client.return_value.get_devices.return_value = [
                DeviceInfo("wifi:5555", "device", "OnePlus 11"), DeviceInfo("locked", "unauthorized")
            ]
            chosen = cli_runner.invoke(main, ["devices", "select", "2"])
            assert chosen.exit_code == 0, chosen.output
            assert Config.from_file().device_serial == "wifi:5555"
            rejected = cli_runner.invoke(main, ["devices", "select", "1"])
            assert rejected.exit_code != 0
            assert "Needs authorization" in rejected.output


def test_number_selection_does_not_replace_disconnected_device(cli_runner):
    with cli_runner.isolated_filesystem():
        with patch("phone_master.cli.ADBClient") as client:
            client.return_value.get_devices.return_value = [DeviceInfo("old", "device")]
            client.return_value.get_wireless_services.return_value = []
            assert cli_runner.invoke(main, ["devices", "list"]).exit_code == 0
            client.return_value.get_devices.return_value = [DeviceInfo("new", "device")]
            result = cli_runner.invoke(main, ["devices", "select", "1"])
            assert result.exit_code != 0
            assert "No longer available" in result.output
            assert not Path(".phone-master.yaml").exists()


def test_number_selection_rejects_discovered_and_out_of_range(cli_runner):
    with cli_runner.isolated_filesystem():
        with patch("phone_master.cli.ADBClient") as client:
            client.return_value.get_devices.side_effect = lambda **kwargs: []
            client.return_value.get_wireless_services.return_value = [
                WirelessService("phone", "_adb._tcp", "wifi:5555")
            ]
            result = cli_runner.invoke(main, ["devices", "select", "1"], input="\x03")
            assert result.exit_code != 0
            assert "Pair device with pairing code" in result.output
            result = cli_runner.invoke(main, ["devices", "select", "9"])
            assert result.exit_code != 0
            assert "between 1 and 1" in result.output


@pytest.fixture
def wireless_cli(tmp_path):
    config = SimpleNamespace(adb_path="adb", cache_dir=str(tmp_path),
                             device_serial="previous", save_to_file=Mock())
    client = Mock()
    client.get_wireless_services.return_value = [
        WirelessService("phone", "_adb-tls-connect._tcp", "192.168.1.107:43049")
    ]
    with patch("phone_master.cli.Config.from_file", return_value=config), patch("phone_master.cli.ADBClient", return_value=client):
        yield config, client


def test_select_connects_without_pairing_if_already_trusted(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], [DeviceInfo("192.168.1.107:43049", "device")]]
    result = cli_runner.invoke(main, ["devices", "select", "1"])
    assert result.exit_code == 0, result.output
    client.connect.assert_called_once_with("192.168.1.107:43049")
    client.pair.assert_not_called()
    assert config.device_serial == "192.168.1.107:43049"
    config.save_to_file.assert_called_once()


def test_select_guides_pairing_then_connects_and_saves(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], [], [DeviceInfo("192.168.1.107:43050", "device")]]
    debug = client.get_wireless_services.return_value
    client.get_wireless_services.side_effect = [debug, [
        *debug, WirelessService("phone", "_adb-tls-pairing._tcp", "192.168.1.107:41857"),
        WirelessService("other", "_adb-tls-pairing._tcp", "192.168.1.108:11111"),
    ], [WirelessService("phone", "_adb-tls-connect._tcp", "192.168.1.107:43050")]]
    client.connect.side_effect = [RuntimeError("not paired"), "connected"]
    result = cli_runner.invoke(main, ["devices", "select", "1"], input="123456\n")
    assert result.exit_code == 0, result.output
    assert "Pair device with pairing code" in result.output
    assert "123456" not in result.output
    client.pair.assert_called_once_with("192.168.1.107:41857", "123456")
    assert client.connect.call_args.args == ("192.168.1.107:43050",)
    assert config.device_serial == "192.168.1.107:43050"
    config.save_to_file.assert_called_once()


def test_select_pairing_without_mdns_prompts_for_distinct_ports(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [
        [DeviceInfo("192.168.1.107:41857", "pairing")],
        [DeviceInfo("192.168.1.107:43049", "device")],
    ]
    client.get_wireless_services.return_value = []
    result = cli_runner.invoke(main, ["devices", "select", "1"],
                               input="123456\n192.168.1.107:41857\n192.168.1.107:43049\n")
    assert result.exit_code == 0, result.output
    client.pair.assert_called_once_with("192.168.1.107:41857", "123456")
    client.connect.assert_called_once_with("192.168.1.107:43049")
    assert config.device_serial == "192.168.1.107:43049"


def test_select_failed_pairing_can_retry_with_new_code(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], [], [DeviceInfo("192.168.1.107:43049", "device")]]
    client.get_wireless_services.return_value += [
        WirelessService("phone", "_adb-tls-pairing._tcp", "192.168.1.107:41857")
    ]
    client.pair.side_effect = [RuntimeError("wrong password"), "paired"]
    result = cli_runner.invoke(main, ["devices", "select", "1"], input="111111\n222222\n")
    assert result.exit_code == 0, result.output
    assert client.pair.call_count == 2
    assert client.pair.call_args.args[1] == "222222"
    assert "Reopen 'Pair device with pairing code'" in result.output


def test_select_pairing_failure_preserves_previous_selection(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], []]
    client.get_wireless_services.return_value += [
        WirelessService("phone", "_adb-tls-pairing._tcp", "192.168.1.107:41857")
    ]
    client.pair.side_effect = RuntimeError("wrong password")
    result = cli_runner.invoke(main, ["devices", "select", "1"], input="111111\n222222\n333333\n")
    assert result.exit_code != 0
    assert client.pair.call_count == 3
    assert config.device_serial == "previous"
    config.save_to_file.assert_not_called()


def test_select_pairing_success_connection_failure_keeps_selection(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], []]
    client.get_wireless_services.return_value += [
        WirelessService("phone", "_adb-tls-pairing._tcp", "192.168.1.107:41857")
    ]
    client.connect.side_effect = [RuntimeError("not paired"), RuntimeError("connection refused")]
    result = cli_runner.invoke(main, ["devices", "select", "1"], input="123456\n")
    assert result.exit_code != 0
    assert "Pairing succeeded, but connection failed" in result.output
    assert config.device_serial == "previous"
    config.save_to_file.assert_not_called()


def test_select_rejects_invalid_pairing_code_without_sending_it(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], []]
    result = cli_runner.invoke(main, ["devices", "select", "1"], input="abc\n12\n1234567\n")
    assert result.exit_code != 0
    assert "exactly 6 digits" in result.output
    client.pair.assert_not_called()
    config.save_to_file.assert_not_called()


def test_select_cancel_pairing_preserves_selection(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], []]
    result = cli_runner.invoke(main, ["devices", "select", "1"], input="\x03")
    assert result.exit_code != 0
    client.pair.assert_not_called()
    config.save_to_file.assert_not_called()


def test_select_does_not_pair_a_different_phone(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.side_effect = [[], []]
    result = cli_runner.invoke(main, ["devices", "select", "1"], input="123456\n192.168.1.108:41857\n")
    assert result.exit_code != 0
    assert "different host" in result.output
    client.pair.assert_not_called()
    config.save_to_file.assert_not_called()


def test_select_usb_authorization_never_prompts_for_wifi_pairing(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.return_value = [DeviceInfo("usb", "unauthorized")]
    result = cli_runner.invoke(main, ["devices", "select", "1"])
    assert result.exit_code != 0
    assert "USB debugging prompt" in result.output
    client.pair.assert_not_called()
    config.save_to_file.assert_not_called()


def test_device_list_merges_ip_mdns_and_pairing_rows(cli_runner, wireless_cli):
    config, client = wireless_cli
    client.get_devices.return_value = [
        DeviceInfo("192.168.1.107:43049", "device", "OnePlus 11"),
        DeviceInfo("phone._adb-tls-connect._tcp", "device", "OnePlus 11"),
    ]
    client.get_wireless_services.return_value += [
        WirelessService("phone", "_adb-tls-pairing._tcp", "192.168.1.107:41857")
    ]
    result = cli_runner.invoke(main, ["devices", "list"])
    assert result.exit_code == 0, result.output
    assert result.output.count("OnePlus 11") == 1
    assert json.loads((Path(config.cache_dir) / "device-selection.json").read_text()) == ["192.168.1.107:43049"]


@pytest.fixture
def cli_runner():
    """Create CLI runner for testing."""
    return CliRunner()


def test_version(cli_runner):
    """Test version command."""
    result = cli_runner.invoke(main, ['--version'])
    assert result.exit_code == 0


def test_help(cli_runner):
    """Test help command."""
    result = cli_runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    assert 'Commands:' in result.output or 'Usage:' in result.output


def test_configs_command_replaces_config_show(cli_runner):
    result = cli_runner.invoke(main, ["configs"])
    assert result.exit_code == 0
    assert "Current Configuration:" in result.output

    help_result = cli_runner.invoke(main, ["--help"])
    assert "configs" in help_result.output
    assert "config-show" not in help_result.output


def test_apps_command_replaces_list_apps(cli_runner):
    result = cli_runner.invoke(main, ["--help"])
    command_names = {
        line.strip().split()[0]
        for line in result.output.splitlines()
        if line.startswith("  ") and line.strip() and not line.strip().startswith("--")
    }
    assert "apps" in command_names
    assert "list-apps" not in command_names


def test_apps_defaults_to_non_play_managed_apps(cli_runner):
    installed = [
        SimpleNamespace(package_name="managed.side", version="1", source=AppSource.SIDELOAD),
        SimpleNamespace(package_name="managed.play", version="2", source=AppSource.GOOGLE_PLAY),
        SimpleNamespace(package_name="other.side", version="3", source=AppSource.SIDELOAD),
    ]
    with (
        patch("phone_master.cli.Config.from_file") as from_file,
        patch("phone_master.cli.ADBManager") as adb_type,
        patch("phone_master.cli._get_installed_apps_with_progress", return_value=installed),
        patch(
            "phone_master.cli._resolve_names_with_progress",
            side_effect=lambda resolver, packages: {package: package for package in packages},
        ),
    ):
        from_file.return_value.managed_apps = [
            {"package_name": "managed.side", "app_name": "Managed Side"},
            {"package_name": "managed.play", "app_name": "Managed Play"},
        ]
        adb_type.return_value.check_device_connection.return_value = True
        result = cli_runner.invoke(main, ["apps"])

    assert result.exit_code == 0
    assert "managed.side" in result.output
    assert "managed.play" not in result.output
    assert "other.side" not in result.output


def test_apps_all_shows_all_third_party_apps(cli_runner):
    installed = [
        SimpleNamespace(package_name="managed.play", version="2", source=AppSource.GOOGLE_PLAY),
        SimpleNamespace(package_name="other.side", version="3", source=AppSource.SIDELOAD),
    ]
    with (
        patch("phone_master.cli.Config.from_file") as from_file,
        patch("phone_master.cli.ADBManager") as adb_type,
        patch("phone_master.cli._get_installed_apps_with_progress", return_value=installed),
        patch(
            "phone_master.cli._resolve_names_with_progress",
            side_effect=lambda resolver, packages: {package: package for package in packages},
        ),
    ):
        from_file.return_value.managed_apps = []
        adb_type.return_value.check_device_connection.return_value = True
        result = cli_runner.invoke(main, ["apps", "--all"])

    assert result.exit_code == 0
    assert "managed.play" in result.output
    assert "other.side" in result.output


@pytest.mark.parametrize("local_update", [True, False])
def test_myapp_is_managed_and_scan_prepares_update(cli_runner, tmp_path, local_update):
    config = Config(
        cache_dir=str(tmp_path / "cache"),
        download_dir=str(tmp_path / "downloads"),
    )
    package = "com.tencent.android.qqdownloader"
    installed = [SimpleNamespace(package_name=package, version="1.0.0", source=AppSource.SIDELOAD)]
    device_path = f"/sdcard/Android/data/{package}/files/update.apk"
    local = {package: {"device_path": device_path, "version_name": "2.0.0"}} if local_update else {}

    with (
        patch("phone_master.cli.Config.from_file", return_value=config),
        patch("phone_master.cli.ADBManager") as adb_type,
        patch("phone_master.cli._get_installed_apps_with_progress", return_value=installed),
        patch("phone_master.cli._resolve_names_with_progress", return_value={package: "应用宝"}),
        patch("phone_master.cli._scan_and_clean_local_apks", return_value=local) as scan_local,
        patch("phone_master.cli._run_with_spinner", side_effect=lambda label, func, *args: func(*args)),
        patch("phone_master.cli.UptodownStore") as store_type,
        patch("phone_master.cli._download_many_with_progress") as download,
    ):
        adb_type.return_value.check_device_connection.return_value = True
        adb_type.return_value.device_serial = "test-device"
        page = "https://tencent-app-store.en.uptodown.com/android"
        store_type.return_value.get_version_batch.return_value = {page: "2.0.0"}
        store_type.return_value.get_latest_batch.return_value = {page: ("2.0.0", "https://example.com/myapp.apk")}

        apps_result = cli_runner.invoke(main, ["apps"])
        assert apps_result.exit_code == 0
        assert "应用宝" in apps_result.output

        result = cli_runner.invoke(main, ["scan"])

    assert result.exit_code == 0, result.output
    assert package in scan_local.call_args.args[2]
    plan = json.loads((tmp_path / "cache" / "update-plan.json").read_text())
    store_type.assert_not_called()
    download.assert_not_called()
    assert "online" not in result.output
    if local_update:
        update = next(item for item in plan["updates"] if item["package_name"] == package)
        assert update["new_version"] == "2.0.0"
        assert update["device_path"] == device_path
    else:
        assert plan["updates"] == []
        assert "no newer APK on phone" in result.output


def test_dictionaries_command_replaces_dict(cli_runner):
    result = cli_runner.invoke(main, ["--help"])
    command_names = {
        line.strip().split()[0]
        for line in result.output.splitlines()
        if line.startswith("  ") and line.strip() and not line.strip().startswith("--")
    }
    assert "dictionaries" in command_names
    assert "dict" not in command_names


@pytest.mark.parametrize("serial, expected", [("oneplus", {"other.play", "other.side"}), ("reader", {"configured.app"})])
def test_device_scoped_app_management(cli_runner, tmp_path, serial, expected):
    config = Config(
        cache_dir=str(tmp_path / "cache"), download_dir=str(tmp_path / "downloads"),
        manage_all_apps_devices=["oneplus"], chinese_apps={},
        managed_apps=[{"package_name": "configured.app", "app_name": "Configured"}],
    )
    installed = [
        SimpleNamespace(package_name="other.play", app_name="Play App", version="1", source=AppSource.GOOGLE_PLAY),
        SimpleNamespace(package_name="other.side", app_name="Side App", version="1", source=AppSource.SIDELOAD),
    ]
    with (
        patch("phone_master.cli.Config.from_file", return_value=config),
        patch("phone_master.cli.ADBManager") as adb_type,
        patch("phone_master.cli._get_installed_apps_with_progress", return_value=installed) as get_apps,
        patch("phone_master.cli._resolve_names_with_progress", return_value={a.package_name: a.app_name for a in installed}),
        patch("phone_master.cli._scan_and_clean_local_apks") as local_scan,
        patch("phone_master.cli._run_with_spinner", side_effect=lambda label, func, *args: func(*args)),
    ):
        adb_type.return_value.device_serial = serial
        adb_type.return_value.check_device_connection.return_value = True
        local_scan.side_effect = lambda adb, config, packages, installed: {
            p: {"device_path": f"/sdcard/Download/{p}.apk", "version_name": "2"} for p in packages
        }
        listed = cli_runner.invoke(main, ["apps"])
        assert listed.exit_code == 0
        assert ("Play App" in listed.output) == (serial == "oneplus")
        result = cli_runner.invoke(main, ["scan"])
        assert result.exit_code == 0, result.output
        assert get_apps.call_args.args[1] == (serial == "oneplus")
        assert set(local_scan.call_args.args[2]) == expected

    plan = json.loads((tmp_path / "cache" / "update-plan.json").read_text())
    assert {item["package_name"] for item in plan["updates"]} == expected


def test_all_apps_update_skips_system_packages(cli_runner, tmp_path):
    config = Config(cache_dir=str(tmp_path), download_dir=str(tmp_path), manage_all_apps_devices=["oneplus"])
    (tmp_path / "update-plan.json").write_text(json.dumps({
        "device_serial": "oneplus",
        "updates": [{"package_name": p, "app_name": p, "current_version": "1", "new_version": "2",
                     "device_path": f"/sdcard/Download/{p}.apk"} for p in ["system.app", "user.app"]],
    }))
    with (
        patch("phone_master.cli.Config.from_file", return_value=config),
        patch("phone_master.cli.ADBManager") as adb_type,
        patch("phone_master.cli._run_with_spinner", side_effect=lambda label, func, *args: func(*args)),
    ):
        adb = adb_type.return_value
        adb.device_serial = "oneplus"
        adb.client.get_installed_packages.return_value = ["user.app"]
        result = cli_runner.invoke(main, ["update"])
    assert result.exit_code == 0, result.output
    adb.client.get_installed_packages.assert_called_once_with(True)
    adb.client.install_from_device_path.assert_called_once_with("/sdcard/Download/user.app.apk", True)


def test_update_workflow_has_only_scan_and_update_commands(cli_runner):
    result = cli_runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    command_names = {
        line.strip().split()[0]
        for line in result.output.splitlines()
        if line.startswith("  ") and line.strip() and not line.strip().startswith("--")
    }
    assert "scan" in command_names
    assert "update" in command_names
    for obsolete in ("check-updates", "find-apks", "install", "search"):
        assert obsolete not in command_names


def test_update_without_scan_explains_next_step(cli_runner, tmp_path):
    with patch("phone_master.cli.Config.from_file") as from_file:
        from_file.return_value.cache_dir = str(tmp_path)
        result = cli_runner.invoke(main, ["update"])

    assert result.exit_code != 0
    assert "phonemaster scan" in result.output


def test_scan_cleanup_removes_installed_and_superseded_apks(tmp_path):
    adb = Mock()
    config = SimpleNamespace(cache_dir=str(tmp_path))
    installed = {"example.app": SimpleNamespace(version="1.0")}
    paths = ["/equal.apk", "/newer.apk", "/newest.apk"]
    details = {
        "/equal.apk": {"device_path": "/equal.apk", "package_name": "example.app", "version_name": "1.0"},
        "/newer.apk": {"device_path": "/newer.apk", "package_name": "example.app", "version_name": "2.0"},
        "/newest.apk": {"device_path": "/newest.apk", "package_name": "example.app", "version_name": "3.0"},
    }
    with (
        patch("phone_master.cli.find_candidate_paths", return_value=paths),
        patch("phone_master.cli.inspect_apk", side_effect=lambda client, path, cache: details[path]),
    ):
        result = _scan_and_clean_local_apks(adb, config, ["example.app"], installed)

    assert result["example.app"]["device_path"] == "/newest.apk"
    assert {call.args[0] for call in adb.client.remove_file.call_args_list} == {
        "/equal.apk",
        "/newer.apk",
    }


def test_dict_list_defaults_to_mac(cli_runner, tmp_path):
    (tmp_path / "Oxford").mkdir()
    (tmp_path / "Longman").mkdir()
    (tmp_path / ".hidden").mkdir()

    with patch("phone_master.cli.Config.from_file") as from_file:
        config = from_file.return_value
        config.dictionary_source_dir = str(tmp_path)
        result = cli_runner.invoke(main, ["dictionaries", "list"])

    assert result.exit_code == 0
    assert "1. Longman" in result.output
    assert "2. Oxford" in result.output
    assert ".hidden" not in result.output
    assert "Dictionaries on mac" in result.output


def test_dict_push_rejects_invalid_selection(cli_runner, tmp_path):
    (tmp_path / "Oxford").mkdir()

    with patch("phone_master.cli.Config.from_file") as from_file:
        config = from_file.return_value
        config.dictionary_source_dir = str(tmp_path)
        result = cli_runner.invoke(main, ["dictionaries", "push", "2"])

    assert result.exit_code != 0
    assert "selection out of range: 2" in result.output


@pytest.mark.parametrize("manage_all", [False, True])
@pytest.mark.parametrize("success", [False, True])
def test_chinese_apks_scan_install_and_cleanup(cli_runner, tmp_path, manage_all, success):
    config = Config(cache_dir=str(tmp_path), download_dir=str(tmp_path),
                    managed_apps=[], manage_all_apps_devices=["phone"] if manage_all else [])
    details = {
        f"/sdcard/Download/{package}.apk": {
            "device_path": f"/sdcard/Download/{package}.apk",
            "package_name": package, "version_name": "2",
        }
        for package in [*config.chinese_apps, "unrelated.app"]
    }
    with (
        patch("phone_master.cli.Config.from_file", return_value=config),
        patch("phone_master.cli.ADBManager") as adb_type,
        patch("phone_master.cli._get_installed_apps_with_progress", return_value=[]),
        patch("phone_master.cli.find_candidate_paths", return_value=list(details)),
        patch("phone_master.cli.inspect_apk", side_effect=lambda client, path, cache: details[path]),
        patch("phone_master.cli._run_with_spinner", side_effect=lambda label, func, *args: func(*args)),
    ):
        adb = adb_type.return_value
        adb.device_serial = "phone"
        adb.client.get_installed_packages.return_value = []
        adb.client.install_from_device_path.return_value = success
        scanned = cli_runner.invoke(main, ["scan"])
        assert scanned.exit_code == 0, scanned.output
        plan = json.loads((tmp_path / "update-plan.json").read_text())
        assert {item["package_name"] for item in plan["updates"]} == set(config.chinese_apps)
        adb.client.remove_file.assert_not_called()
        updated = cli_runner.invoke(main, ["update"])
        assert updated.exit_code == (0 if success else 1), updated.output
        assert adb.client.install_from_device_path.call_count == 3
        deleted = {call.args[0] for call in adb.client.remove_file.call_args_list}
        expected = {f"/sdcard/Download/{package}.apk" for package in config.chinese_apps}
        assert deleted == (expected if success else set())
        remaining = json.loads((tmp_path / "update-plan.json").read_text())["updates"]
        assert len(remaining) == (0 if success else 3)


def test_update_continues_after_adb_exception_and_retains_failed_apk(cli_runner, tmp_path):
    config = Config(cache_dir=str(tmp_path), download_dir=str(tmp_path))
    candidates = [
        {"package_name": p, "app_name": p, "current_version": "1", "new_version": "2",
         "device_path": f"/sdcard/Download/{p}.apk"}
        for p in ["com.xingin.xhs", "com.taobao.taobao"]
    ]
    plan_path = tmp_path / "update-plan.json"
    plan_path.write_text(json.dumps({"device_serial": "phone", "updates": candidates}))
    with (
        patch("phone_master.cli.Config.from_file", return_value=config),
        patch("phone_master.cli.ADBManager") as adb_type,
        patch("phone_master.cli._run_with_spinner", side_effect=lambda label, func, *args: func(*args)),
    ):
        adb = adb_type.return_value
        adb.device_serial = "phone"
        adb.client.install_from_device_path.side_effect = [
            RuntimeError("ADB command failed: Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]"), True,
        ]
        result = cli_runner.invoke(main, ["update"])
    assert result.exit_code == 1
    assert "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in result.output
    assert "1 update(s) failed" in result.output
    assert "Traceback" not in result.output
    assert adb.client.install_from_device_path.call_count == 2
    adb.client.remove_file.assert_called_once_with(candidates[1]["device_path"])
    assert json.loads(plan_path.read_text())["updates"] == candidates[:1]
