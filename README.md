# Phone Master CLI

A powerful command-line tool for managing Android apps on your phone, with special support for Chinese app stores and sideloading.

## Features

- **ADB Integration**: Connect to Android devices via USB or network
- **Multiple App Sources**: Google Play Store, APKPure, and Chinese app stores
- **Chinese App Support**: Built-in support for popular Chinese apps:
  - 小宇宙 (Xiaoyuzhou)
  - 豆包 (Doubao)
  - 抖音国内版 (Douyin - China version)
  - Keep健身国内版 (Keep Fitness - China version)
- **App Listing**: View all installed apps including those not from Google Play
- **Update Detection**: Automatically check for app updates across multiple sources
- **APK Sideloading**: Install APKs directly via ADB
- **Configuration Management**: Customize which apps to monitor and auto-update

## Installation

### Prerequisites
- Python 3.8+
- Android Debug Bridge (ADB) installed
- Android phone with USB debugging enabled

### Setup

1. Clone or navigate to the project directory:
```bash
cd phone-master
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e .
```

## Quick Start

### 1. Check Device Connection
```bash
phone-master devices
```

### 2. List Installed Apps
```bash
phone-master list-apps
phone-master list-apps --source chinese_store
```

### 3. Search for Apps
```bash
phone-master search --query "小宇宙"
phone-master search --query "Douyin" --store apkpure
```

### 4. Check for Updates
```bash
phone-master check-updates
```

### 5. Install an App
```bash
phone-master install com.qiwu.app /path/to/app.apk
phone-master install com.qiwu.app /path/to/app.apk --reinstall
```

### 6. Uninstall an App
```bash
phone-master uninstall com.qiwu.app
```

### 7. View Configuration
```bash
phone-master config-show
```

## Configuration

Create a `.phone-master.yaml` file in your project root to customize behavior:

```yaml
adb_path: adb
device_serial: null  # Auto-detect, or specify serial number
auto_update: false
check_updates_interval: 3600
download_dir: ./downloads
cache_dir: ./cache

managed_apps:
  - package_name: com.qiwu.app
    app_name: 小宇宙
    sources: [apkpure, chinese_store]
    auto_update: true
  - package_name: com.volcengine.live
    app_name: 豆包
    sources: [google_play, apkpure]
    auto_update: true
  - package_name: com.ss.android.ugc.aweme
    app_name: 抖音国内版
    sources: [chinese_store]
    auto_update: true
  - package_name: com.gotokeep.app
    app_name: Keep健身国内版
    sources: [chinese_store, apkpure]
    auto_update: true
```

## Setting Up USB Debugging

### On Your Android Phone:
1. Open **Settings** → **About Phone**
2. Tap **Build Number** 7 times to unlock Developer Options
3. Go to **Settings** → **Developer Options**
4. Enable **USB Debugging**
5. Optionally enable **Wireless Debugging** for network connections

### On Your Computer:
```bash
# List connected devices
adb devices

# Connect wirelessly (if device supports it)
adb connect <device-ip>:5555
```

## Architecture

```
phone-master/
├── phone_master/
│   ├── adb/              # Android Debug Bridge integration
│   │   ├── client.py     # ADB command wrapper
│   │   └── manager.py    # High-level ADB operations
│   ├── app_stores/       # App store integrations
│   │   ├── manager.py    # Multi-store manager
│   │   ├── google_play.py
│   │   ├── apkpure.py
│   │   └── chinese_stores.py
│   ├── models/           # Data models
│   ├── config/           # Configuration management
│   └── cli.py            # CLI commands
├── tests/                # Unit tests
└── pyproject.toml        # Project dependencies
```

## Development

### Run Tests
```bash
pytest tests/ -v
```

### Code Quality
```bash
black phone_master/
flake8 phone_master/
mypy phone_master/
```

## Troubleshooting

### Device not detected
- Ensure USB Debugging is enabled
- Try: `adb kill-server && adb start-server`
- Check ADB path: `which adb`

### APK installation fails
- Ensure you have the correct APK for your device architecture (ARM, ARM64, etc.)
- Try: `phone-master install <package> <apk> --reinstall`

### Connection issues with app stores
- Check your internet connection
- Some Chinese stores may require a Chinese IP or VPN
- Try using APKPure as a fallback (usually more accessible globally)

## Chinese App Store Support

The tool specifically supports finding and updating:

| App | Package Name | Preferred Sources |
|-----|--------------|-------------------|
| 小宇宙 | com.qiwu.app | APKPure, Chinese Stores |
| 豆包 | com.volcengine.live | Google Play, APKPure |
| 抖音国内版 | com.ss.android.ugc.aweme | Chinese Stores |
| Keep健身国内版 | com.gotokeep.app | Chinese Stores, APKPure |

## Security Notes

- Only install APKs from trusted sources
- Verify APK signatures when possible
- Be cautious with sideloading apps
- Keep your device's OS updated

## Contributing

Contributions are welcome! Please ensure:
- Code follows PEP 8 style guide
- All tests pass
- New features include tests
- Documentation is updated

## License

MIT License - see LICENSE file

## Support

For issues and feature requests, please open an issue on the project repository.
