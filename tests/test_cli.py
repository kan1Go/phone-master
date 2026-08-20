"""Tests for phone-master CLI."""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
from click.testing import CliRunner
from phone_master.cli import _scan_and_clean_local_apks, main
from phone_master.models import AppSource


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


def test_dictionaries_command_replaces_dict(cli_runner):
    result = cli_runner.invoke(main, ["--help"])
    command_names = {
        line.strip().split()[0]
        for line in result.output.splitlines()
        if line.startswith("  ") and line.strip() and not line.strip().startswith("--")
    }
    assert "dictionaries" in command_names
    assert "dict" not in command_names


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
