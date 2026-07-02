"""Tests for phone-master CLI."""

import pytest
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
