# iPod2026 - state machine (port of ipod2026/ipod/state.py).

import settings as sd

# ============================================================
# State machine (port of ipod2026/ipod/state.py, live-catalog version)
# ============================================================

SEEK_FAST_S = 10
# How many artist catalogs to keep in RAM at once (LRU). The current
# artist's catalog is shared with state.albums/track_cache (same list
# objects, no copy), so the extra cost is (N-1) full catalogs. 2 keeps
# the previous artist instant when you go back and re-enter it; drop to
# 1 (== no cache) if a very large artist makes RAM tight.
MAX_CAT_CACHE = 2
SETTING_CHARS = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                 "abcdefghijklmnopqrstuvwxyz .-_!@#$%&*+=/,:;<>")
MAX_SETTING_LEN = 48
SETTING_LABELS = ("Server URL", "API key", "WiFi SSID", "WiFi password",
                  "Audio format")
NET_TEST_LABEL = "Network test"
SOUND_TEST_LABEL = "Sound test"
SD_BROWSE_LABEL = "SD files"
REBUILD_LABEL = "Rebuild cache"
# rows = 5 editable settings + Network test + Sound test + Rebuild cache + SD files actions
SETTING_ROW_COUNT = len(SETTING_LABELS) + 4
CHOICES = {"Audio format": ("m3u8", "flac", "mp3")}
PASSWORD_KEYS = ("API key", "WiFi password")


class PlayerState(object):
    _view_name = "home"
    _browse_view = "home"

    def __init__(self):
        self.artists = []          # (id, name)
        self.artist_sel = 0
        self.artists_loaded = 0
        self.artists_total = 0     # true count from TotalRecordCount, if known
        self.artists_done = False  # True once the artist catalog is exhausted
        self._artists_rows = None  # memoized rows tuple (snapshot hot path)
        self._artists_rows_n = -1
        self._albums_rows = None   # memoized rows tuple (snapshot hot path)
        self._albums_rows_for = None  # albums list object the rows were built from
        self._tracks_rows = None
        self._tracks_rows_for = None  # tracks list object the rows were built from
        # Now-Playing album name, memoized by (queue_pos, queue, albums
        # objects) -- snapshot runs every tick, so this must not scan
        # self.albums (linear in album count) 100x per second.
        self._np_album_for = None
        self._np_album_name = ""
        self.artist_name = ""
        self.artist_id = ""
        self.albums = []           # (id, name, year)
        self.album_sel = 0
        self.track_cache = []      # (item_id, title, index, runtime, album_id) for current artist
        self.albums_loaded = False # True once the selected artist's catalog is in RAM
        self._catalog_pending = False  # one-shot: fetch the selected artist's catalog (RAM+SD miss)
        # Session-only catalog cache: artist_id -> (albums, tracks). Lives in
        # RAM only, so a reboot wipes it automatically -- cache cleared at
        # startup with zero code, and it can never hold data older than this
        # boot. LRU-bounded (MAX_CAT_CACHE).
        self.cat_cache = {}
        self._cat_order = []
        self.tracks = []           # tracks of current album
        self.track_sel = 0
        self.queue = []
        self.queue_pos = -1
        self.playing = False
        self.pos = 0
        self.dur = 0
        self.volume = 50
        self.settings = {}
        self.set_sel = 0
        self.set_editing = False
        self.set_cursor = 0
        self.set_saved = False
        self.banner = ""           # transient loading/status line
        self.net = ""              # persistent wifi status for the home title
        self.net_ok = False        # last egress test (8.8.8.8) passed
        self.net_test_msg = ""     # last manual network-test result line
        # SD card browser (Settings -> "SD files"): current dir + selection.
        self.sd_path = "/sd"
        self.sd_sel = 0

    def view(self):
        return self._view_name

    def _view_set(self, name):
        self._view_name = name

    # ---- I/O -> state: returns an audio intent string ----
    def on_event(self, ev):
        v = self._view_name
        if v in ("home", "artists", "albums", "tracks"):
            self._browse_view = v
        self.set_saved = False

        if ev == "BACK":
            if v == "nowplaying":
                self._view_set(self._browse_view)
            elif v == "settings":
                if self.set_editing:
                    self.set_editing = False
                else:
                    self._view_set("home")
            elif v == "sdview":
                self._view_set("settings")
            elif v == "tracks":
                self._view_set("albums")
            elif v == "albums":
                self._view_set("artists")
            elif v == "artists":
                self._view_set("home")
            return ""

        if v == "home":
            if ev in ("UP", "KNOB_CCW", "KNOB_CCW_FAST"):
                self.set_sel = (self.set_sel - 1) % 3
            elif ev in ("DOWN", "KNOB_CW", "KNOB_CW_FAST"):
                self.set_sel = (self.set_sel + 1) % 3
            elif ev == "SELECT":
                if self.set_sel == 0:
                    self._view_set("artists")
                elif self.set_sel == 1:
                    self._view_set("settings")
                else:
                    self._view_set("nowplaying")
            return ""

        if v == "artists":
            n = len(self.artists)
            if n == 0:
                return ""
            if ev in ("UP", "KNOB_CCW", "KNOB_CCW_FAST"):
                self.artist_sel = (self.artist_sel - 1) % n
            elif ev in ("DOWN", "KNOB_CW", "KNOB_CW_FAST"):
                self.artist_sel = (self.artist_sel + 1) % n
            elif ev == "SELECT":
                self._view_set("albums")
                self.artist_name = self.artists[self.artist_sel][1]
                self.artist_id = self.artists[self.artist_sel][0]
                cached = self.cat_cache.get(self.artist_id)
                if cached is not None:
                    # Session cache hit: instant, no spinner. albums and
                    # track_cache point at the same list objects the cache
                    # holds (no copy), so this costs nothing.
                    self.albums, self.track_cache = cached
                    self._cat_touch(self.artist_id)
                    self.albums_loaded = True
                    self.banner = ""
                else:
                    # SD cache hit: read the artist's catalog from the card
                    # (fast, offline). One SPI file read instead of dozens of
                    # ~300KB API requests.
                    c_albums, c_tracks = sd.sd_load_catalog(self.artist_id)
                    if c_albums is not None:
                        self.albums, self.track_cache = c_albums, c_tracks
                        self._cat_store(self.artist_id, c_albums, c_tracks)
                        self.albums_loaded = True
                        self.banner = ""
                    else:
                        # Cache miss: mark for a one-shot network fetch in
                        # the main loop (keeps this handler non-blocking).
                        self.albums = []
                        self.track_cache = []
                        self.albums_loaded = False
                        self._catalog_pending = True
                        self.banner = "loading albums..."
                self.album_sel = 0
            return ""

        if v == "albums":
            n = len(self.albums)
            if n == 0:
                return ""
            if ev in ("UP", "KNOB_CCW", "KNOB_CCW_FAST"):
                self.album_sel = (self.album_sel - 1) % n
            elif ev in ("DOWN", "KNOB_CW", "KNOB_CW_FAST"):
                self.album_sel = (self.album_sel + 1) % n
            elif ev == "SELECT":
                self._open_album(self.album_sel)
            return ""

        if v == "tracks":
            n = len(self.tracks)
            if n == 0:
                return ""
            if ev in ("UP", "KNOB_CCW", "KNOB_CCW_FAST"):
                self.track_sel = (self.track_sel - 1) % n
            elif ev in ("DOWN", "KNOB_CW", "KNOB_CW_FAST"):
                self.track_sel = (self.track_sel + 1) % n
            elif ev == "SELECT":
                self.queue = self.tracks
                self.queue_pos = self.track_sel
                self._start_track(self.tracks[self.track_sel])
                return "play:%s" % self.tracks[self.track_sel][0]
            return ""

        if v == "settings":
            return self._settings_event(ev)

        if v == "sdview":
            return self._sdview_event(ev)

        if v == "nowplaying":
            if not self.queue:
                return ""
            if ev in ("PLAY_PAUSE", "SELECT"):
                self.playing = not self.playing
                return "pause" if not self.playing else "resume"
            elif ev == "STOP":
                self.playing = False
                self.pos = 0
                return "stop"
            elif ev in ("NEXT", "KNOB_CW"):
                self.queue_pos = (self.queue_pos + 1) % len(self.queue)
                self._start_track(self.queue[self.queue_pos])
                return "play:%s" % self.queue[self.queue_pos][0]
            elif ev in ("PREV", "KNOB_CCW"):
                if self.pos > 3:
                    return "seek:0"
                self.queue_pos = (self.queue_pos - 1) % len(self.queue)
                self._start_track(self.queue[self.queue_pos])
                return "play:%s" % self.queue[self.queue_pos][0]
            elif ev == "KNOB_CW_FAST":
                return "seek:%d" % min(self.dur, self.pos + SEEK_FAST_S)
            elif ev == "KNOB_CCW_FAST":
                return "seek:%d" % max(0, self.pos - SEEK_FAST_S)
            elif ev == "VOL_UP":
                self.volume = min(100, self.volume + 5)
            elif ev == "VOL_DOWN":
                self.volume = max(0, self.volume - 5)
            return ""
        return ""

    # ---- state -> I/O: the thing the renderer draws ----
    def snapshot(self):
        v = self._view_name
        if v == "home":
            t = "Home"
            if self.net:
                t += "  " + self.net
            return ("home", t, ["Artists", "Settings", "Now Playing"],
                    self.set_sel, None)
        if v == "artists":
            n = len(self.artists)
            if self._artists_rows_n != n:
                self._artists_rows = tuple(name for _, name in self.artists)
                self._artists_rows_n = n
            rows = self._artists_rows
            t = "Artists"
            if self.artists_total:
                t += " (%d/%d)" % (self.artists_loaded, self.artists_total)
            elif n:
                t += " (%d)" % n
            return ("artists", t, rows, self.artist_sel, None)
        if v == "albums":
            rows = ["%s  (%s)" % (a[1], a[2] or "?") for a in self.albums]
            return ("albums", self.artist_name, rows, self.album_sel, None)
        if v == "tracks":
            rows = ["%s. %s" % (t[2] or i + 1, t[1]) for i, t in enumerate(self.tracks)]
            title = self.artist_name
            if self.albums:
                title += " - " + self.albums[self.album_sel][1]
            return ("tracks", title, rows, self.track_sel, None)
        if v == "settings":
            rows = []
            for i, key in enumerate(SETTING_LABELS):
                val = self.settings.get(key, "")
                if key in PASSWORD_KEYS and not (self.set_editing and i == self.set_sel):
                    val = "*" * len(val) if val else ""
                rows.append("%s: %s" % (key, val))
            rows.append(NET_TEST_LABEL + " [8.8.8.8]")
            # Sound test: play /sd/test.mp3 through the I2S DAC so we can
            # check the real decode path with a known file (host plays it).
            rows.append(SOUND_TEST_LABEL + " [test.mp3]")
            # Rebuild cache: wipe the SD library cache, then refetch artists
            # and every opened artist's catalog. Slow (full library), so it's
            # an explicit action, not something we do at boot.
            rows.append(REBUILD_LABEL + (" (wipe + refetch)" if sd.sd_present else " (no card)"))
            if sd.sd_present:
                rows.append(SD_BROWSE_LABEL + " [mounted]")
            else:
                rows.append(SD_BROWSE_LABEL + " [no card]")
            return ("settings", "Settings" + (" (editing)" if self.set_editing else ""),
                    rows, self.set_sel,
                    {"editing": self.set_editing, "saved": self.set_saved,
                     "nettest": self.net_test_msg})
        if v == "sdview":
            if not sd.sd_present:
                return ("sdview", "SD card",
                        ["not mounted", (sd.sd_err or "unknown error"), ""],
                        0, {"path": "", "n": 0})
            # Serve the cached listing (list_dir re-stats only when
            # sd_path changes), dirs first, then files.
            try:
                dirs, files = sd.list_dir(self.sd_path)
            except OSError:
                dirs, files = [], []
            rows = ["  " + name + "/" for name, _ in dirs]
            for name, size in files:
                if size >= 1048576:
                    sz = "%d.%dM" % (size // 1048576, (size % 1048576) // 104857)
                elif size >= 1024:
                    sz = "%dK" % (size // 1024)
                else:
                    sz = "%d" % size
                rows.append("  " + name + "  (%s)" % sz)
            n = len(rows)
            # relative path in the title: /sd, /sd/Music, ...
            rel = self.sd_path
            if rel.startswith(sd.SD_ROOT):
                rel = rel[len(sd.SD_ROOT):]
            title = "SD" + rel
            return ("sdview", title, rows, self.sd_sel,
                    {"path": self.sd_path, "n": n})
        # nowplaying
        t = self.queue[self.queue_pos] if 0 <= self.queue_pos < len(self.queue) else None
        np = {
            "title": t[1] if t else "Nothing playing",
            "artist": self.artist_name,
            "album": self._current_album_name(),
            "pos": self.pos, "dur": self.dur,
            "playing": self.playing, "volume": self.volume,
        }
        return ("nowplaying", "Now Playing", [], -1, np)

    # ---- internals ----
    def _open_album(self, i):
        album_id = self.albums[i][0]
        self.tracks = [t for t in self.track_cache if t[4] == album_id]
        self.track_sel = 0
        self._view_set("tracks")

    # ---- session catalog cache (LRU, RAM only) ----
    def _cat_store(self, artist_id, albums, tracks):
        if artist_id in self.cat_cache:
            self._cat_order.remove(artist_id)
        self.cat_cache[artist_id] = (albums, tracks)
        self._cat_order.append(artist_id)
        while len(self._cat_order) > MAX_CAT_CACHE:
            oldest = self._cat_order.pop(0)
            self.cat_cache.pop(oldest, None)

    def _cat_touch(self, artist_id):
        if artist_id in self._cat_order:
            self._cat_order.remove(artist_id)
        self._cat_order.append(artist_id)

    def _cat_clear(self):
        self.cat_cache = {}
        self._cat_order = []

    def _current_album_name(self):
        if 0 <= self.queue_pos < len(self.queue):
            aid = self.queue[self.queue_pos][4]
            for a in self.albums:
                if a[0] == aid:
                    return a[1]
        return ""

    def _start_track(self, t):
        self.dur = t[3]
        self.pos = 0
        self.playing = True
        self._view_set("nowplaying")

    def _setting_value(self, i):
        return self.settings.get(SETTING_LABELS[i], "")

    def _set_setting_value(self, i, val):
        self.settings[SETTING_LABELS[i]] = val

    def _settings_event(self, ev):
        if self.set_editing:
            if ev.startswith("KEY:"):
                ch = ev[4:]
                val = self._setting_value(self.set_sel)
                if self.set_cursor > len(val):
                    self.set_cursor = len(val)
                val = val[:self.set_cursor] + ch + val[self.set_cursor:]
                if len(val) > MAX_SETTING_LEN:
                    val = val[:MAX_SETTING_LEN]
                self.set_cursor = min(self.set_cursor + len(ch), len(val))
                self._set_setting_value(self.set_sel, val)
            elif ev.startswith("DEL:"):
                val = self._setting_value(self.set_sel)
                if self.set_cursor > len(val):
                    self.set_cursor = len(val)
                val = val[:self.set_cursor - 1] + val[self.set_cursor:]
                self.set_cursor = max(0, self.set_cursor - 1)
                self._set_setting_value(self.set_sel, val)
            elif ev in ("KNOB_CW", "KNOB_CCW", "KNOB_CW_FAST", "KNOB_CCW_FAST"):
                step = 1 if ev in ("KNOB_CW", "KNOB_CW_FAST") else -1
                if ev.endswith("_FAST"):
                    step *= 5
                val = self._setting_value(self.set_sel)
                if not val:
                    self._set_setting_value(
                        self.set_sel,
                        SETTING_CHARS[0 if step > 0 else len(SETTING_CHARS) - 1])
                    self.set_cursor = 1
                else:
                    ci = (SETTING_CHARS.index(val[self.set_cursor - 1])
                          if val[self.set_cursor - 1] in SETTING_CHARS else 0)
                    ch = SETTING_CHARS[(ci + step) % len(SETTING_CHARS)]
                    self._set_setting_value(
                        self.set_sel,
                        val[:self.set_cursor - 1] + ch + val[self.set_cursor:])
            return ""

        if ev in ("UP", "KNOB_CCW", "KNOB_CCW_FAST"):
            self.set_sel = (self.set_sel - 1) % SETTING_ROW_COUNT
        elif ev in ("DOWN", "KNOB_CW", "KNOB_CW_FAST"):
            self.set_sel = (self.set_sel + 1) % SETTING_ROW_COUNT
        elif ev == "SELECT":
            if self.set_sel == len(SETTING_LABELS):
                return "nettest"  # Network test row: host runs the egress test
            if self.set_sel == len(SETTING_LABELS) + 1:
                # Sound test row: host plays /sd/test.mp3 through the DAC.
                return "soundtest"
            if self.set_sel == len(SETTING_LABELS) + 2:
                # Rebuild cache row: host wipes the SD cache and refetches.
                return "rebuild"
            if self.set_sel == len(SETTING_LABELS) + 3:
                # SD files row: open the card browser (host preps the view).
                self.sd_path = sd.SD_ROOT
                self.sd_sel = 0
                self._view_set("sdview")
                return ""
            key = SETTING_LABELS[self.set_sel]
            if key in CHOICES:
                choices = CHOICES[key]
                cur = choices.index(self._setting_value(self.set_sel)) \
                    if self._setting_value(self.set_sel) in choices else -1
                self._set_setting_value(self.set_sel, choices[(cur + 1) % len(choices)])
            else:
                self.set_editing = True
                self.set_cursor = len(self._setting_value(self.set_sel))
        elif ev == "PLAY_PAUSE":
            self.set_saved = True
        return ""

    def _sdview_event(self, ev):
        """SD card file browser. Rows: dirs first (trailing '/'), then
        files. k1 SELECT: enter dir (file = no-op, audio backend not
        wired yet). k4 STOP: up a level. k3 BACK: settings."""
        if not sd.sd_present:
            return ""
        dirs, files = sd.list_dir(self.sd_path)
        n = len(dirs) + len(files)
        if n == 0:
            # empty dir: k1 jumps up a level (k3 does the same via BACK)
            if ev == "SELECT":
                up = sd.parent(self.sd_path)
                if up is not None:
                    self.sd_path = up
                    self.sd_sel = 0
            return ""
        if ev in ("UP", "KNOB_CCW", "KNOB_CCW_FAST"):
            self.sd_sel = (self.sd_sel - 1) % n
        elif ev in ("DOWN", "KNOB_CW", "KNOB_CW_FAST"):
            self.sd_sel = (self.sd_sel + 1) % n
        elif ev == "SELECT":
            if self.sd_sel < len(dirs):
                self.sd_path = self.sd_path + "/" + dirs[self.sd_sel][0]
                self.sd_sel = 0
            # files: nothing to play yet (audio backend not wired)
        elif ev == "STOP":
            up = sd.parent(self.sd_path)
            if up is not None:
                self.sd_path = up
                self.sd_sel = 0
        return ""
