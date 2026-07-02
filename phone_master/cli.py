"""Phone Master CLI - Command-line interface."""

import threading
import time
from pathlib import Path

import click
import requests
from typing import Optional
from tabulate import tabulate
from colorama import Fore, Style
from wcwidth import wcswidth, wcwidth as _wcwidth
from .adb import ADBManager
from .adb.app_names import AppNameResolver
from .app_stores import AppStoreManager
from .app_stores.uptodown import UptodownStore
from .config import Config
from .models import AppSource

# Google's brand colors, cycled to highlight apps Google Play can't manage.
GOOGLE_COLORS = [
    (66, 133, 244),   # blue
    (234, 67, 53),    # red
    (251, 188, 5),    # yellow
    (52, 168, 83),    # green
]


def _google_color(index: int) -> str:
    r, g, b = GOOGLE_COLORS[index % len(GOOGLE_COLORS)]
    return f"\033[38;2;{r};{g};{b}m"


def _truncate(text: str, max_width: int) -> str:
    """Truncate text to a max display width, accounting for wide (CJK) characters."""
    if wcswidth(text) <= max_width:
        return text

    ellipsis = "…"
    budget = max_width - wcswidth(ellipsis)
    width = 0
    result = []
    for ch in text:
        ch_width = max(_wcwidth(ch), 0)
        if width + ch_width > budget:
            break
        result.append(ch)
        width += ch_width
    return "".join(result) + ellipsis


def _run_with_spinner(message: str, func, *args, **kwargs):
    """Run a blocking call on a background thread while showing an elapsed-time spinner."""
    result = {}
    error = {}

    def target():
        try:
            result["value"] = func(*args, **kwargs)
        except Exception as e:
            error["value"] = e

    thread = threading.Thread(target=target)
    thread.start()

    frames = "|/-\\"
    i = 0
    start = time.time()
    while thread.is_alive():
        elapsed = time.time() - start
        click.echo(f"\r{Fore.CYAN}{message} {frames[i % len(frames)]} ({elapsed:.0f}s){Style.RESET_ALL}", nl=False)
        i += 1
        time.sleep(0.2)
    thread.join()

    elapsed = time.time() - start
    click.echo(f"\r{Fore.CYAN}{message} done ({elapsed:.0f}s){Style.RESET_ALL}" + " " * 10)

    if "value" in error:
        raise error["value"]
    return result.get("value")


def _download_with_progress(url: str, dest_path: Path) -> None:
    """Stream a download to dest_path with a live progress bar."""
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(dest_path, "wb") as f, click.progressbar(length=total, label="Downloading") as bar:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
                bar.update(len(chunk))


@click.group()
@click.version_option()
@click.pass_context
def main(ctx):
    """Phone Master - Android app management CLI."""
    ctx.ensure_object(dict)
    ctx.obj['config'] = Config.from_file()


@main.command()
@click.pass_context
def devices(ctx):
    """List connected Android devices."""
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path)
        
        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No devices connected{Style.RESET_ALL}")
            return
        
        click.echo(f"{Fore.GREEN}✓ Device connected{Style.RESET_ALL}")
        click.echo(f"  Serial: {adb.device_serial}")
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command()
@click.option(
    '--source',
    type=click.Choice(['google_play', 'sideload', 'all']),
    default='all',
    help='Filter by install source'
)
@click.option(
    '--all-apps',
    is_flag=True,
    help='Include preinstalled system apps'
)
@click.pass_context
def list_apps(ctx, source, all_apps):
    """List installed apps on device."""
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)

        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return

        click.echo(f"{Fore.CYAN}Fetching installed apps...{Style.RESET_ALL}")
        apps = adb.get_installed_apps(third_party_only=not all_apps)

        # Chrome WebAPKs are auto-generated wrappers around "Add to Home Screen"
        # websites, not real installable apps - noise for this tool's purposes.
        apps = [app for app in apps if not app.package_name.startswith("org.chromium.webapk.")]

        if not apps:
            click.echo("No apps found")
            return

        # Filter by source if specified
        if source != 'all':
            apps = [app for app in apps if app.source.value == source]

        # Not-on-Play apps first (what this tool is for), alphabetical within each group
        apps.sort(key=lambda app: (app.source == AppSource.GOOGLE_PLAY, app.package_name.lower()))

        known_names = {a['package_name']: a['app_name'] for a in config.managed_apps}
        resolver = AppNameResolver(config.cache_dir, known_names)
        names = resolver.resolve_many([app.package_name for app in apps])

        # Prepare table data - flag apps Google Play can't manage (sideloaded)
        table_data = [
            [
                _truncate(names.get(app.package_name, app.package_name), 40),
                app.version,
                "" if app.source == AppSource.GOOGLE_PLAY else "not on Play"
            ]
            for app in apps
        ]

        table_str = tabulate(table_data, headers=["Name", "Version", ""], tablefmt="simple")

        # Highlight not-on-Play rows using Google's brand colors, cycled per row.
        # Colored after formatting (not in the cells) since tabulate counts ANSI
        # escape codes toward column width and would otherwise misalign columns.
        lines = table_str.split("\n")
        color_index = 0
        for i, line in enumerate(lines):
            data_row = i - 2  # header + separator line precede the data rows
            if 0 <= data_row < len(apps) and apps[data_row].source != AppSource.GOOGLE_PLAY:
                click.echo(f"{_google_color(color_index)}{line}{Style.RESET_ALL}")
                color_index += 1
            else:
                click.echo(line)

        sideload_count = sum(1 for app in apps if app.source != AppSource.GOOGLE_PLAY)
        click.echo(f"\n{Fore.GREEN}Total: {len(apps)} apps{Style.RESET_ALL} ({sideload_count} not manageable via Google Play)")
    
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command()
@click.option('--query', prompt='Search query', help='App name or package to search')
@click.option(
    '--store',
    type=click.Choice(['google_play', 'apkpure', 'chinese_store', 'all']),
    default='all',
    help='App store to search'
)
@click.pass_context
def search(ctx, query, store):
    """Search for app in app stores."""
    try:
        store_manager = AppStoreManager()
        
        # Map store name to AppSource
        stores_map = {
            'google_play': [AppSource.GOOGLE_PLAY],
            'apkpure': [AppSource.APKPURE],
            'chinese_store': [AppSource.CHINESE_STORE],
            'all': None
        }
        
        click.echo(f"{Fore.CYAN}Searching for '{query}'...{Style.RESET_ALL}")
        results = store_manager.search_app(query, stores_map.get(store))
        
        if not results:
            click.echo("No apps found")
            return
        
        table_data = [
            [app.app_name, app.package_name, app.source.value]
            for app in results
        ]
        
        click.echo(tabulate(
            table_data,
            headers=["App Name", "Package", "Store"],
            tablefmt="grid"
        ))
    
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command()
@click.argument('package_name')
@click.argument('apk_path', type=click.Path(exists=True))
@click.option('--reinstall', '-r', is_flag=True, help='Force reinstall')
@click.pass_context
def install(ctx, package_name, apk_path, reinstall):
    """Install APK on device."""
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)
        
        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return
        
        click.echo(f"{Fore.CYAN}Installing {package_name}...{Style.RESET_ALL}")
        
        if adb.install_apk(apk_path, package_name, reinstall):
            click.echo(f"{Fore.GREEN}✓ Installation successful{Style.RESET_ALL}")
        else:
            click.echo(f"{Fore.RED}✗ Installation failed{Style.RESET_ALL}")
    
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command()
@click.argument('package_name')
@click.pass_context
def uninstall(ctx, package_name):
    """Uninstall app from device."""
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)
        
        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return
        
        if not click.confirm(f"Uninstall {package_name}?"):
            return
        
        click.echo(f"{Fore.CYAN}Uninstalling {package_name}...{Style.RESET_ALL}")
        
        if adb.uninstall_app(package_name):
            click.echo(f"{Fore.GREEN}✓ Uninstallation successful{Style.RESET_ALL}")
        else:
            click.echo(f"{Fore.RED}✗ Uninstallation failed{Style.RESET_ALL}")
    
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command()
@click.argument('package_name')
@click.pass_context
def update(ctx, package_name):
    """Download and install the latest version of a managed app.

    Resolves the app's configured download_page (see managed_apps in
    .phone-master.yaml) via a headless browser, downloads the APK, and
    installs it on the connected device.
    """
    try:
        config = ctx.obj['config']
        app_config = next(
            (a for a in config.managed_apps if a['package_name'] == package_name),
            None
        )
        if not app_config:
            click.echo(f"{Fore.RED}✗ {package_name} is not in managed_apps (see .phone-master.yaml){Style.RESET_ALL}")
            return

        download_page = app_config.get('download_page')
        if not download_page:
            click.echo(
                f"{Fore.RED}✗ No download_page configured for {app_config['app_name']} — "
                f"add one to managed_apps in .phone-master.yaml{Style.RESET_ALL}"
            )
            return

        adb = ADBManager(config.adb_path, config.device_serial)
        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return

        installed_apps = adb.get_installed_apps(third_party_only=False)
        current = next((a for a in installed_apps if a.package_name == package_name), None)
        current_version = current.version if current else "not installed"
        click.echo(f"{Fore.CYAN}{app_config['app_name']} ({package_name}): installed version {current_version}{Style.RESET_ALL}")

        store = UptodownStore()
        version, download_url = _run_with_spinner(
            "Resolving latest version and download link", store.get_latest, download_page
        )
        click.echo(f"Latest available: {version or 'unknown'}")

        Path(config.download_dir).mkdir(parents=True, exist_ok=True)
        dest_path = Path(config.download_dir) / f"{package_name}-{version or 'latest'}.apk"
        _download_with_progress(download_url, dest_path)

        success = _run_with_spinner(
            "Installing on device", adb.install_apk, str(dest_path), package_name, True
        )

        if success:
            click.echo(f"{Fore.GREEN}✓ {app_config['app_name']} updated to {version or 'latest'}{Style.RESET_ALL}")
        else:
            click.echo(f"{Fore.RED}✗ Installation failed{Style.RESET_ALL}")

    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command()
@click.pass_context
def check_updates(ctx):
    """Check managed apps for updates, then choose which ones to install."""
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)

        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return

        checkable = [a for a in config.managed_apps if a.get('download_page')]
        skipped = [a for a in config.managed_apps if not a.get('download_page')]
        for app_config in skipped:
            click.echo(f"{Fore.YELLOW}⚠ {app_config['app_name']}: no automated source configured, skipping{Style.RESET_ALL}")

        if not checkable:
            click.echo("No managed apps have an automated source configured.")
            return

        installed_apps = adb.get_installed_apps(third_party_only=False)
        installed_by_pkg = {a.package_name: a for a in installed_apps}

        store = UptodownStore()
        pages = [a['download_page'] for a in checkable]
        results = _run_with_spinner(
            f"Checking {len(pages)} managed app(s) for updates", store.get_latest_batch, pages
        )

        candidates = []
        for app_config in checkable:
            result = results.get(app_config['download_page'])
            if isinstance(result, Exception):
                click.echo(f"{Fore.RED}✗ {app_config['app_name']}: {result}{Style.RESET_ALL}")
                continue

            version, download_url = result
            current = installed_by_pkg.get(app_config['package_name'])
            current_version = current.version if current else "not installed"

            if version and version != current_version:
                candidates.append({
                    "app_config": app_config,
                    "current_version": current_version,
                    "latest_version": version,
                    "download_url": download_url,
                })

        if not candidates:
            click.echo(f"{Fore.GREEN}All apps are up to date!{Style.RESET_ALL}")
            return

        table_data = [
            [i + 1, c["app_config"]["app_name"], c["current_version"], c["latest_version"]]
            for i, c in enumerate(candidates)
        ]
        click.echo("\n" + tabulate(table_data, headers=["#", "App", "Current", "Latest"], tablefmt="simple"))

        try:
            selection = click.prompt(
                "\nSelect apps to update (comma-separated numbers, 'all', or 'none')",
                default="none"
            )
        except (click.Abort, EOFError):
            click.echo("\nNo selection made, aborting.")
            return
        selection = selection.strip().lower()
        if selection == "none":
            return
        elif selection == "all":
            chosen = candidates
        else:
            indices = [int(x.strip()) - 1 for x in selection.split(",") if x.strip()]
            chosen = [candidates[i] for i in indices if 0 <= i < len(candidates)]

        if not chosen:
            click.echo("Nothing selected.")
            return

        Path(config.download_dir).mkdir(parents=True, exist_ok=True)

        for c in chosen:
            app_config = c["app_config"]
            package_name = app_config["package_name"]
            click.echo(f"\n{Fore.CYAN}{app_config['app_name']}: {c['current_version']} → {c['latest_version']}{Style.RESET_ALL}")

            dest_path = Path(config.download_dir) / f"{package_name}-{c['latest_version']}.apk"
            _download_with_progress(c["download_url"], dest_path)

            success = _run_with_spinner("Installing on device", adb.install_apk, str(dest_path), package_name, True)
            if success:
                click.echo(f"{Fore.GREEN}✓ {app_config['app_name']} updated to {c['latest_version']}{Style.RESET_ALL}")
            else:
                click.echo(f"{Fore.RED}✗ {app_config['app_name']} installation failed{Style.RESET_ALL}")

    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command()
@click.pass_context
def config_show(ctx):
    """Show current configuration."""
    try:
        config = ctx.obj['config']
        click.echo(f"{Fore.CYAN}Current Configuration:{Style.RESET_ALL}")
        click.echo(f"  ADB Path: {config.adb_path}")
        click.echo(f"  Device Serial: {config.device_serial or 'auto-detect'}")
        click.echo(f"  Auto-update: {config.auto_update}")
        click.echo(f"  Download Directory: {config.download_dir}")
        click.echo(f"\n{Fore.CYAN}Managed Apps:{Style.RESET_ALL}")
        for app in config.managed_apps:
            click.echo(f"  - {app['app_name']} ({app['package_name']})")
    
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


if __name__ == '__main__':
    main()
