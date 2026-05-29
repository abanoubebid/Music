#!/usr/bin/env python3
"""
Hyper-Downloader — enhanced CLI video/audio downloader powered by yt-dlp.
"""

from typing import Optional, List, Dict, Tuple
import subprocess
import sys
import json
import os
import platform
import ctypes
import shutil
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule
from rich import box

# ─────────────────────────────────────────────
#  Global console & constants
# ─────────────────────────────────────────────
console = Console()

AUDIO_FORMAT = "mp3"
VIDEO_FORMAT = "mp4"
H264_CODEC   = "avc1"
CONFIG_FILE  = Path.home() / ".hyper_downloader_config.json"
DEFAULT_DIR  = str(Path.home() / "Downloads")

# Eye-friendly colour aliases (Rich markup)
C_TITLE   = "bold cyan"
C_SUCCESS = "bold green"
C_INFO    = "green"
C_PROMPT  = "cyan"
C_WARN    = "yellow"
C_ERROR   = "bold red"
C_DIM     = "dim"
C_HEAD    = "bold white"


# ══════════════════════════════════════════════
#  UI helpers — section headers & styled prompts
# ══════════════════════════════════════════════

def section(title: str) -> None:
    """Print a clear section divider with a title so the user always knows what step they're on."""
    console.print()
    console.print(Rule(f"[{C_HEAD}]  {title}  [/{C_HEAD}]", style="cyan"))
    console.print()


def numbered_menu(title: str, options: List[Tuple[str, str]], prompt: str = "Your choice") -> str:
    """
    Print a titled numbered menu and return the user's choice string.

    options = list of (key, label) e.g. [("1","Download video"), ("0","Back")]
    The last option whose key is "0" is always styled as the exit/back option.
    """
    console.print(f"  [{C_HEAD}]{title}[/{C_HEAD}]")
    console.print()
    choices = []
    for key, label in options:
        if key == "0":
            console.print(f"    [bold]0.[/bold]  [{C_ERROR}]{label}[/{C_ERROR}]")
        else:
            console.print(f"    [bold]{key}.[/bold]  [{C_INFO}]{label}[/{C_INFO}]")
        choices.append(key)
    console.print()
    return Prompt.ask(f"  [{C_PROMPT}]{prompt}[/{C_PROMPT}]", choices=choices, default=choices[0])


# ══════════════════════════════════════════════
#  Sleep-prevention helpers
# ══════════════════════════════════════════════

_ES_CONTINUOUS        = 0x80000000
_ES_SYSTEM_REQUIRED   = 0x00000001
_ES_AWAYMODE_REQUIRED = 0x00000040

_caffeinate_proc: Optional[subprocess.Popen] = None


def _prevent_sleep() -> None:
    """Prevent the OS from sleeping while a download is active."""
    global _caffeinate_proc
    os_name = platform.system()
    if os_name == "Windows":
        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_AWAYMODE_REQUIRED
        )
    elif os_name == "Darwin":
        try:
            _caffeinate_proc = subprocess.Popen(["caffeinate", "-i"])
        except FileNotFoundError:
            console.print(f"[{C_WARN}]⚠  caffeinate not found — sleep prevention unavailable.[/{C_WARN}]")
    elif os_name == "Linux":
        try:
            _caffeinate_proc = subprocess.Popen(
                ["systemd-inhibit","--what=sleep:idle","--who=hyper-downloader",
                 "--why=Download in progress","--mode=block","sleep","infinity"]
            )
        except FileNotFoundError:
            console.print(f"[{C_WARN}]⚠  systemd-inhibit not found — sleep prevention unavailable.[/{C_WARN}]")


def _allow_sleep() -> None:
    """Re-enable normal sleep behaviour after a download finishes."""
    global _caffeinate_proc
    os_name = platform.system()
    if os_name == "Windows":
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
    elif os_name in ("Darwin", "Linux"):
        if _caffeinate_proc and _caffeinate_proc.poll() is None:
            _caffeinate_proc.terminate()
            _caffeinate_proc = None


# ══════════════════════════════════════════════
#  Config / directory helpers
# ══════════════════════════════════════════════

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
    Interactive folder browser.
    Returns the selected folder path, or None if the user cancels.
    """
    current = Path(start).expanduser().resolve()
    while True:
        console.clear()
        console.print(Panel(
            f"[{C_TITLE}]📁  Choose Download Folder[/{C_TITLE}]\n[{C_DIM}]{current}[/{C_DIM}]",
            expand=False,
        ))
        try:
            entries = sorted(
                [e for e in current.iterdir() if e.is_dir() and not e.name.startswith(".")],
                key=lambda e: e.name.lower(),
            )
        except PermissionError:
            console.print(f"[{C_ERROR}]❌ Permission denied. Going back.[/{C_ERROR}]")
            current = current.parent
            continue

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("ID",     style="bold", justify="right", width=4)
        table.add_column("Folder")
        table.add_row("0",  f"[{C_ERROR}]✖  Cancel[/{C_ERROR}]")
        table.add_row("00", f"[{C_SUCCESS}]✔  Select this folder[/{C_SUCCESS}]  [{C_DIM}]{current}[/{C_DIM}]")
        if current != current.parent:
            table.add_row("..", f"[{C_WARN}]⬆  Go up[/{C_WARN}]")
        for i, entry in enumerate(entries, start=1):
            table.add_row(str(i), f"📂 {entry.name}")
        console.print(table)

        raw = Prompt.ask(
            f"\n[{C_PROMPT}]Enter number / '..' to go up / '00' to select / '0' to cancel[/{C_PROMPT}]"
        ).strip()

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
                console.print(f"[{C_ERROR}]❌ Invalid number.[/{C_ERROR}]")
                input("Press Enter to continue...")
        except ValueError:
            console.print(f"[{C_ERROR}]❌ Please enter a number.[/{C_ERROR}]")
            input("Press Enter to continue...")


# ══════════════════════════════════════════════
#  Dependency check
# ══════════════════════════════════════════════

def check_dependencies() -> None:
    for dep in ["yt-dlp", "ffmpeg"]:
        if not shutil.which(dep):
            console.print(f"[{C_ERROR}]❌ Error: {dep} is not installed or not in PATH.[/{C_ERROR}]")
            sys.exit(1)


# ══════════════════════════════════════════════
#  Utility helpers
# ══════════════════════════════════════════════

def convert_to_english_digits(text: str) -> str:
    return text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    parts  = []
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def format_size(bytes_val: Optional[float]) -> str:
    """Convert bytes to a human-readable size string."""
    if not bytes_val:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


# ══════════════════════════════════════════════
#  Size estimation
# ══════════════════════════════════════════════

# ──────────────────────────────────────────────
#  Size estimation
#
#  Strategy: always calculate from duration × bitrate.
#  This is reliable across single videos, batch, and playlists because:
#  - format filesize fields are often missing or wrong
#  - duration is always present after a fast fetch
#  Bitrates used (measured YouTube averages, conservative):
#    video 1080p ≈ 3 Mbps  |  720p ≈ 1.5 Mbps  |  480p ≈ 0.8 Mbps
#    audio MP3   ≈ 128 kbps
#  For single-video we know the exact resolution, so we pick the right bitrate.
# ──────────────────────────────────────────────

_VIDEO_BITRATES = {1080: 3_000_000, 720: 1_500_000, 480: 800_000,
                   360: 500_000, 240: 300_000, 144: 150_000}
_DEFAULT_VIDEO_BITRATE = 1_500_000   # fallback if height unknown
_AUDIO_BITRATE         =   128_000   # bits/sec for MP3


def _size_from_duration(duration_sec: float, is_audio: bool, height: int = 0) -> int:
    """Return estimated bytes from duration and format type."""
    if is_audio:
        bitrate = _AUDIO_BITRATE
    else:
        # Find the closest known height
        bitrate = _VIDEO_BITRATES.get(height)
        if not bitrate:
            closest = min(_VIDEO_BITRATES.keys(), key=lambda h: abs(h - height)) if height else 0
            bitrate = _VIDEO_BITRATES.get(closest, _DEFAULT_VIDEO_BITRATE)
    return int(duration_sec * bitrate / 8)


def estimate_size(info: dict, options: List[str]) -> str:
    """Estimate download size for a single video from its duration."""
    is_audio = "-x" in options
    duration = info.get("duration") or 0
    if not duration:
        return "unknown"
    # Extract chosen height from the info (set by ask_format_choice via _chosen_height)
    height = info.get("_chosen_height", 0)
    return format_size(_size_from_duration(duration, is_audio, height))


def estimate_size_batch(infos: List[Optional[dict]], is_audio: bool) -> str:
    """Estimate total size for a batch of videos."""
    counted = 0
    total   = 0
    for inf in infos:
        if not inf:
            continue
        dur = inf.get("duration") or 0
        if dur > 0:
            total   += _size_from_duration(dur, is_audio)
            counted += 1
    if counted == 0:
        return "unknown"
    label = format_size(total)
    valid_count = len([i for i in infos if i])
    if counted < valid_count:
        label += "  (partial — some durations unavailable)"
    return label


def estimate_playlist_size(entries: List[dict], fmt: str) -> str:
    """Estimate total size for a list of playlist entries from their durations."""
    is_audio = fmt == "audio"
    counted  = 0
    total    = 0
    for e in entries:
        dur = e.get("duration") or 0
        if dur > 0:
            total   += _size_from_duration(dur, is_audio)
            counted += 1
    if counted == 0:
        return "unknown"
    label = format_size(total)
    if counted < len(entries):
        label += "  (partial — some durations unavailable)"
    return label


# ══════════════════════════════════════════════
#  Confirm before download  ←  THE KEY FUNCTION
#  Shows size, asks "download?", then exit/menu
# ══════════════════════════════════════════════

def confirm_and_decide(size_label: str, item_count: int = 1, exact: bool = False) -> Optional[str]:
    """
    Show download size, ask the user to confirm, then ask exit/menu.

    exact=True  → size came from real format metadata (like Chrome shows)
    exact=False → size is a bitrate estimate

    Returns:
        'menu'  — download approved, return to menu afterward
        'exit'  — download approved, exit program afterward
        None    — user cancelled, go back to main menu without downloading
    """
    section("📦  Download Summary")

    count_str  = f"{item_count} item{'s' if item_count > 1 else ''}"
    size_note  = "" if exact else f"  [{C_DIM}](estimated from bitrate — actual may vary slightly)[/{C_DIM}]"
    size_tag   = "Size" if exact else "Estimated size"

    console.print(f"  [{C_DIM}]Items to download :[/{C_DIM}]  [{C_HEAD}]{count_str}[/{C_HEAD}]")
    console.print(f"  [{C_DIM}]{size_tag:18s}:[/{C_DIM}]  [{C_WARN}]{size_label}[/{C_WARN}]{size_note}")
    console.print()

    # Step 1: Confirm download
    ans = numbered_menu(
        "Ready to download?",
        [("1", "Yes — start downloading"),
         ("0", "No  — go back to main menu")],
        prompt="Confirm",
    )
    if ans == "0":
        return None   # cancelled

    # Step 2: What to do after download finishes
    section("⚙️   After Download")
    after = numbered_menu(
        "What should happen when the download finishes?",
        [("1", "Return to main menu"),
         ("2", "Exit the program")],
        prompt="Your choice",
    )
    return "menu" if after == "1" else "exit"


# ══════════════════════════════════════════════
#  Download runner  (sleep-aware)
# ══════════════════════════════════════════════

def run_download(url: str, options: List[str], download_dir: str) -> None:
    """Run yt-dlp, preventing OS sleep for the duration."""
    is_audio_only = "-x" in options
    extra = [] if is_audio_only else ["--remux-video", VIDEO_FORMAT]
    cmd = (
        ["yt-dlp"] + options + extra
        + ["-o", os.path.join(download_dir, "%(title)s.%(ext)s"), url]
    )
    _prevent_sleep()
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[{C_ERROR}]❌ Download failed (exit code {e.returncode}): {url}[/{C_ERROR}]")
    finally:
        _allow_sleep()


# ══════════════════════════════════════════════
#  yt-dlp metadata helpers
# ══════════════════════════════════════════════

def get_video_info_fast(url: str) -> Optional[dict]:
    """
    FAST metadata fetch: title, duration, uploader only.
    Uses yt-dlp --print to get structured fields reliably — much faster than full -j,
    and always returns duration (unlike --flat-playlist which often omits it).
    Does NOT include format details, so it cannot be used for quality selection.
    """
    with console.status(f"[{C_WARN}]🌐 Fetching info...[/{C_WARN}]"):
        try:
            # --print gives us exactly the fields we need, quickly and reliably
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--no-playlist",
                    "--skip-download",
                    "--quiet",
                    "--print", "%(title)s\t%(duration)s\t%(uploader)s\t%(webpage_url)s",
                    url,
                ],
                capture_output=True, text=True,
            )
            line = result.stdout.strip()
            if not line:
                return None
            parts = line.split("\t")
            title    = parts[0] if len(parts) > 0 else url
            duration = None
            if len(parts) > 1 and parts[1] not in ("", "NA", "None"):
                try:
                    duration = float(parts[1])
                except ValueError:
                    pass
            uploader    = parts[2] if len(parts) > 2 else ""
            webpage_url = parts[3] if len(parts) > 3 else url
            return {
                "title":       title,
                "duration":    duration,
                "uploader":    uploader,
                "webpage_url": webpage_url,
            }
        except Exception:
            return None


def get_video_info(url: str) -> Optional[dict]:
    """
    FULL metadata fetch: includes all format details needed for quality selection.
    Slower (~3-5 s per video) — only call this right before showing quality options.
    """
    with console.status(f"[{C_WARN}]🌐 Fetching format details...[/{C_WARN}]"):
        try:
            result = subprocess.run(
                ["yt-dlp", "-j", "--skip-download", "--quiet", url],
                capture_output=True, text=True,
            )
            if not result.stdout:
                return None
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            console.print(f"[{C_ERROR}]❌ Unexpected response from yt-dlp (JSON parse error).[/{C_ERROR}]")
            return None
        except Exception as e:
            console.print(f"[{C_ERROR}]❌ Error fetching video info: {e}[/{C_ERROR}]")
            return None


def get_playlist_info(url: str) -> Optional[dict]:
    """
    Fetch playlist metadata: title + per-entry (title, duration, id, webpage_url).
    Two-step approach:
      1. --dump-single-json --flat-playlist  → fast, gets playlist title + entry ids
      2. yt-dlp --print per entry            → fills in missing duration fields
    Falls back gracefully if step 2 fails.
    """
    with console.status(f"[{C_WARN}]🌐 Fetching playlist info...[/{C_WARN}]"):
        try:
            # Step 1: flat fetch for overall structure
            result = subprocess.run(
                ["yt-dlp", "--dump-single-json", "--flat-playlist", "--quiet", url],
                capture_output=True, text=True,
            )
            if not result.stdout.strip():
                return None
            data    = json.loads(result.stdout)
            entries = data.get("entries") or []
            if not entries:
                return None

            # Flatten one level of nesting some extractors add
            flat: list = []
            for e in entries:
                if e is None:
                    continue
                if e.get("_type") == "playlist" and e.get("entries"):
                    flat.extend(e["entries"])
                else:
                    flat.append(e)
            data["entries"] = flat

            # Step 2: fill missing durations via --print (one subprocess, all entries)
            missing_duration = any(
                not e.get("duration") for e in data["entries"] if e
            )
            if missing_duration:
                print_result = subprocess.run(
                    [
                        "yt-dlp",
                        "--flat-playlist",
                        "--quiet",
                        "--print", "%(duration)s",
                        url,
                    ],
                    capture_output=True, text=True,
                )
                durations = print_result.stdout.strip().splitlines()
                for i, e in enumerate(data["entries"]):
                    if e and not e.get("duration") and i < len(durations):
                        d = durations[i]
                        if d not in ("", "NA", "None"):
                            try:
                                e["duration"] = float(d)
                            except ValueError:
                                pass

            return data
        except json.JSONDecodeError:
            console.print(f"[{C_ERROR}]❌ JSON parse error from yt-dlp.[/{C_ERROR}]")
            return None
        except Exception as e:
            console.print(f"[{C_ERROR}]❌ Error fetching playlist info: {e}[/{C_ERROR}]")
            return None


def pick_h264_format(formats: List[dict], height: int) -> Optional[dict]:
    """
    For a given height, prefer the video-only H.264 stream (acodec=none, has filesize).
    Falls back to muxed H.264, then any codec video-only, then any candidate.
    Video-only streams always have real filesize data; muxed ones often don't.
    """
    candidates = [f for f in formats if f.get("height") == height and f.get("vcodec") not in (None, "none")]
    # 1st choice: video-only H.264 with a real filesize
    h264_video_only = [f for f in candidates
                       if H264_CODEC in (f.get("vcodec") or "")
                       and f.get("acodec") in (None, "none")
                       and (f.get("filesize") or f.get("filesize_approx") or f.get("vbr"))]
    if h264_video_only:
        return h264_video_only[0]
    # 2nd choice: any video-only H.264
    h264_any = [f for f in candidates
                if H264_CODEC in (f.get("vcodec") or "")
                and f.get("acodec") in (None, "none")]
    if h264_any:
        return h264_any[0]
    # 3rd choice: muxed H.264 (filesize likely missing but still valid)
    h264_muxed = [f for f in candidates if H264_CODEC in (f.get("vcodec") or "")]
    if h264_muxed:
        return h264_muxed[0]
    # Fallback: any video stream
    return candidates[0] if candidates else None


# ══════════════════════════════════════════════
#  Shared interactive prompts
# ══════════════════════════════════════════════

def _exact_size(fmt: dict, duration: float = 0.0) -> int:
    """
    Best-effort size in bytes for one format stream.
    Priority:
      1. filesize        -- exact, from CDN headers (often present for VP9/WebM)
      2. filesize_approx -- yt-dlp pre-computed estimate
      3. vbr/abr x duration  -- video-only or audio-only bitrate (NOT tbr, to avoid double-counting)
    Returns 0 only when truly nothing is available.
    """
    fs = fmt.get("filesize") or fmt.get("filesize_approx")
    if fs:
        return int(fs)
    if duration:
        # Use vbr for video-only streams, abr for audio-only streams
        # Avoid tbr here because tbr = vbr+abr combined, and _combined_size
        # already adds audio separately, which would double-count.
        bitrate = fmt.get("vbr") or fmt.get("abr")
        if bitrate:
            return int(duration * bitrate * 1000 / 8)
    return 0


def _exact_size_with_tbr(fmt: dict, duration: float = 0.0) -> int:
    """
    Size using tbr (total bitrate) -- use ONLY when audio is already included
    in the stream (muxed formats), so there is no separate audio to add.
    """
    fs = fmt.get("filesize") or fmt.get("filesize_approx")
    if fs:
        return int(fs)
    if duration:
        tbr = fmt.get("tbr") or fmt.get("vbr") or fmt.get("abr")
        if tbr:
            return int(duration * tbr * 1000 / 8)
    return 0


def _best_audio_fmt(all_formats: list, prefer_aac: bool = False) -> Optional[dict]:
    """
    Return the best audio-only format by bitrate/size.
    prefer_aac=True: when merging H.264 into mp4, yt-dlp can only use AAC audio
    (opus/vorbis can't go into mp4 container). It picks the lowest-bitrate AAC
    available. We do the same to get an accurate size estimate.
    """
    audio = [f for f in all_formats
             if f.get("acodec") not in (None, "none")
             and f.get("vcodec") in (None, "none")]
    if prefer_aac:
        aac = [f for f in audio
               if "mp4a" in (f.get("acodec") or "") or "aac" in (f.get("acodec") or "")]
        if aac:
            # yt-dlp picks best quality aac that fits — use lowest abr aac
            # (matches observed behavior: 48kbps aac chosen over 128kbps for small videos)
            return min(aac, key=lambda f: f.get("abr") or f.get("tbr") or 999)
    return max(audio, key=lambda f: f.get("abr") or f.get("tbr") or _exact_size(f), default=None)


def _combined_size(vid_fmt: dict, all_formats: list, duration: float = 0.0) -> int:
    """
    True download size = video stream + audio stream (yt-dlp merges them).
    - If the video format already carries audio (muxed), use tbr alone.
    - Otherwise: video bytes + best matching audio bytes.
      For H.264 video we prefer AAC audio (mp4 container compatibility).
    """
    # Muxed format: audio already inside, use tbr for the whole thing
    if vid_fmt.get("acodec") not in (None, "none"):
        return _exact_size_with_tbr(vid_fmt, duration)
    # Separate video+audio streams
    vid_bytes  = _exact_size(vid_fmt, duration)
    is_h264    = H264_CODEC in (vid_fmt.get("vcodec") or "")
    audio      = _best_audio_fmt(all_formats, prefer_aac=is_h264)
    audio_bytes = _exact_size(audio, duration) if audio else 0
    return vid_bytes + audio_bytes


def get_real_download_size(url: str, fmt_selector: str) -> str:
    """
    Get accurate download size by asking yt-dlp what it will actually download.
    Uses --print after_move:filepath on a simulated run so yt-dlp resolves the
    exact format(s) and reports their real filesizes.
    Falls back to filesize_approx if filesize is unavailable.
    Returns a human-readable size string.
    """
    with console.status(f"[{C_WARN}]📏 Calculating size...[/{C_WARN}]"):
        try:
            # Use --print to get filesize for each stream yt-dlp will actually fetch
            cmd = [
                "yt-dlp",
                "-f", fmt_selector,
                "--skip-download",
                "--quiet",
                "--no-simulate",
                "--print", "%(filesize,filesize_approx)s",
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            lines = [l.strip() for l in result.stdout.strip().splitlines()
                     if l.strip() and l.strip() not in ("NA", "None", "none", "N/A", "")]
            total = 0
            valid = 0
            for line in lines:
                try:
                    val = int(float(line))
                    if val > 0:
                        total += val
                        valid += 1
                except ValueError:
                    pass
            if valid > 0 and total > 0:
                return format_size(total)
        except Exception:
            pass
    return "unknown"


def ask_format_choice(info: dict) -> Optional[Tuple[str, List[str], str]]:
    """
    Show quality options for a single video.
    Returns (url, yt-dlp options, fmt_selector) or None if the user cancels.
    fmt_selector is passed to get_real_download_size() after save path is chosen.
    """
    section("🎬  Select Quality")

    url         = info.get("webpage_url") or info.get("url", "")
    all_formats = info.get("formats", [])
    duration    = float(info.get("duration") or 0)
    video_fmts  = [f for f in all_formats if f.get("vcodec") not in (None, "none") and f.get("height")]
    heights     = sorted({f["height"] for f in video_fmts}, reverse=True)

    table = Table(header_style=f"bold {C_PROMPT}", box=box.SIMPLE)
    table.add_column("#",       justify="center", width=4)
    table.add_column("Quality")
    table.add_column("Codec",   style=C_DIM)

    height_map: Dict[int, dict] = {}
    for i, h in enumerate(heights, start=1):
        vid = pick_h264_format(all_formats, h)
        if not vid:
            continue
        codec       = vid.get("vcodec", "unknown")
        is_h264     = H264_CODEC in codec
        if is_h264:
            codec_label = "H.264 ✓"
            compat_note = ""
        else:
            short = codec.split(".")[0]
            codec_label = short
            compat_note = f"  [{C_WARN}]⚠ may not open in QuickTime[/{C_WARN}]"
        table.add_row(str(i), f"Video {h}p{compat_note}", codec_label)
        height_map[i] = vid

    audio_id   = len(height_map) + 1
    best_audio = _best_audio_fmt(all_formats)
    table.add_row(str(audio_id), f"Audio Only ({AUDIO_FORMAT.upper()})", "")
    table.add_row("0", f"[{C_ERROR}]Back to main menu[/{C_ERROR}]", "")
    console.print(table)

    raw = Prompt.ask(f"  [{C_PROMPT}]Select format[/{C_PROMPT}]").strip()
    if raw == "0":
        return None
    try:
        choice = int(raw)
    except ValueError:
        console.print(f"[{C_ERROR}]❌ Invalid choice.[/{C_ERROR}]")
        return None

    if choice == audio_id:
        dl_options = ["-x", "--audio-format", AUDIO_FORMAT]
        return url, dl_options, "bestaudio/best"

    chosen_fmt = height_map.get(choice)
    if not chosen_fmt:
        console.print(f"[{C_ERROR}]❌ Invalid choice.[/{C_ERROR}]")
        return None
    fmt_id  = chosen_fmt["format_id"]
    is_h264 = H264_CODEC in (chosen_fmt.get("vcodec") or "")

    # Non-H264 (VP9, AV1): warn and offer re-encode for Mac/QuickTime compatibility
    if not is_h264:
        console.print()
        console.print(f"  [{C_WARN}]⚠  This format ({chosen_fmt.get('vcodec','').split('.')[0]}) may not open in QuickTime or some players.[/{C_WARN}]")
        console.print()
        compat = numbered_menu(
            "How do you want to download it?",
            [("1", f"Download as-is  (.{VIDEO_FORMAT}, fastest — use VLC to play)"),
             ("2", "Re-encode to H.264  (fully compatible, takes longer)"),
             ("0", "Go back and pick a different quality")],
            prompt="Your choice",
        )
        if compat == "0":
            return ask_format_choice(info)   # restart quality selection
        if compat == "2":
            # Re-encode: ffmpeg converts to H.264 — compatible everywhere
            dl_options = [
                "-f", f"{fmt_id}+bestaudio/best",
                "--merge-output-format", VIDEO_FORMAT,
                "--postprocessor-args", "ffmpeg:-vcodec libx264 -acodec aac",
            ]
            console.print(f"  [{C_DIM}]Note: re-encoding will take extra time after download.[/{C_DIM}]")
            return url, dl_options, f"{fmt_id}+bestaudio/best"
        # else: download as-is
    dl_options = ["-f", f"{fmt_id}+bestaudio/best", "--merge-output-format", VIDEO_FORMAT]
    return url, dl_options, f"{fmt_id}+bestaudio/best"


def ask_save_path(current_dir: str) -> str:
    """Ask whether to keep the current save folder or pick a new one."""
    section("📁  Save Location")
    console.print(f"  [{C_DIM}]Current folder:  {current_dir}[/{C_DIM}]")
    console.print()
    ans = numbered_menu(
        "Where do you want to save the file?",
        [("1", f"Keep current folder"),
         ("2", "Choose a different folder")],
        prompt="Your choice",
    )
    if ans == "2":
        chosen = browse_folders(current_dir)
        return chosen if chosen else current_dir
    return current_dir


def _print_items_with_paths(labels: List[str], paths: Dict[int, str], default_dir: str) -> None:
    """Print the items table with each item's current save folder."""
    table = Table(box=box.SIMPLE, show_header=True, header_style=f"bold {C_PROMPT}")
    table.add_column("#",           justify="right", style="bold", width=4)
    table.add_column("Item",        style=C_INFO)
    table.add_column("Save Folder", style=C_DIM)
    for i, label in enumerate(labels, start=1):
        folder = paths.get(i, default_dir)
        tag    = "  [dim](default)[/dim]" if folder == default_dir else ""
        table.add_row(str(i), label, folder + tag)
    console.print(table)


def ask_per_item_save_paths(labels: List[str], default_dir: str) -> Dict[int, str]:
    """
    Ask whether to use one folder for all items, or customise per item.
    Redraws the items table after every folder pick so the user can see
    all current paths before choosing the next one.
    """
    section("📁  Save Location")
    console.print(f"  [{C_DIM}]Default folder:  {default_dir}[/{C_DIM}]")
    console.print()
    ans = numbered_menu(
        "Where do you want to save the files?",
        [("1", "Same folder for all items"),
         ("2", "Choose a different folder for specific items")],
        prompt="Your choice",
    )
    paths: Dict[int, str] = {i + 1: default_dir for i in range(len(labels))}
    if ans == "1":
        return paths

    _print_items_with_paths(labels, paths, default_dir)
    console.print(f"  [{C_DIM}]Enter an item number to change its folder.  Enter 0 when done.[/{C_DIM}]")
    console.print()
    while True:
        raw = Prompt.ask(f"  [{C_PROMPT}]Item number  (0 = done)[/{C_PROMPT}]").strip()
        if raw == "0":
            break
        try:
            idx = int(raw)
            if 1 <= idx <= len(labels):
                chosen = browse_folders(paths.get(idx, default_dir))
                if chosen:
                    paths[idx] = chosen
                _print_items_with_paths(labels, paths, default_dir)
                console.print(f"  [{C_DIM}]Enter another number to keep changing, or 0 to finish.[/{C_DIM}]")
                console.print()
            else:
                console.print(f"[{C_ERROR}]❌ Number out of range.[/{C_ERROR}]")
        except ValueError:
            console.print(f"[{C_ERROR}]❌ Please enter a number.[/{C_ERROR}]")
    return paths


# ══════════════════════════════════════════════
#  Main menu header
# ══════════════════════════════════════════════

def show_menu(download_dir: str = "") -> None:
    console.clear()
    console.print(Panel(f"[{C_TITLE}]🚀  Hyper-Downloader[/{C_TITLE}]", expand=False))
    if download_dir:
        console.print(f"  [{C_PROMPT}]📁[/{C_PROMPT}]  [bold]Saving to:[/bold]  [{C_INFO}]{download_dir}[/{C_INFO}]")
        console.print()


# ══════════════════════════════════════════════
#  SINGLE URL download
# ══════════════════════════════════════════════

def single_download(download_dir: str) -> str:
    show_menu()
    section("🔗  Single URL Download")

    url = Prompt.ask(f"  [{C_PROMPT}]Paste video URL  (0 = back)[/{C_PROMPT}]").strip()
    if url == "0":
        return "menu"
    url = convert_to_english_digits(url)

    # Fast fetch first — shows title/duration immediately
    fast = get_video_info_fast(url)
    if not fast:
        console.print(f"[{C_ERROR}]❌ Could not fetch video info. Check the URL and your connection.[/{C_ERROR}]")
        input("\nPress Enter to go back...")
        return "menu"

    console.print(Panel(
        f"[{C_INFO}]{fast.get('title', url)}[/{C_INFO}]\n"
        f"[{C_DIM}]Duration: {format_duration(fast.get('duration'))}[/{C_DIM}]",
        title="Video Info",
    ))

    # Full fetch only now (needed for quality list)
    info = get_video_info(url)
    if not info:
        console.print(f"[{C_ERROR}]❌ Could not fetch format details.[/{C_ERROR}]")
        input("\nPress Enter to go back...")
        return "menu"

    result = ask_format_choice(info)
    if result is None:
        return "menu"
    dl_url, options, fmt_selector = result   # fmt_selector used to compute real size

    save_path = ask_save_path(download_dir)

    # Show summary header first, then calculate size inside it
    section("📦  Download Summary")
    console.print(f"  [{C_DIM}]Items to download :[/{C_DIM}]  [{C_HEAD}]1 item[/{C_HEAD}]")
    with console.status(f"  [{C_WARN}]📏 Calculating size...[/{C_WARN}]"):
        size = get_real_download_size(dl_url, fmt_selector) if fmt_selector else "unknown"
    size_tag  = "Size" if size != "unknown" else "Estimated size"
    size_note = "" if size != "unknown" else f"  [{C_DIM}](could not determine exact size)[/{C_DIM}]"
    console.print(f"  [{C_DIM}]{size_tag:18s}:[/{C_DIM}]  [{C_WARN}]{size}[/{C_WARN}]{size_note}")
    console.print()

    ans = numbered_menu(
        "Ready to download?",
        [("1", "Yes — start downloading"),
         ("0", "No  — go back to main menu")],
        prompt="Confirm",
    )
    if ans == "0":
        return "menu"

    section("⚙️   After Download")
    after = numbered_menu(
        "What should happen when the download finishes?",
        [("1", "Return to main menu"),
         ("2", "Exit the program")],
        prompt="Your choice",
    )
    decision = "menu" if after == "1" else "exit"

    section("🚀  Starting Download")
    console.print(f"  [{C_INFO}]Title    :[/{C_INFO}]  {fast.get('title', dl_url)[:80]}")
    console.print(f"  [{C_INFO}]Save to  :[/{C_INFO}]  {save_path}")
    console.print(f"  [{C_INFO}]Size     :[/{C_INFO}]  {size}")
    console.print()
    run_download(dl_url, options, save_path)
    console.print(f"\n[{C_SUCCESS}]✔  Download complete![/{C_SUCCESS}]")
    return decision


# ══════════════════════════════════════════════
#  BATCH MODE
# ══════════════════════════════════════════════

def batch_download(download_dir: str) -> str:
    show_menu()
    section("📋  Batch URL Download")
    console.print(f"  [{C_DIM}]Paste one URL per line.  Type 'done' when finished, or 0 to cancel.[/{C_DIM}]")
    console.print()

    urls: List[str] = []
    while True:
        u = Prompt.ask(f"  [{C_PROMPT}]URL #{len(urls) + 1}[/{C_PROMPT}]").strip()
        if u.lower() == "done":
            break
        if u == "0":
            return "menu"
        if u:
            urls.append(convert_to_english_digits(u))

    if not urls:
        return "menu"

    # Fetch info for all URLs
    infos: Dict[int, Optional[dict]] = {}

    def _display_batch_info() -> None:
        section("📊  URL Information")
        table = Table(header_style=f"bold {C_PROMPT}", box=box.SIMPLE)
        table.add_column("#",        justify="right", width=4)
        table.add_column("Title",    style=C_INFO)
        table.add_column("Duration", style=C_DIM)
        table.add_column("URL",      style=C_DIM, no_wrap=True)
        for i, u in enumerate(urls, start=1):
            inf      = infos.get(i)
            title    = inf.get("title", "—") if inf else f"[{C_ERROR}]Could not fetch[/{C_ERROR}]"
            duration = format_duration(inf.get("duration")) if inf else "—"
            table.add_row(str(i), title, duration, u[:70])
        console.print(table)

    console.print(f"\n  [{C_WARN}]Fetching info for all URLs...[/{C_WARN}]")
    for i, u in enumerate(urls, start=1):
        console.print(f"  [{C_DIM}]({i}/{len(urls)}) {u[:70]}[/{C_DIM}]")
        infos[i] = get_video_info_fast(u)   # fast: title + duration only
    _display_batch_info()

    # Allow editing
    section("✏️   Edit URLs  (optional)")
    console.print(f"  [{C_DIM}]Enter an item number to replace its URL.  Enter 0 when done.[/{C_DIM}]")
    console.print()
    while True:
        raw = Prompt.ask(f"  [{C_PROMPT}]Item number to edit  (0 = done)[/{C_PROMPT}]").strip()
        if raw == "0":
            break
        try:
            idx = int(raw)
            if 1 <= idx <= len(urls):
                new_url = Prompt.ask(f"  [{C_PROMPT}]New URL for #{idx}[/{C_PROMPT}]").strip()
                new_url = convert_to_english_digits(new_url)
                urls[idx - 1] = new_url
                console.print(f"  [{C_WARN}]Re-fetching info for #{idx}...[/{C_WARN}]")
                infos[idx] = get_video_info_fast(new_url)
                _display_batch_info()
            else:
                console.print(f"[{C_ERROR}]❌ Number out of range.[/{C_ERROR}]")
        except ValueError:
            console.print(f"[{C_ERROR}]❌ Please enter a number.[/{C_ERROR}]")

    # Format
    section("🎬  Select Format")
    pref = numbered_menu(
        "What do you want to download?",
        [("1", "Video  (best quality)"),
         ("2", "Audio only  (MP3)"),
         ("0", "Back to main menu")],
        prompt="Your choice",
    )
    if pref == "0":
        return "menu"

    # Save paths
    labels     = [f"#{i+1}  {urls[i][:65]}" for i in range(len(urls))]
    save_paths = ask_per_item_save_paths(labels, download_dir)

    # Size estimate: sum duration × bitrate for all videos
    is_audio   = pref == "2"
    size_label = estimate_size_batch([infos.get(i) for i in range(1, len(urls)+1)], is_audio)

    decision = confirm_and_decide(size_label, item_count=len(urls), exact=False)
    if decision is None:
        return "menu"

    # Run
    for i, u in enumerate(urls, start=1):
        console.print(f"\n  [{C_INFO}]({i}/{len(urls)})  Downloading: {u}[/{C_INFO}]")
        sp = save_paths.get(i, download_dir)
        if pref == "1":
            run_download(u, ["-f", f"bestvideo[vcodec^={H264_CODEC}]+bestaudio/bestvideo+bestaudio/best",
                             "--merge-output-format", VIDEO_FORMAT], sp)
        else:
            run_download(u, ["-x", "--audio-format", AUDIO_FORMAT], sp)

    console.print(f"\n[{C_SUCCESS}]✔  Batch download complete![/{C_SUCCESS}]")
    return decision


# ══════════════════════════════════════════════
#  PLAYLIST MODE
# ══════════════════════════════════════════════

def playlist_download(download_dir: str) -> str:
    show_menu()
    section("🎵  Playlist Download")

    url = Prompt.ask(f"  [{C_PROMPT}]Paste playlist URL  (0 = back)[/{C_PROMPT}]").strip()
    if url == "0":
        return "menu"
    url = convert_to_english_digits(url)

    pl = get_playlist_info(url)
    if not pl:
        console.print(f"[{C_ERROR}]❌ Could not fetch playlist info. Check the URL and your connection.[/{C_ERROR}]")
        input("\nPress Enter to go back...")
        return "menu"

    entries  = pl.get("entries", [])
    total    = len(entries)
    pl_title = pl.get("title", "Unknown Playlist")

    console.print(Panel(
        f"[{C_INFO}]{pl_title}[/{C_INFO}]\n[{C_DIM}]Total videos: {total}[/{C_DIM}]",
        title="Playlist Info",
    ))

    # Full or range
    section("📥  Download Scope")
    scope = numbered_menu(
        f"Which videos do you want to download?  (Playlist has {total} videos)",
        [("1", f"Full playlist  — all {total} videos"),
         ("2", "Custom range  — choose start and end"),
         ("0", "Back to main menu")],
        prompt="Your choice",
    )
    if scope == "0":
        return "menu"

    if scope == "1":
        start_idx, end_idx = 1, total
    else:
        console.print(f"  [{C_DIM}]Available range: 1 – {total}[/{C_DIM}]")
        console.print()
        while True:
            s = Prompt.ask(f"  [{C_PROMPT}]Start video number  (0 = back)[/{C_PROMPT}]").strip()
            if s == "0":
                return "menu"
            e = Prompt.ask(f"  [{C_PROMPT}]End video number    (0 = back)[/{C_PROMPT}]").strip()
            if e == "0":
                return "menu"
            try:
                start_idx, end_idx = int(s), int(e)
                if 1 <= start_idx <= end_idx <= total:
                    break
                console.print(f"[{C_ERROR}]❌ Invalid range — start must be ≤ end and within 1–{total}.[/{C_ERROR}]")
            except ValueError:
                console.print(f"[{C_ERROR}]❌ Please enter numbers.[/{C_ERROR}]")

    selected = entries[start_idx - 1 : end_idx]

    # Show selected videos
    section(f"📋  Selected Videos  ({start_idx} – {end_idx})")
    table = Table(header_style=f"bold {C_PROMPT}", box=box.SIMPLE)
    table.add_column("#",        justify="right", width=5)
    table.add_column("Title",    style=C_INFO)
    table.add_column("Duration", style=C_DIM)
    for i, entry in enumerate(selected, start=start_idx):
        table.add_row(str(i), entry.get("title", entry.get("id", "—")), format_duration(entry.get("duration")))
    console.print(table)

    # Format
    section("🎬  Select Format")
    fmt_raw = numbered_menu(
        "What do you want to download?",
        [("1", "Video  (best quality)"),
         ("2", "Audio only  (MP3)"),
         ("0", "Back to main menu")],
        prompt="Your choice",
    )
    if fmt_raw == "0":
        return "menu"
    fmt = "audio" if fmt_raw == "2" else "video"

    # Save paths
    labels     = [f"#{start_idx+i}  {e.get('title', e.get('id','—'))[:60]}" for i, e in enumerate(selected)]
    save_paths = ask_per_item_save_paths(labels, download_dir)

    # Size estimate + confirm
    size_label = estimate_playlist_size(selected, fmt)
    decision   = confirm_and_decide(size_label, item_count=len(selected), exact=False)
    if decision is None:
        return "menu"

    # Run
    for local_i, entry in enumerate(selected, start=1):
        entry_url = entry.get("url") or entry.get("webpage_url") or entry.get("id")
        if entry_url and not entry_url.startswith("http"):
            extractor = pl.get("extractor_key", "youtube")
            if "youtube" in extractor.lower():
                entry_url = f"https://www.youtube.com/watch?v={entry_url}"
        if not entry_url:
            console.print(f"[{C_WARN}]⚠  Skipping #{local_i} — no URL found.[/{C_WARN}]")
            continue
        console.print(f"\n  [{C_INFO}]({local_i}/{len(selected)})  {entry.get('title', entry_url)[:70]}[/{C_INFO}]")
        sp = save_paths.get(local_i, download_dir)
        if fmt == "audio":
            run_download(entry_url, ["-x", "--audio-format", AUDIO_FORMAT], sp)
        else:
            run_download(entry_url, ["-f", f"bestvideo[vcodec^={H264_CODEC}]+bestaudio/bestvideo+bestaudio/best",
                                     "--merge-output-format", VIDEO_FORMAT], sp)

    console.print(f"\n[{C_SUCCESS}]✔  Playlist download complete![/{C_SUCCESS}]")
    return decision


# ══════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════

def main() -> None:
    check_dependencies()
    download_dir = load_saved_dir()

    while True:
        show_menu(download_dir)
        console.print(f"  [bold]1.[/bold]  [{C_INFO}]Single URL[/{C_INFO}]")
        console.print(f"  [bold]2.[/bold]  [{C_INFO}]Batch Mode  (multiple URLs)[/{C_INFO}]")
        console.print(f"  [bold]3.[/bold]  [{C_INFO}]Playlist Mode[/{C_INFO}]")
        console.print(f"  [bold]4.[/bold]  [{C_WARN}]Change Save Location[/{C_WARN}]")
        console.print(f"  [bold]0.[/bold]  [{C_ERROR}]Exit[/{C_ERROR}]")
        console.print()

        mode = Prompt.ask(
            f"  [{C_PROMPT}]Select mode[/{C_PROMPT}]",
            choices=["1", "2", "3", "4", "0"],
        )

        if mode == "1":
            action = single_download(download_dir)
        elif mode == "2":
            action = batch_download(download_dir)
        elif mode == "3":
            action = playlist_download(download_dir)
        elif mode == "4":
            chosen = browse_folders(download_dir)
            if chosen:
                download_dir = chosen
                save_dir(download_dir)
            action = "menu"
        else:
            break

        if action == "exit":
            console.print(f"\n[{C_INFO}]Goodbye![/{C_INFO}]")
            sys.exit(0)


if __name__ == "__main__":
    main()
