"""Phone Master CLI - Command-line interface."""

import threading
import time
import posixpath
from pathlib import Path

import click
import requests
from typing import Optional
from tabulate import tabulate
from colorama import Fore, Style
from wcwidth import wcswidth, wcwidth as _wcwidth
from .adb import ADBManager
from .adb.app_names import AppNameResolver
from .adb.apk_finder import find_candidate_paths, inspect_apk, read_package_name
from .app_stores import AppStoreManager
from .app_stores.tencent_myapp import TencentMyAppStore
from .app_stores.uptodown import UptodownStore
from .config import Config
from .models import AppSource
from .version import compare_versions, is_newer

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


def _download_many_with_progress(jobs: list) -> None:
    """Download multiple (url, dest_path) pairs concurrently with one aggregate progress bar.

    Downloads are network-bound and independent, so there's no reason to make
    the user wait for one to finish before starting the next (unlike adb
    installs, which stay sequential since they all go through the same device).
    """
    if not jobs:
        return
    if len(jobs) == 1:
        _download_with_progress(*jobs[0])
        return

    responses = []
    total = 0
    for url, dest_path in jobs:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        total += int(r.headers.get("content-length", 0))
        responses.append((r, dest_path))

    lock = threading.Lock()
    with click.progressbar(length=total, label=f"Downloading {len(jobs)} apps") as bar:

        def worker(response, dest_path):
            with response, open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    f.write(chunk)
                    with lock:
                        bar.update(len(chunk))

        threads = [threading.Thread(target=worker, args=(r, dest_path)) for r, dest_path in responses]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


def _get_installed_apps_with_progress(adb, third_party_only, label="Reading installed apps"):
    """adb.get_installed_apps runs one `dumpsys` call per package - slow and
    silent otherwise, so this drives a determinate progress bar over it."""
    total = len(adb.client.get_installed_packages(third_party_only))
    with click.progressbar(length=total, label=label) as bar:
        return adb.get_installed_apps(third_party_only, on_progress=lambda: bar.update(1))


def _resolve_names_with_progress(resolver, package_names, label="Resolving app names"):
    """resolver.resolve_many hits the network once per uncached package - can
    be slow on a cold cache, so this drives a determinate progress bar over it."""
    with click.progressbar(length=len(package_names), label=label) as bar:
        return resolver.resolve_many(package_names, on_progress=lambda: bar.update(1))


def _scan_and_clean_local_apks(adb, config, package_names):
    """Find stray .apk files for the given packages already sitting on the device.

    Outdated ones (not newer than what's installed) are deleted on the spot -
    they're leftover self-update files with no further use. Returns the
    highest-version surviving candidate per package: package_name -> info.
    """
    installed_apps = adb.get_installed_apps(third_party_only=False)
    installed_by_pkg = {a.package_name: a for a in installed_apps}

    paths = find_candidate_paths(adb.client, package_names)
    if not paths:
        return {}

    Path(config.cache_dir).mkdir(parents=True, exist_ok=True)
    best_by_pkg = {}
    for path in paths:
        info = inspect_apk(adb.client, path, config.cache_dir)
        if not info or info["package_name"] not in package_names:
            continue

        current = installed_by_pkg.get(info["package_name"])
        current_version = current.version if current else None

        if not is_newer(info["version_name"], current_version):
            adb.client.remove_file(path)
            click.echo(
                f"{Fore.YELLOW}  Removed outdated local APK: {path} "
                f"(v{info['version_name']}){Style.RESET_ALL}"
            )
            continue

        existing = best_by_pkg.get(info["package_name"])
        if not existing or compare_versions(info["version_name"], existing["version_name"]) > 0:
            best_by_pkg[info["package_name"]] = info

    return best_by_pkg


def _dictionary_directories(source_dir: str):
    """Return visible dictionary directories in stable display order."""
    source = Path(source_dir).expanduser()
    if not source.is_dir():
        raise click.ClickException(f"Dictionary source directory does not exist: {source}")
    return sorted(
        (path for path in source.iterdir() if path.is_dir() and not path.name.startswith(".")),
        key=lambda path: path.name.casefold(),
    )


def _local_size(path: Path) -> int:
    """Return the combined size of all files below path."""
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _color_progress(iterable=None, length=None, label="Working"):
    """Create the shared high-contrast progress bar used by dictionary commands."""
    return click.progressbar(
        iterable=iterable,
        length=length,
        label=f"{Fore.CYAN}{label}{Style.RESET_ALL}",
        color=True,
        bar_template=(
            "%(label)s  " + Fore.MAGENTA + "[%(bar)s]" + Fore.YELLOW
            + " %(info)s" + Style.RESET_ALL
        ),
    )


def _push_dictionary_with_progress(adb, dictionary: Path, phone_root: str) -> bool:
    """Push one dictionary while tracking bytes appearing at its destination."""
    total = max(_local_size(dictionary), 1)
    remote_path = posixpath.join(phone_root, dictionary.name)
    state = {"success": False, "error": None}

    def push():
        try:
            state["success"] = adb.client.push_file(str(dictionary), f"{phone_root.rstrip('/')}/")
        except Exception as exc:
            state["error"] = exc

    worker = threading.Thread(target=push)
    worker.start()
    shown = 0
    with _color_progress(length=total, label=f"Pushing {dictionary.name}") as bar:
        while worker.is_alive():
            current = min(adb.client.directory_size(remote_path), total)
            if current > shown:
                bar.update(current - shown)
                shown = current
            time.sleep(0.4)
        worker.join()
        if state["success"] and shown < total:
            bar.update(total - shown)
    if state["error"]:
        raise state["error"]
    return state["success"]


def _select_items(items, selection: str):
    """Resolve an all/none/comma-separated numbered selection."""
    value = selection.strip().lower()
    if value == "all":
        return items
    if value in {"", "none"}:
        return []

    try:
        numbers = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise click.BadParameter("use comma-separated numbers, 'all', or 'none'") from exc

    invalid = [number for number in numbers if not 1 <= number <= len(items)]
    if invalid:
        raise click.BadParameter(
            f"selection out of range: {', '.join(str(number) for number in invalid)}"
        )
    # Preserve display order and avoid copying duplicates.
    selected = set(numbers)
    return [item for index, item in enumerate(items, start=1) if index in selected]


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

        apps = _get_installed_apps_with_progress(adb, not all_apps)

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
        names = _resolve_names_with_progress(resolver, [app.package_name for app in apps])

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
@click.argument('apk_path', type=click.Path(exists=True))
@click.option('--reinstall', '-r', is_flag=True, help='Force reinstall')
@click.pass_context
def install(ctx, apk_path, reinstall):
    """Install APK on device."""
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)

        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return

        package_name = read_package_name(apk_path) or Path(apk_path).name
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

    Checks for a self-downloaded update already sitting on the device first
    (some apps fetch their own update APK without any app store); only if
    none is found does it fall back to the configured download_page,
    resolved via a headless browser since the real link is JS-gated.
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

        adb = ADBManager(config.adb_path, config.device_serial)
        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return

        installed_apps = _get_installed_apps_with_progress(adb, False)
        current = next((a for a in installed_apps if a.package_name == package_name), None)
        current_version = current.version if current else "not installed"
        click.echo(f"{Fore.CYAN}{app_config['app_name']} ({package_name}): installed version {current_version}{Style.RESET_ALL}")

        local_best = _run_with_spinner(
            "Checking device storage for a local update", _scan_and_clean_local_apks,
            adb, config, [package_name]
        )
        local_info = local_best.get(package_name)

        if local_info:
            version = local_info["version_name"]
            click.echo(f"Found local update already on device: {version}")
            success = _run_with_spinner(
                "Installing from device", adb.client.install_from_device_path,
                local_info["device_path"], True
            )
        else:
            download_page = app_config.get('download_page')
            if not download_page:
                click.echo(
                    f"{Fore.RED}✗ No local update found and no download_page configured for "
                    f"{app_config['app_name']} — add one to managed_apps in .phone-master.yaml{Style.RESET_ALL}"
                )
                return

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
    """Check managed apps for updates, then choose which ones to install.

    A self-downloaded update already on the device (see `find-apks`) is always
    preferred over fetching one from the web. Anything picked up from the web
    is cross-checked against 应用宝 as an authoritative version source.
    """
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)

        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return

        installed_apps = _get_installed_apps_with_progress(adb, False)
        installed_by_pkg = {a.package_name: a for a in installed_apps}
        all_packages = [a['package_name'] for a in config.managed_apps]

        local_best = _run_with_spinner(
            "Checking device storage for self-downloaded updates",
            _scan_and_clean_local_apks, adb, config, all_packages
        )

        need_remote = [a for a in config.managed_apps if a['package_name'] not in local_best]
        checkable = [a for a in need_remote if a.get('download_page')]
        skipped = [a for a in need_remote if not a.get('download_page')]
        for app_config in skipped:
            click.echo(f"{Fore.YELLOW}⚠ {app_config['app_name']}: no local file or automated source found, skipping{Style.RESET_ALL}")

        remote_results = {}
        if checkable:
            store = UptodownStore()
            pages = [a['download_page'] for a in checkable]
            remote_results = _run_with_spinner(
                f"Checking {len(pages)} app(s) against Uptodown", store.get_latest_batch, pages
            )

        candidates = []
        for app_config in config.managed_apps:
            package_name = app_config['package_name']
            current = installed_by_pkg.get(package_name)
            current_version = current.version if current else "not installed"

            if package_name in local_best:
                info = local_best[package_name]
                candidates.append({
                    "app_config": app_config,
                    "current_version": current_version,
                    "latest_version": info["version_name"],
                    "source": "local file",
                    "device_path": info["device_path"],
                })
            elif app_config.get('download_page'):
                result = remote_results.get(app_config['download_page'])
                if isinstance(result, Exception):
                    click.echo(f"{Fore.RED}✗ {app_config['app_name']}: {result}{Style.RESET_ALL}")
                    continue
                if result is None:
                    continue
                version, download_url = result
                if is_newer(version, current_version):
                    candidates.append({
                        "app_config": app_config,
                        "current_version": current_version,
                        "latest_version": version,
                        "source": "uptodown",
                        "download_url": download_url,
                    })

        if not candidates:
            click.echo(f"{Fore.GREEN}All apps are up to date!{Style.RESET_ALL}")
            return

        # Cross-check against a first-party Chinese app store for confidence,
        # regardless of which source the candidate version came from.
        myapp = TencentMyAppStore()
        confirmed = _run_with_spinner(
            "Confirming versions with 应用宝", myapp.get_version_batch,
            [c["app_config"]["package_name"] for c in candidates]
        )
        for c in candidates:
            c["confirmed_version"] = confirmed.get(c["app_config"]["package_name"])

        table_data = []
        for i, c in enumerate(candidates):
            confirmed_version = c["confirmed_version"]
            if not confirmed_version:
                confirmed_display = "unavailable"
            elif confirmed_version == c["latest_version"]:
                confirmed_display = f"{confirmed_version} ✓"
            else:
                confirmed_display = f"{confirmed_version} (differs)"
            table_data.append([
                i + 1, c["app_config"]["app_name"], c["current_version"], c["latest_version"],
                c["source"], confirmed_display
            ])
        click.echo("\n" + tabulate(
            table_data,
            headers=["#", "App", "Current", "Latest", "Source", "Confirmed (应用宝)"],
            tablefmt="simple"
        ))

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

        local_chosen = [c for c in chosen if c["source"] == "local file"]
        remote_chosen = [c for c in chosen if c["source"] != "local file"]

        # Downloads are independent network transfers, so fetch them all at once
        # rather than making the user wait for each one before starting the next.
        # Anything sourced from a local file needs no download at all.
        if remote_chosen:
            for c in remote_chosen:
                c["dest_path"] = Path(config.download_dir) / f"{c['app_config']['package_name']}-{c['latest_version']}.apk"
            click.echo(f"\n{Fore.CYAN}Downloading: {', '.join(c['app_config']['app_name'] for c in remote_chosen)}{Style.RESET_ALL}")
            _download_many_with_progress([(c["download_url"], c["dest_path"]) for c in remote_chosen])

        if local_chosen:
            click.echo(f"\n{Fore.CYAN}Already on device: {', '.join(c['app_config']['app_name'] for c in local_chosen)}{Style.RESET_ALL}")

        # Installs all go through the same adb-connected device, so those stay sequential.
        for c in chosen:
            app_config = c["app_config"]
            package_name = app_config["package_name"]
            click.echo(f"\n{Fore.CYAN}{app_config['app_name']}: {c['current_version']} → {c['latest_version']}{Style.RESET_ALL}")

            if c["source"] == "local file":
                success = _run_with_spinner(
                    "Installing from device", adb.client.install_from_device_path, c["device_path"], True
                )
            else:
                success = _run_with_spinner(
                    "Installing on device", adb.install_apk, str(c["dest_path"]), package_name, True
                )

            if success:
                click.echo(f"{Fore.GREEN}✓ {app_config['app_name']} updated to {c['latest_version']}{Style.RESET_ALL}")
            else:
                click.echo(f"{Fore.RED}✗ {app_config['app_name']} installation failed{Style.RESET_ALL}")

    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


@main.command(name="find-apks")
@click.pass_context
def find_apks(ctx):
    """Find APK files already on the device that aren't installed (or are newer).

    Searches Download folders and each managed app's own data folder - some
    apps (e.g. self-updating Chinese apps) download their own update APK there
    without going through any app store. Anything not newer than what's
    already installed is deleted on the spot as a stale leftover; anything
    else is listed so you can install it directly from the device, no
    download needed.
    """
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)

        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return

        managed_packages = [a['package_name'] for a in config.managed_apps]
        known_names = {a['package_name']: a['app_name'] for a in config.managed_apps}

        paths = _run_with_spinner(
            "Searching Download folders and managed apps' data folders",
            find_candidate_paths, adb.client, managed_packages
        )

        if not paths:
            click.echo("No APK files found.")
            return

        installed_apps = _get_installed_apps_with_progress(adb, False)
        installed_by_pkg = {a.package_name: a for a in installed_apps}

        Path(config.cache_dir).mkdir(parents=True, exist_ok=True)
        kept = []
        for path in paths:
            info = _run_with_spinner(
                f"Inspecting {Path(path).name}", inspect_apk, adb.client, path, config.cache_dir
            )
            if not info:
                continue

            current = installed_by_pkg.get(info["package_name"])
            current_version = current.version if current else None

            if not is_newer(info["version_name"], current_version):
                adb.client.remove_file(path)
                click.echo(f"{Fore.YELLOW}Removed outdated: {path} (v{info['version_name']}){Style.RESET_ALL}")
                continue

            kept.append({
                "path": path,
                "package_name": info["package_name"],
                "version_name": info["version_name"],
                "current_version": current_version or "not installed",
            })

        if not kept:
            click.echo(f"{Fore.GREEN}Nothing worth keeping - no file was newer than what's installed.{Style.RESET_ALL}")
            return

        table_data = [
            [i + 1, known_names.get(k["package_name"], k["package_name"]), k["current_version"], k["version_name"], k["path"]]
            for i, k in enumerate(kept)
        ]
        click.echo("\n" + tabulate(table_data, headers=["#", "App", "Installed", "Found", "Path"], tablefmt="simple"))

        try:
            selection = click.prompt(
                "\nSelect files to install (comma-separated numbers, 'all', or 'none')",
                default="none"
            )
        except (click.Abort, EOFError):
            click.echo("\nNo selection made, aborting.")
            return
        selection = selection.strip().lower()
        if selection == "none":
            return
        elif selection == "all":
            chosen = kept
        else:
            indices = [int(x.strip()) - 1 for x in selection.split(",") if x.strip()]
            chosen = [kept[i] for i in indices if 0 <= i < len(kept)]

        for k in chosen:
            app_label = known_names.get(k["package_name"], k["package_name"])
            click.echo(f"\n{Fore.CYAN}Installing {app_label} ({k['version_name']}){Style.RESET_ALL}")
            success = _run_with_spinner(
                "Installing from device", adb.client.install_from_device_path, k["path"], True
            )
            if success:
                click.echo(f"{Fore.GREEN}✓ Installed{Style.RESET_ALL}")
            else:
                click.echo(f"{Fore.RED}✗ Installation failed{Style.RESET_ALL}")

    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


def _list_local_dictionaries(config):
    with _color_progress(length=1, label="Scanning Mac dictionaries") as bar:
        dictionaries = _dictionary_directories(config.dictionary_source_dir)
        bar.update(1)
    return dictionaries


def _connected_adb(config):
    adb = ADBManager(config.adb_path, config.device_serial)
    if not adb.check_device_connection():
        raise click.ClickException(
            "No authorized device connected. Unlock the phone and accept its USB-debugging prompt."
        )
    return adb


def _show_dictionaries(config, location):
    if location == "mac":
        dictionaries = _list_local_dictionaries(config)
        names = [dictionary.name for dictionary in dictionaries]
        display_path = config.dictionary_source_dir
    else:
        adb = _connected_adb(config)
        with _color_progress(length=1, label="Scanning phone dictionaries") as bar:
            adb.client.create_directory(config.dictionary_phone_dir)
            paths = adb.client.list_directories(config.dictionary_phone_dir)
            bar.update(1)
        names = sorted((posixpath.basename(path) for path in paths), key=str.casefold)
        display_path = config.dictionary_phone_dir

    click.echo(f"{Fore.CYAN}Dictionaries on {location} ({display_path}):{Style.RESET_ALL}")
    if not names:
        click.echo("  None found.")
    for index, name in enumerate(names, start=1):
        click.echo(f"  {index}. {name}")
    return names


def _push_dictionaries(config, selection):
    try:
        dictionaries = _list_local_dictionaries(config)
        if not dictionaries:
            click.echo(f"No dictionaries found in {config.dictionary_source_dir}")
            return

        click.echo(f"{Fore.CYAN}Dictionaries on mac ({config.dictionary_source_dir}):{Style.RESET_ALL}")
        for index, dictionary in enumerate(dictionaries, start=1):
            click.echo(f"  {index}. {dictionary.name}")

        chosen = _select_items(dictionaries, selection)
        if not chosen:
            click.echo("Nothing selected.")
            return

        adb = _connected_adb(config)
        adb.client.create_directory(config.dictionary_phone_dir)
        failures = []
        for dictionary in chosen:
            click.echo(f"\n{Fore.CYAN}Copying {dictionary.name}...{Style.RESET_ALL}")
            success = _push_dictionary_with_progress(adb, dictionary, config.dictionary_phone_dir)
            if success:
                click.echo(f"{Fore.GREEN}✓ Copied {dictionary.name}{Style.RESET_ALL}")
            else:
                failures.append(dictionary.name)
                click.echo(f"{Fore.RED}✗ Failed to copy {dictionary.name}{Style.RESET_ALL}")

        if failures:
            raise click.ClickException(f"Failed dictionaries: {', '.join(failures)}")
        click.echo(
            f"\n{Fore.GREEN}✓ Copied {len(chosen)} dictionary/directories to "
            f"{config.dictionary_phone_dir}{Style.RESET_ALL}"
        )

    except click.ClickException:
        raise
    except (click.Abort, EOFError):
        click.echo("\nNo selection made, aborting.")
    except click.BadParameter:
        raise
    except Exception as e:
        raise click.ClickException(str(e)) from e


@main.group(name="dict")
def dictionary_commands():
    """List and copy dictionaries between the Mac and phone."""


@dictionary_commands.command(name="list")
@click.argument("location", type=click.Choice(["mac", "phone"]), default="mac", required=False)
@click.pass_context
def dict_list(ctx, location):
    """List dictionaries on the Mac (default) or phone."""
    _show_dictionaries(ctx.obj["config"], location)


@dictionary_commands.command(name="push")
@click.argument("selection")
@click.pass_context
def dict_push(ctx, selection):
    """Push a dictionary number, comma-separated numbers, or all to the phone."""
    _push_dictionaries(ctx.obj["config"], selection)


@main.command(name="copy-dictionaries", hidden=True)
@click.option("--select", "selection")
@click.pass_context
def copy_dictionaries(ctx, selection):
    """Compatibility alias for `phonemaster dict push`."""
    if selection is None:
        selection = click.prompt(
            "Select dictionaries to copy (comma-separated numbers, 'all', or 'none')",
            default="none",
        )
    _push_dictionaries(ctx.obj["config"], selection)


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
        click.echo(f"  Dictionary Source Directory: {config.dictionary_source_dir}")
        click.echo(f"  Dictionary Phone Directory: {config.dictionary_phone_dir}")
        click.echo(f"\n{Fore.CYAN}Managed Apps:{Style.RESET_ALL}")
        for app in config.managed_apps:
            click.echo(f"  - {app['app_name']} ({app['package_name']})")
    
    except Exception as e:
        click.echo(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")


if __name__ == '__main__':
    main()
