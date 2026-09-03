# iPod2026 - settings.json, WiFi connect, SD mount + browse +
# library cache.

import json
import time
import os
import sys

import board
import digitalio
import busio
import adafruit_sdcard
import storage

# ============================================================
# Settings + WiFi
# ============================================================

SETTINGS_FILE = "settings.json"
ENV_FILE = ".env"


def load_env():
    """Parse .env (KEY=VALUE lines, # comments, optional quotes) from the
    flash root. Missing file or bad lines are ignored: a fresh clone with
    no .env just gets blank fields to fill in via the Settings UI."""
    env = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                env[k] = v
    except Exception:
        pass
    return env


def load_settings():
    e = load_env()
    s = {"Server URL": e.get("SERVER_URL", ""), "API key": e.get("API_KEY", ""),
         "WiFi SSID": e.get("WIFI_SSID", ""), "WiFi password": e.get("WIFI_PASSWORD", ""),
         "Audio format": "m3u8"}
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        for k in s:
            if k in data and data[k] is not None:
                s[k] = data[k]
    except Exception:
        pass
    return s


def save_settings(d):
    out = "{\n"
    for k in ("Server URL", "API key", "WiFi SSID", "WiFi password", "Audio format"):
        v = str(d.get(k, "")).replace('\\', '\\\\').replace('"', '\\"')
        out += '  "%s": "%s",\n' % (k, v)
    out = out.rstrip(',\n') + "\n}\n"
    with open(SETTINGS_FILE, 'w') as f:
        f.write(out)


def wifi_connect(ssid, password):
    import wifi

    if not ssid:
        return None
    # wifi.radio has NO disconnect() or reset(): toggle `enabled` to drop
    # the link (this also closes any open sockets), then reconnect with the
    # new credentials.
    wifi.radio.enabled = False
    wifi.radio.enabled = True
    try:
        wifi.radio.connect(ssid, password)
    except Exception:
        return None
    t0 = time.monotonic()
    while not wifi.radio.connected:
        if time.monotonic() - t0 > 30:
            return None
        time.sleep(0.2)
    # ipv4_address is an ipaddress.IPv4Address object, not a str —
    # str() gives the dotted quad.
    return str(wifi.radio.ipv4_address)
# ============================================================
# SD card (board SPI: SCK/MOSI/MISO, CS on board.SD_CS = GPIO45)
# Mounted read-browse at /sd. Mount is attempted once at boot and
# its outcome remembered: SD_OK if usable, SD_DOWN with a reason if
# not (the home banner shows the reason; the Settings "SD files"
# row then opens to the error message instead of a listing).
# NOTE: Metro ESP32-S3 SD support needs recent firmware -- early
# builds (8.1/8.2) hit the octal-flash/SD_CS conflict (github
# adafruit/circuitpython#8288, fixed since). If mount fails with a
# watchdog/safe-mode-ish error, update the firmware before wiring
# anything else.
# ============================================================

import os
import sys

import busio
import adafruit_sdcard
import storage

SD_OK = True
SD_DOWN = False
sd_present = False
sd_err = ""          # "" when ok, else short reason for the banner
SD_ROOT = "/sd"

# Directory listing cache: the main loop calls snapshot() every tick, so we
# must NOT re-stat the card over SPI 100x/sec. list_dir() below serves the
# cache while the path is unchanged; navigation (entering a dir / going up)
# just changes state.sd_path, and the next list_dir() call re-lists once.
_sd_listing = {"path": None, "entries": None}


def list_dir(path):
    """(dirs, files) for `path`, cached. dirs/files are lists of (name, size),
    dirs first, both sorted case-insensitively, dotfiles skipped."""
    if _sd_listing["path"] == path and _sd_listing["entries"] is not None:
        return _sd_listing["entries"]
    try:
        names = os.listdir(path)
    except OSError:
        names = []
    dirs = []
    files = []
    for name in names:
        if name.startswith("."):
            continue
        full = path + "/" + name
        try:
            st = os.stat(full)
        except OSError:
            continue
        if (st[0] & 0x4000) != 0:      # S_IFDIR
            dirs.append((name, 0))
        else:
            files.append((name, st[6] or 0))
    dirs.sort(key=lambda d: d[0].lower())
    files.sort(key=lambda f: f[0].lower())
    _sd_listing["path"] = path
    _sd_listing["entries"] = (dirs, files)
    return _sd_listing["entries"]


def parent(path):
    """Parent of an /sd-relative absolute path; None at the root."""
    if path == SD_ROOT:
        return None
    cut = path.rstrip("/").rfind("/")
    if cut <= 0:
        return SD_ROOT
    p = path[:cut]
    return p if p else SD_ROOT


def mount_sd():
    """Mount the SD card once at boot. Sets sd_present/sd_err.

    The card shares the board SPI bus with the Sharp display (both use
    GPIO39/42/21), so we must pass the SAME busio.SPI singleton the
    display holds (board.SPI()), NOT a fresh busio.SPI(...) -- a second
    SPI object on the same pins raises a pin-conflict. The bus is only
    locked per-transaction (display writes and SD reads each grab it
    briefly), so the two coexist fine. CS is on board.SD_CS (GPIO45),
    independent of the display's D6 (GPIO6) CS."""
    global sd_present, sd_err
    try:
        spi = board.SPI()
        cs = digitalio.DigitalInOut(board.SD_CS)
        sdcard = adafruit_sdcard.SDCard(spi, cs)
        vfs = storage.VfsFat(sdcard)
        storage.mount(vfs, SD_ROOT)
        sys.path.append(SD_ROOT)   # lets code.py files on the card load too
        sd_present = True
    except Exception as e:
        sd_present = False
        sd_err = str(e)[:40] or "mount failed"
        try:
            print("SD MOUNT ERROR:", repr(e))
        except Exception:
            pass


# ============================================================
# SD library cache
#   The API (Jellyfin) is slow: paging an artist's whole catalog is dozens
#   of ~300KB requests. So we front-load the data onto the SD card ONCE,
#   then the UI reads from the card (fast, and works offline).
#
#   Layout under /sd/cache:
#     artists.json            {"total":N, "items":[[id,name], ...]}
#     cat_<artist_id>.json    {"albums":[[id,name,year], ...],
#                              "tracks":[[id,title,index,secs,album_id],...]}
#     art/<album_id>.jpg      album artwork (JPEG, ~230x230), one file per
#                             album; a missing file = no art for that album.
#
#   The card already holds code.py/settings.json; the cache lives in its own
#   /sd/cache subdir so the SD-file browser can see (and delete) it.
# ============================================================
SD_CACHE_DIR = "/sd/cache"
ARTISTS_CACHE = "/sd/cache/artists.json"


def _sd_cache_dir():
    """Ensure /sd/cache exists. Returns True if usable."""
    if not sd_present:
        return False
    try:
        os.stat(SD_CACHE_DIR)
    except OSError:
        try:
            os.mkdir(SD_CACHE_DIR)
        except OSError:
            return False
    return True


def sd_store_artists(artists, total):
    """Write the full artist list to the card cache. artists: [(id, name)]."""
    if not _sd_cache_dir():
        return
    try:
        with open(ARTISTS_CACHE, "w") as f:
            f.write(json.dumps({"total": total,
                                "items": [list(a) for a in artists]},
                               separators=(',', ':')))
    except OSError:
        pass


def sd_load_artists():
    """Read the artist list cache. -> ([(id, name)], total) or ([], 0)."""
    if not sd_present:
        return [], 0
    try:
        with open(ARTISTS_CACHE) as f:
            data = json.load(f)
    except (OSError, Exception):
        return [], 0
    if not isinstance(data, dict):
        return [], 0
    items = data.get("items") or []
    total = data.get("total") or 0
    return [tuple(a) for a in items if isinstance(a, (list, tuple)) and len(a) >= 2], total


def _cat_cache_path(artist_id):
    return "/sd/cache/cat_%s.json" % artist_id


def sd_store_catalog(artist_id, albums, tracks):
    """Write one artist's albums+tracks to the card cache."""
    if not _sd_cache_dir():
        return
    try:
        with open(_cat_cache_path(artist_id), "w") as f:
            f.write(json.dumps({"albums": [list(a) for a in albums],
                                "tracks": [list(t) for t in tracks]},
                               separators=(',', ':')))
    except OSError:
        pass


def sd_load_catalog(artist_id):
    """Read one artist's catalog. -> (albums, tracks) or (None, None)."""
    if not sd_present:
        return None, None
    try:
        with open(_cat_cache_path(artist_id)) as f:
            data = json.load(f)
    except (OSError, Exception):
        return None, None
    if not isinstance(data, dict):
        return None, None
    albums = data.get("albums") or []
    tracks = data.get("tracks") or []
    return ([tuple(a) for a in albums if isinstance(a, (list, tuple))],
            [tuple(t) for t in tracks if isinstance(t, (list, tuple))])


def sd_clear_catalogs():
    """Delete all per-artist catalog cache files (keeps artists.json)."""
    if not sd_present:
        return
    try:
        for name in os.listdir(SD_CACHE_DIR):
            if name.startswith("cat_") and name.endswith(".json"):
                try:
                    os.remove(SD_CACHE_DIR + "/" + name)
                except OSError:
                    pass
    except OSError:
        pass


# ============================================================
# Album artwork cache (JPEG files under /sd/cache/art/)
#   One file per album, named by the Jellyfin item id. The art is
#   fetched lazily when an artist's catalog loads (see audio.py) and
#   drawn on the Now-Playing screen from this card cache -- so it
#   works offline once cached. A missing file simply means "no art".
# ============================================================
ART_DIR = "/sd/cache/art"


def _art_path(album_id):
    return ART_DIR + "/" + album_id + ".jpg"


def sd_store_art(album_id, data):
    """Write one album's artwork bytes to the card. Best-effort: a full
    or failing card just means no art for that album (never an error)."""
    if not _sd_cache_dir():
        return False
    try:
        os.stat(ART_DIR)
    except OSError:
        try:
            os.mkdir(ART_DIR)
        except OSError:
            return False
    try:
        with open(_art_path(album_id), "wb") as f:
            f.write(data)
        return True
    except (OSError, Exception):
        return False


def sd_load_art(album_id):
    """Read one album's artwork bytes from the card. -> bytes or None."""
    if not sd_present:
        return None
    try:
        with open(_art_path(album_id), "rb") as f:
            return f.read()
    except (OSError, Exception):
        return None


def sd_clear_art():
    """Delete all cached artwork files."""
    if not sd_present:
        return
    try:
        for name in os.listdir(ART_DIR):
            if name.endswith(".jpg"):
                try:
                    os.remove(ART_DIR + "/" + name)
                except OSError:
                    pass
    except OSError:
        pass
