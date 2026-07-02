#!/bin/bash
# Quick setup script for phone-master

set -e

echo "🔧 Phone Master - Setup Script"
echo "================================"

# Check Python version
echo "✓ Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Found Python $python_version"

# Create virtual environment
echo "✓ Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "✓ Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "✓ Upgrading pip..."
pip install --upgrade pip > /dev/null 2>&1

# Install dependencies
echo "✓ Installing dependencies..."
pip install -e ".[dev]" > /dev/null 2>&1

# Check ADB
echo "✓ Checking ADB installation..."
if ! command -v adb &> /dev/null; then
    echo "  ⚠️  ADB not found in PATH"
    echo "  Install Android SDK Platform Tools:"
    echo "  - macOS: brew install android-platform-tools"
    echo "  - Linux: sudo apt install android-tools-adb"
    echo "  - Windows: Download from https://developer.android.com/tools"
else
    adb_version=$(adb version 2>&1 | head -1)
    echo "  $adb_version"
fi

echo ""
echo "✅ Setup Complete!"
echo ""
echo "Next steps:"
echo "1. Activate the virtual environment:"
echo "   source venv/bin/activate"
echo ""
echo "2. Enable USB Debugging on your Android device"
echo ""
echo "3. Connect your device and run:"
echo "   adb devices"
echo ""
echo "4. Copy the example configuration:"
echo "   cp .phone-master.yaml.example .phone-master.yaml"
echo ""
echo "5. Start using phone-master:"
echo "   phone-master --help"
echo "   phone-master devices"
echo "   phone-master list-apps"
