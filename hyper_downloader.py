#!/usr/bin/env python3
from typing import Optional, List, Dict
import subprocess
import sys
import json
import os
import shutil
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()
AUDIO_FORMAT = "mp3"
VIDEO_FORMAT = "mp4"
H264_CODEC = "avc1"
CONFIG_FILE = Path.home() / ".hyper_downloader_config.json"
DEFAULT_DIR  = str(Path.home() / "Downloads")


def load_saved_dir() -> str:
    try:
        data = json.loads(CONFIG_FILE.read_text())
        path = data.get("download_dir", DEFAULT_DIR)
        if os.path.isdir(path):
            return path
    except Exception:
        pass
    return DEFAULT_DIR


def save_dir(path: str) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps({"download_dir": path}))
    except Exception:
        pass


def browse_folders(start: str = str(Path.home())) -> Optional[str]:
    """
    Interactive folder browser — navigate directories like Finder in the terminal.
    Returns the selected folder path, or None if the user cancels with 0.
    """
    current = Path(start).expanduser().resolve()

    while True:
        console.clear()
        console.print(Panel(f"[bold cyan]📁 Choose Download Folder[/bold cyan]\n[dim]{current}[/dim]", expand=False))

        try:
            entries = sorted(
                [e for e in current.iterdir() if e.is_dir() and not e.name.startswith(".")],
                key=lambda e: e.name.lower(),
            )
        except PermissionError:
            console.print("[bold red]❌ Permission denied. Going back.[/bold red]")
            current = current.parent
            continue

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("ID", style="bold", justify="right", width=4)
        table.add_column("Folder")

        table.add_row("0",  "[bold red]✖  Cancel[/bold red]")
        table.add_row("00", f"[bold green]✔  Select this folder[/bold green]  [dim]{current}[/dim]")
        if current != current.parent:
            table.add_row("..", "[yellow]⬆  Go up[/yellow]")

        for i, entry in enumerate(entries, start=1):
            table.add_row(str(i), f"📂 {entry.name}")

        console.print(table)

        raw = Prompt.ask("\n[bold]Enter number / '..' / '00' to select / '0' to cancel[/bold]").strip()

        if raw == "0":
            return None

        if raw == "00":
            return str(current)

        if raw == "..":
            current = current.parent
            continue

        try:
            idx = int(raw)
            if 1 <= idx <= len(entries):
                current = entries[idx - 1]
            else:
                console.print("[bold red]❌ Invalid number.[/bold red]")
                input("Press Enter to continue...")
        except ValueError:
            console.print("[bold red]❌ Please enter a number.[/bold red]")
            input("Press Enter to continue...")


def check_dependencies() -> None:
    for dep in ["yt-dlp", "ffmpeg"]:
        if not shutil.which(dep):
            console.print(f"[bold red]❌ Error: {dep} is not installed or not in PATH.[/bold red]")
            sys.exit(1)


def convert_to_english_digits(text: str) -> str:
    return text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def run_download(url: str, options: List[str], download_dir: str) -> None:
    """
    Unified download handler.
    For video, remuxes into an mp4 container without re-encoding (fast).
    """
    is_audio_only = "-x" in options
    extra = [] if is_audio_only else ["--remux-video", VIDEO_FORMAT]
    cmd = (
        ["yt-dlp"]
        + options
        + extra
        + ["-o", os.path.join(download_dir, "%(title)s.%(ext)s"), url]
    )
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]❌ Download failed (exit code {e.returncode}): {url}[/bold red]")


def get_video_info(url: str) -> Optional[dict]:
    """Fetch video metadata from yt-dlp. Returns None on network or parse error."""
    with console.status("[bold yellow]🌐 Fetching data...[/bold yellow]"):
        try:
            result = subprocess.run(
                ["yt-dlp", "-j", "--skip-download", "--quiet", url],
                capture_output=True,
                text=True,
            )
            if not result.stdout:
                return None
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            console.print("[bold red]❌ Unexpected response from yt-dlp (JSON parse error).[/bold red]")
            return None
        except Exception as e:
            console.print(f"[bold red]❌ Error fetching video info: {e}[/bold red]")
            return None


def pick_h264_format(formats: List[dict], height: int) -> Optional[dict]:
    candidates = [
        f for f in formats
        if f.get("height") == height and f.get("vcodec") != "none"
    ]
    h264 = [f for f in candidates if H264_CODEC in (f.get("vcodec") or "")]
    return h264[0] if h264 else (candidates[0] if candidates else None)


def show_menu(download_dir: str = "") -> None:
    console.clear()
    console.print(Panel("[bold cyan]🚀 Hyper-Downloader[/bold cyan]", expand=False))
    if download_dir:
        console.print(f"  [cyan]📁[/cyan] [bold]Saving to:[/bold] [green]{download_dir}[/green]")
        console.print()


def single_download(download_dir: str) -> None:
    show_menu()
    url = Prompt.ask("[bold blue]🔗 Paste URL[/bold blue] (or '0' to cancel)").strip()
    if url == "0":
        return
    url = convert_to_english_digits(url)

    info = get_video_info(url)
    if not info:
        console.print("[bold red]❌ Could not retrieve video info. Check the URL and your connection.[/bold red]")
        input("\nPress Enter to go back...")
        return

    console.print(Panel(f"[green]{info.get('title')}[/green]", title="[white]Selected Video[/white]"))

    all_formats = info.get("formats", [])
    video_formats = [f for f in all_formats if f.get("vcodec") != "none" and f.get("height")]
    heights = sorted({f["height"] for f in video_formats}, reverse=True)

    table = Table(title="Available Quality Options", header_style="bold yellow", box=box.SIMPLE)
    table.add_column("ID", justify="center")
    table.add_column("Quality")
    table.add_column("Codec", style="dim")

    height_map: Dict[int, dict] = {}
    for i, h in enumerate(heights):
        chosen = pick_h264_format(all_formats, h)
        codec = chosen.get("vcodec", "unknown") if chosen else "unknown"
        codec_label = "H.264 ✓" if H264_CODEC in codec else codec.split(".")[0]
        table.add_row(str(i + 1), f"Video {h}p", codec_label)
        if chosen:
            height_map[i + 1] = chosen

    audio_id = len(heights) + 1
    table.add_row(str(audio_id), f"Audio Only ({AUDIO_FORMAT.upper()})", "")
    console.print(table)

    raw_choice = Prompt.ask("[bold]Select option (0 to exit)[/bold]")
    if raw_choice == "0":
        return

    try:
        choice_int = int(raw_choice)
    except ValueError:
        console.print("[bold red]❌ Invalid choice — please enter a number.[/bold red]")
        return

    console.print("[bold green]▶ Downloading...[/bold green]")

    if choice_int == audio_id:
        run_download(url, ["-x", "--audio-format", AUDIO_FORMAT], download_dir)
    else:
        chosen_fmt = height_map.get(choice_int)
        if not chosen_fmt:
            console.print("[bold red]❌ Invalid choice.[/bold red]")
            return
        fmt_id = chosen_fmt["format_id"]
        run_download(url, ["-f", f"{fmt_id}+bestaudio/best", "--merge-output-format", VIDEO_FORMAT], download_dir)


def batch_download(download_dir: str) -> None:
    show_menu()
    console.print("[yellow]Paste URLs one by one (type 'done' to start or '0' to exit):[/yellow]")
    urls: List[str] = []
    while True:
        u = Prompt.ask(f"[cyan]URL #{len(urls) + 1}[/cyan]").strip()
        if u.lower() == "done":
            break
        if u == "0":
            return
        if u:
            urls.append(convert_to_english_digits(u))

    if not urls:
        return

    pref = Prompt.ask(
        "\n[bold]Select Preference:[/bold]\n1. Best Video\n2. Audio Only\n0. Exit\nSelect Option",
        choices=["1", "2", "0"],
    )
    if pref == "0":
        return

    for i, url in enumerate(urls):
        console.print(f"\n[blue]({i + 1}/{len(urls)}) Downloading: {url}[/blue]")
        if pref == "1":
            run_download(
                url,
                ["-f", f"bestvideo[vcodec^={H264_CODEC}]+bestaudio/bestvideo+bestaudio/best",
                 "--merge-output-format", VIDEO_FORMAT],
                download_dir,
            )
        else:
            run_download(url, ["-x", "--audio-format", AUDIO_FORMAT], download_dir)


def main() -> None:
    check_dependencies()
    download_dir = load_saved_dir()
    while True:
        show_menu(download_dir)
        console.print("  [bold white]1.[/bold white]  Single URL")
        console.print("  [bold white]2.[/bold white]  Batch Mode")
        console.print("  [bold white]3.[/bold white]  Change Location")
        console.print("  [bold white]0.[/bold white]  Exit")
        console.print()
        mode = Prompt.ask("[bold]Select Mode[/bold]", choices=["1", "2", "3", "0"])
        if mode == "1":
            single_download(download_dir)
        elif mode == "2":
            batch_download(download_dir)
        elif mode == "3":
            chosen = browse_folders(download_dir)
            if chosen:
                download_dir = chosen
                save_dir(download_dir)
        elif mode == "0":
            break


if __name__ == "__main__":
    main()
