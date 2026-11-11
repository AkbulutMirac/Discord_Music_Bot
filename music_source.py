"""Find a playable YouTube audio stream for a search query.

Used by dc_bot.py, dc_bot_mcp.py and check.py.
"""
import urllib.error
import urllib.request

import yt_dlp

YDL_OPTIONS = {
    'format': 'ba[ext=m4a]/ba[ext=webm]/ba/b',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'geo_bypass': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'source_address': '0.0.0.0',
    'socket_timeout': 30,
    'http_chunk_size': 10485760,
    'prefer_ffmpeg': True,
    'keepvideo': False,
    'extract_flat': False,
}

# YouTube clients tried in order. As of 2026-11 only visionos gives stream URLs that
# ffmpeg can open (the others return 403), but that changes when YouTube changes.
PLAYER_CLIENTS = ['visionos', 'android_vr', 'tv', 'web_safari']

UPDATE_HINT = 'Try updating yt-dlp: pip install -U "yt-dlp[default]"'


class StreamError(Exception):
    pass


def _url_opens(url, headers):
    """True if YouTube accepts the request the way ffmpeg makes it (open-ended range).

    Some clients accept small ranges but return 403 for ffmpeg's "bytes=0-" request.
    Only the response headers are read, not the audio.
    """
    request = urllib.request.Request(url, headers={**headers, 'Range': 'bytes=0-'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status in (200, 206)
    except (urllib.error.URLError, TimeoutError):
        return False


def find_stream(query):
    """Return (url, title, client) for the first search result that can be streamed.

    Raises StreamError with a readable message when no client works.
    """
    problems = []
    for client in PLAYER_CLIENTS:
        options = dict(YDL_OPTIONS, extractor_args={'youtube': {'player_client': [client]}})
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
        except Exception as e:
            problems.append(f"{client}: {str(e).splitlines()[0][:120]}")
            continue
        if not info.get('entries'):
            raise StreamError(f"No YouTube results for '{query}'.")
        entry = info['entries'][0]
        if _url_opens(entry['url'], entry.get('http_headers', {})):
            return entry['url'], entry['title'], client
        problems.append(f"{client}: stream URL returned 403")
    raise StreamError("Could not get a working YouTube stream. " + UPDATE_HINT + "\n" + "\n".join(problems))
