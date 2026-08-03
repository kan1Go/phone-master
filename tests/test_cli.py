"""Tests for phone-master CLI."""

import pytest
from unittest.mock import patch
from click.testing import CliRunner
from phone_master.cli import main


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


def test_dict_list_defaults_to_mac(cli_runner, tmp_path):
    (tmp_path / "Oxford").mkdir()
    (tmp_path / "Longman").mkdir()
    (tmp_path / ".hidden").mkdir()

    with patch("phone_master.cli.Config.from_file") as from_file:
        config = from_file.return_value
        config.dictionary_source_dir = str(tmp_path)
        result = cli_runner.invoke(main, ["dict", "list"])

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
        result = cli_runner.invoke(main, ["dict", "push", "2"])

    assert result.exit_code != 0
    assert "selection out of range: 2" in result.output
