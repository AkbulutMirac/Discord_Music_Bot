"""Quick health check for the bot's music playback. Run it before starting the bot,
especially after updating anything:

    python check.py            (tests with a default song)
    python check.py "song name"
"""
import shutil
import subprocess
import sys

failed = False


def report(ok, name, detail=""):
    global failed
    failed = failed or not ok
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


# 1. Library versions
import discord
import davey
import yt_dlp

report(discord.__version__ == "2.7.1", "discord.py", discord.__version__)
davey_major_minor = tuple(int(x) for x in davey.__version__.split(".")[:2])
report(davey_major_minor < (0, 2), "davey", davey.__version__ + ("" if davey_major_minor < (0, 2) else
       " - 0.2+ makes voice silent with discord.py 2.7. Fix: pip install \"davey==0.1.7\""))
report(True, "yt-dlp", yt_dlp.version.__version__)

# 2. Programs on PATH
report(shutil.which("ffmpeg") is not None, "ffmpeg on PATH")
report(shutil.which("deno") is not None, "deno on PATH",
       "" if shutil.which("deno") else "Install: winget install DenoLand.Deno, then reopen the terminal")

# 3. YouTube stream
from music_source import StreamError, find_stream

query = " ".join(sys.argv[1:]) or "manifest tralala"
try:
    url, title, client = find_stream(query)
    report(True, "YouTube stream URL", f"{title} (client: {client})")
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", url, "-t", "5", "-vn", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    report(result.returncode == 0, "ffmpeg reads 5 seconds of audio", result.stderr.strip()[:300])
except StreamError as e:
    report(False, "YouTube stream URL", str(e))

print("\nAll good, start the bot." if not failed else "\nSomething is broken, see the FAIL lines above.")
sys.exit(1 if failed else 0)
