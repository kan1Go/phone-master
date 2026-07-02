"""Tests for app models."""

import pytest
from phone_master.models import App, AppSource, AppStatus


def test_app_creation():
    """Test app model creation."""
    app = App(
        package_name="com.example.app",
        app_name="Example App",
        version="1.0.0",
        version_code=1,
        source=AppSource.GOOGLE_PLAY
    )
    
    assert app.package_name == "com.example.app"
    assert app.app_name == "Example App"
    assert app.version == "1.0.0"
    assert app.installed is True


def test_app_string_representation():
    """Test app string representation."""
    app = App(
        package_name="com.example.app",
        app_name="Example App",
        version="1.0.0",
        version_code=1,
        source=AppSource.GOOGLE_PLAY
    )
    
    assert str(app) == "Example App (com.example.app) v1.0.0"
