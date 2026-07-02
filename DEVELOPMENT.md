# Development Environment Setup

This guide helps you set up the development environment for phone-master.

## Prerequisites

- macOS, Linux, or Windows
- Python 3.8 or later
- pip and virtualenv
- Android Debug Bridge (ADB) - [Installation guide](https://developer.android.com/tools/adb)

## Step 1: Clone or Navigate to the Project

```bash
cd phone-master
```

## Step 2: Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

## Step 3: Upgrade pip

```bash
pip install --upgrade pip
```

## Step 4: Install Development Dependencies

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

This installs:
- Main dependencies (click, requests, etc.)
- Dev dependencies (pytest, black, flake8, mypy)

## Step 5: Verify Installation

```bash
phone-master --version
phone-master --help
```

## Step 6: Verify ADB Installation

```bash
adb version
adb devices
```

## IDE Setup

### VS Code

1. Install Python extension
2. Select interpreter: `Cmd+Shift+P` → "Python: Select Interpreter"
3. Choose the venv interpreter

### PyCharm

1. Open project settings
2. Project → Python Interpreter
3. Add interpreter → Existing environment → Select venv/bin/python

## Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=phone_master
```

## Code Quality

```bash
# Format code
black phone_master/

# Check style
flake8 phone_master/

# Type checking
mypy phone_master/
```

## Common Issues

### ModuleNotFoundError
Ensure virtual environment is activated and dependencies are installed:
```bash
source venv/bin/activate
pip install -e ".[dev]"
```

### ADB not found
Install Android SDK Tools or add ADB to PATH:
```bash
# macOS with Homebrew
brew install android-platform-tools

# Verify
which adb
```

### Permission denied on device
Enable USB debugging on your Android device and trust the connection when prompted.
