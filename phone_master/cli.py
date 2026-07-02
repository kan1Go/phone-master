"""Phone Master CLI - Command-line interface."""

import click
from typing import Optional
from tabulate import tabulate
from colorama import Fore, Style
from .adb import ADBManager
from .app_stores import AppStoreManager
from .config import Config
from .models import AppSource


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
    type=click.Choice(['google_play', 'apkpure', 'chinese_store', 'all']),
    default='all',
    help='App store to check'
)
@click.pass_context
def list_apps(ctx, source):
    """List installed apps on device."""
    try:
        config = ctx.obj['config']
        import sys
        print(f"DEBUG: config.adb_path={config.adb_path}", file=sys.stderr)
        print(f"DEBUG: config.device_serial={config.device_serial}", file=sys.stderr)
        adb = ADBManager(config.adb_path, config.device_serial)
        print(f"DEBUG: adb.device_serial={adb.device_serial}", file=sys.stderr)
        
        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return
        
        click.echo(f"{Fore.CYAN}Fetching installed apps...{Style.RESET_ALL}")
        apps = adb.get_installed_apps()
        
        if not apps:
            click.echo("No apps found")
            return
        
        # Filter by source if specified
        if source != 'all':
            apps = [app for app in apps if app.source.value == source]
        
        # Prepare table data
        table_data = [
            [app.app_name, app.package_name, app.version, app.source.value]
            for app in apps
        ]
        
        click.echo(tabulate(
            table_data,
            headers=["App Name", "Package", "Version", "Source"],
            tablefmt="grid"
        ))
        click.echo(f"\n{Fore.GREEN}Total: {len(apps)} apps{Style.RESET_ALL}")
    
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
@click.pass_context
def check_updates(ctx):
    """Check for app updates for managed apps."""
    try:
        config = ctx.obj['config']
        adb = ADBManager(config.adb_path, config.device_serial)
        store_manager = AppStoreManager()
        
        if not adb.check_device_connection():
            click.echo(f"{Fore.RED}✗ No device connected{Style.RESET_ALL}")
            return
        
        click.echo(f"{Fore.CYAN}Checking for updates...{Style.RESET_ALL}")
        
        installed_apps = adb.get_installed_apps()
        updates_available = []
        
        for app_config in config.managed_apps:
            package = app_config['package_name']
            app = next((a for a in installed_apps if a.package_name == package), None)
            
            if app:
                update = store_manager.check_updates(package, app.version)
                if update:
                    updates_available.append(update)
        
        if not updates_available:
            click.echo(f"{Fore.GREEN}All apps are up to date!{Style.RESET_ALL}")
            return
        
        table_data = [
            [u.package_name, u.current_version, u.new_version, u.source.value]
            for u in updates_available
        ]
        
        click.echo(tabulate(
            table_data,
            headers=["Package", "Current", "Latest", "Store"],
            tablefmt="grid"
        ))
        click.echo(f"\n{Fore.YELLOW}{len(updates_available)} updates available{Style.RESET_ALL}")
    
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
