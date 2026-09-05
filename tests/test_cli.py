"""Tests for phone-master CLI."""

import pytest
import json
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
from click.testing import CliRunner
from phone_master.cli import _scan_and_clean_local_apks, main
from phone_master.models import AppSource
from phone_master.config import Config


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
    update = next(item for item in plan["updates"] if item["package_name"] == package)
    assert update["new_version"] == "2.0.0"
    if local_update:
        assert update["device_path"] == device_path
        assert page not in store_type.return_value.get_version_batch.call_args.args[0]
    else:
        assert page in store_type.return_value.get_version_batch.call_args.args[0]
        assert download.call_args.args[0] == [
            ("https://example.com/myapp.apk", tmp_path / "downloads" / f"{package}-2.0.0.apk")
        ]


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
        manage_all_apps_devices=["oneplus"],
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
