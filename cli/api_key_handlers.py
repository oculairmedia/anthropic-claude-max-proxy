"""API key management handlers for CLI"""

import __main__
from rich.prompt import Prompt, Confirm
from rich.table import Table
from utils.api_key_storage import APIKeyStorage


def generate_api_key(storage: APIKeyStorage, console, debug: bool = False):
    """Generate a new API key with user-provided name"""
    if debug and hasattr(__main__, '_proxy_debug_logger'):
        __main__._proxy_debug_logger.debug("[CLI] Starting API key generation")

    console.print("\n[bold]Generate New API Key[/bold]\n")

    # Get key name from user
    name = Prompt.ask("Enter a name for this key").strip()

    if not name:
        console.print("[red]Key name cannot be empty.[/red]")
        console.print("\nPress Enter to continue...")
        input()
        return

    # Generate the key
    key_id, plaintext_key = storage.create_key(name)

    console.print(f"\n[green]API Key generated successfully![/green]\n")
    console.print(f"[bold yellow]IMPORTANT: Copy this key now. It will NOT be shown again![/bold yellow]\n")
    console.print(f"[cyan]{plaintext_key}[/cyan]\n")

    console.print("[bold]Key Details:[/bold]")
    console.print(f"  ID: {key_id}")
    console.print(f"  Name: {name}")
    console.print(f"  Prefix: {plaintext_key[:12]}...\n")

    console.print("[bold]Usage:[/bold]")
    console.print("  Add header to API requests:")
    console.print(f"  [dim]Authorization: Bearer {plaintext_key[:20]}...[/dim]")
    console.print("  Or use X-API-Key header:")
    console.print(f"  [dim]X-API-Key: {plaintext_key[:20]}...[/dim]\n")

    # Offer to copy to clipboard
    if _try_clipboard_available():
        if Confirm.ask("Copy key to clipboard?", default=True):
            if _copy_to_clipboard(plaintext_key):
                console.print("[green]Key copied to clipboard![/green]")
            else:
                console.print("[yellow]Could not copy to clipboard. Please copy manually.[/yellow]")

    if debug and hasattr(__main__, '_proxy_debug_logger'):
        __main__._proxy_debug_logger.debug(f"[CLI] Generated API key: id={key_id}, name={name}")

    console.print("\nPress Enter to continue...")
    input()


def list_api_keys(storage: APIKeyStorage, console, debug: bool = False):
    """Display all API keys in a table format"""
    if debug and hasattr(__main__, '_proxy_debug_logger'):
        __main__._proxy_debug_logger.debug("[CLI] Listing API keys")

    keys = storage.list_keys()

    if not keys:
        console.print("\n[yellow]No API keys found.[/yellow]")
        console.print("Generate a new key with option 1.")
        console.print("\nPress Enter to continue...")
        input()
        return

    table = Table(title="API Keys")
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", style="cyan")
    table.add_column("Key Prefix", style="green")
    table.add_column("Created", style="dim")
    table.add_column("Last Used", style="dim")
    table.add_column("Uses", justify="right")

    for idx, key_data in enumerate(keys, 1):
        created = key_data.get("created_at", "")[:10] if key_data.get("created_at") else "N/A"
        last_used = key_data.get("last_used_at", "")[:10] if key_data.get("last_used_at") else "Never"
        table.add_row(
            str(idx),
            key_data.get("name", "unnamed"),
            key_data.get("key_prefix", "") + "...",
            created,
            last_used,
            str(key_data.get("usage_count", 0))
        )

    console.print()
    console.print(table)
    console.print(f"\nTotal: {len(keys)} key(s)")
    console.print("\nPress Enter to continue...")
    input()


def delete_api_key(storage: APIKeyStorage, console, debug: bool = False):
    """Delete an API key with confirmation"""
    if debug and hasattr(__main__, '_proxy_debug_logger'):
        __main__._proxy_debug_logger.debug("[CLI] Starting API key deletion")

    keys = storage.list_keys()

    if not keys:
        console.print("\n[yellow]No API keys to delete.[/yellow]")
        console.print("\nPress Enter to continue...")
        input()
        return

    console.print("\n[bold]Delete API Key[/bold]")
    console.print("\nSelect a key to delete:\n")

    # Display numbered list
    for idx, key_data in enumerate(keys, 1):
        console.print(f" {idx}. {key_data['name']:20} ({key_data['key_prefix']}...)")
    console.print(" 0. Cancel\n")

    # Get selection
    choices = ["0"] + [str(i) for i in range(1, len(keys) + 1)]
    choice = Prompt.ask(f"Select key [0-{len(keys)}]", choices=choices)

    if choice == "0":
        console.print("Cancelled.")
        console.print("\nPress Enter to continue...")
        input()
        return

    selected_key = keys[int(choice) - 1]

    # Confirmation with warning
    console.print(f"\n[yellow]Warning:[/yellow] Deleting this key will immediately revoke access for any")
    console.print("applications using it.\n")

    if Confirm.ask(f'Delete key "{selected_key["name"]}"?', default=False):
        if storage.delete_key(selected_key["id"]):
            console.print(f'\n[green]Key "{selected_key["name"]}" deleted successfully.[/green]')
            if debug and hasattr(__main__, '_proxy_debug_logger'):
                __main__._proxy_debug_logger.debug(f"[CLI] Deleted API key: id={selected_key['id']}")
        else:
            console.print("[red]Failed to delete key.[/red]")
    else:
        console.print("\nDeletion cancelled.")

    console.print("\nPress Enter to continue...")
    input()


def rename_api_key(storage: APIKeyStorage, console, debug: bool = False):
    """Rename an existing API key"""
    if debug and hasattr(__main__, '_proxy_debug_logger'):
        __main__._proxy_debug_logger.debug("[CLI] Starting API key rename")

    keys = storage.list_keys()

    if not keys:
        console.print("\n[yellow]No API keys to rename.[/yellow]")
        console.print("\nPress Enter to continue...")
        input()
        return

    console.print("\n[bold]Rename API Key[/bold]")
    console.print("\nSelect a key to rename:\n")

    for idx, key_data in enumerate(keys, 1):
        console.print(f" {idx}. {key_data['name']:20} ({key_data['key_prefix']}...)")
    console.print(" 0. Cancel\n")

    choices = ["0"] + [str(i) for i in range(1, len(keys) + 1)]
    choice = Prompt.ask(f"Select key [0-{len(keys)}]", choices=choices)

    if choice == "0":
        console.print("Cancelled.")
        console.print("\nPress Enter to continue...")
        input()
        return

    selected_key = keys[int(choice) - 1]
    old_name = selected_key["name"]

    console.print(f"\nCurrent name: [cyan]{old_name}[/cyan]")
    new_name = Prompt.ask("Enter new name").strip()

    if not new_name:
        console.print("[red]Name cannot be empty.[/red]")
        console.print("\nPress Enter to continue...")
        input()
        return

    if storage.rename_key(selected_key["id"], new_name):
        console.print(f'\n[green]Key renamed from "{old_name}" to "{new_name}"[/green]')
        if debug and hasattr(__main__, '_proxy_debug_logger'):
            __main__._proxy_debug_logger.debug(f"[CLI] Renamed API key: id={selected_key['id']}, {old_name} -> {new_name}")
    else:
        console.print("[red]Failed to rename key.[/red]")

    console.print("\nPress Enter to continue...")
    input()


def copy_key_prefix(storage: APIKeyStorage, console, debug: bool = False):
    """Copy a key prefix to clipboard (for identification only)"""
    if debug and hasattr(__main__, '_proxy_debug_logger'):
        __main__._proxy_debug_logger.debug("[CLI] Starting copy key prefix")

    keys = storage.list_keys()

    if not keys:
        console.print("\n[yellow]No API keys found.[/yellow]")
        console.print("\nPress Enter to continue...")
        input()
        return

    if not _try_clipboard_available():
        console.print("\n[red]Clipboard functionality not available.[/red]")
        console.print("Please install pyperclip: pip install pyperclip")
        console.print("\nPress Enter to continue...")
        input()
        return

    console.print("\n[bold]Copy Key Prefix[/bold]")
    console.print("[dim]Note: Only the prefix is available. Full keys are shown only at creation.[/dim]\n")

    for idx, key_data in enumerate(keys, 1):
        console.print(f" {idx}. {key_data['name']:20} ({key_data['key_prefix']}...)")
    console.print(" 0. Cancel\n")

    choices = ["0"] + [str(i) for i in range(1, len(keys) + 1)]
    choice = Prompt.ask(f"Select key [0-{len(keys)}]", choices=choices)

    if choice == "0":
        console.print("Cancelled.")
        console.print("\nPress Enter to continue...")
        input()
        return

    selected_key = keys[int(choice) - 1]

    if _copy_to_clipboard(selected_key["key_prefix"]):
        console.print(f'\n[green]Copied prefix "{selected_key["key_prefix"]}" to clipboard![/green]')
        if debug and hasattr(__main__, '_proxy_debug_logger'):
            __main__._proxy_debug_logger.debug(f"[CLI] Copied key prefix to clipboard: {selected_key['key_prefix']}")
    else:
        console.print(f"[yellow]Could not copy. Prefix: {selected_key['key_prefix']}[/yellow]")

    console.print("\nPress Enter to continue...")
    input()


def _try_clipboard_available() -> bool:
    """Check if clipboard functionality is available"""
    try:
        import pyperclip
        return True
    except ImportError:
        return False


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard, returns True on success"""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False
