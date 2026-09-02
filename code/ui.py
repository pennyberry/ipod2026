# iPod2026 - display: Sharp framebuffer, labels, marquee, render().
# `state` is runtime-bound by audio.py (ui.state = state) before
# the first render() call.

import time
import displayio
import framebufferio
import sharpdisplay
import board
from adafruit_display_text.label import Label
from terminalio import FONT

import settings as sd

state = None  # runtime-bound by audio.py; read by render()

# ============================================================
# Display
# ============================================================
displayio.release_displays()
framebuffer = sharpdisplay.SharpMemoryFramebuffer(
    board.SPI(), board.D6, 400, 240
)
# auto_refresh OFF: with it on, every label write schedules a display-
# refresh background task that competes with the MP3 decode callback for
# the same main-core background slot -> audio stutter while the UI scrolls.
# We instead push ONE explicit display.refresh() per render() (and per
# marquee tick), which batches all the label changes into a single frame
# and yields to the audio callback at the same time.
display = framebufferio.FramebufferDisplay(framebuffer, auto_refresh=False)
WIDTH, HEIGHT = 400, 240
ROW_H = 24
N_ROWS = 7

ui = displayio.Group()
display.root_group = ui

# Sharp memory-in-pixel panel: before the FIRST SPI write it shows its own
# power-on state (white/undefined), NOT our buffer -- and with auto_refresh
# off nothing is pushed until an explicit refresh(). The first real render()
# doesn't run until audio.py's boot gets past load_settings()/mount_sd(), so
# without this the panel sits white for that whole window. Push one all-black
# full frame NOW (empty group -> every pixel 0x00 = dark, and root_group was
# just set so this is a guaranteed full-screen write) to drive the whole
# 400x240 black immediately, well before the slow SD work in audio.py.
display.refresh()

title = Label(font=FONT, scale=2, text="")
title.x = 4
title.y = 8
ui.append(title)

# Now-Playing screen: classic iPod layout, centered. scale=3 for the
# title, scale=2 for everything else. All the labels sit inside the
# list rows' area (y 56..196), so they never collide with the banner
# (y=228). Centering is done by char count (fixed 6px cell font, so
# exact) with plain top-left anchors -- this firmware build's Label
# metrics are unreliable (see fit()) and its anchor_point values are
# limited, so render() recomputes x after every text change via
# _center().
np_title = Label(font=FONT, scale=3, text="")
np_title.x = 4
np_title.y = 56
ui.append(np_title)

np_artist = Label(font=FONT, scale=2, text="")
np_artist.x = 4
np_artist.y = 92
ui.append(np_artist)

np_album = Label(font=FONT, scale=2, text="")
np_album.x = 4
np_album.y = 116
ui.append(np_album)

# Progress: one full-width track of 32 cells ("#" = elapsed, "_" =
# remaining) with the times underneath, elapsed left / total right.
np_bar = Label(font=FONT, scale=2, text="")
np_bar.x = 4
np_bar.y = 146
ui.append(np_bar)

np_t1 = Label(font=FONT, scale=2, text="")
np_t1.x = 4
np_t1.y = 172
ui.append(np_t1)

np_t2 = Label(font=FONT, scale=2, text="")
np_t2.x = 4
np_t2.y = 172
ui.append(np_t2)

# Battery meter: fixed top-right slot (max text "100%" = 4 chars = 48px).
# battery_tick() refreshes the text (~1/s) only.
batt = Label(font=FONT, scale=2, text="")
batt.x = 344
batt.y = 8
ui.append(batt)

# 32 chars * 12px = 384px: full-width at scale=2.
sep = Label(font=FONT, scale=2, text="=" * 32)
sep.x = 4
sep.y = 34
ui.append(sep)

row_labels = []
for i in range(N_ROWS):
    lab = Label(font=FONT, scale=2, text="")
    lab.x = 4
    lab.y = 56 + i * ROW_H
    ui.append(lab)
    row_labels.append(lab)

banner = Label(font=FONT, scale=2, text="")
banner.x = 4
banner.y = 56 + N_ROWS * ROW_H + 4
ui.append(banner)

_mq_text = ""   # current banner text (for marquee scrolling)
_mq_win = 0     # how many chars fit in the banner width (pixels->chars)
_mq_off = 0     # current marquee scroll offset (chars)
_banner_dirty = False  # set by render() when the banner text changed; the
                       # marquee must not advance on that same tick or the
                       # first frame of a new (long) banner would be skipped


def fit(label, text, max_w):
    # This firmware build's Label.width is unreliable (it does not track
    # the rendered advance), so fit by char count instead: exact for this
    # fixed-cell font and immune to the width() bug.
    max_chars = max_w // CHAR_W
    if len(text) <= max_chars:
        label.text = text
        return label
    label.text = text[:max_chars - 3] + "..."
    return label


def _center(label, text, max_chars, char_w):
    """Set `label` to `text` (truncated with '...' if over max_chars) and
    center it horizontally by char count. Used by the Now-Playing screen's
    lines (char_w=12 at scale=2, 18 at scale=3)."""
    if len(text) > max_chars:
        text = text[:max_chars - 3] + "..."
    label.text = text
    label.x = max(4, (WIDTH - len(text) * char_w) // 2)
    return label


def _hide_nowplaying():
    # Blank the Now-Playing screen's labels (called on every render of any
    # other view, so the screen always comes back clean).
    np_title.text = ""
    np_artist.text = ""
    np_album.text = ""
    np_bar.text = ""
    np_t1.text = ""
    np_t2.text = ""


# terminalio FONT advance in pixels at scale=2, measured on the real panel:
# 24 chars spanned ~75% of the 400px width -> ~12px/char (a 6px cell x 2).
CHAR_W = 12


def _window(label, text, max_w):
    """Number of leading chars of `text` that fit in `max_w` pixels (this
    build's Label.width ignores scale, so pixels -> chars)."""
    return min(len(text), max_w // CHAR_W)


def _setup_banner(text, max_w):
    """Prepare the banner for (possible) marquee scrolling. Sets module
    state _mq_text/_mq_win/_mq_off and draws the first frame. Called from
    render() when the banner content changes."""
    global _mq_text, _mq_win, _mq_off, _banner_dirty
    _banner_dirty = _mq_text != text
    _mq_text = text
    if not text:
        _mq_win = 0
        _mq_off = 0
        banner.text = ""
        return
    _mq_win = _window(banner, text, max_w)
    if len(text) <= _mq_win:
        _mq_off = 0
        banner.text = text          # fits: static, no scroll
    else:
        _mq_off = 0
        banner.text = text[:_mq_win]  # first scroll frame


# Marquee throttle: the main loop ticks at 100 Hz, but scrolling one char
# per tick burns 100 label writes + (now) 100 refreshes per second -- pure
# SPI/CPU pressure that competes with the MP3 decode callback for the same
# background slot. Scroll ~12 chars/s instead (still smooth, ~1/8 the cost).
# Banner and row keep separate clocks so each scrolls at its own rate
# (only one is ever active at a time, but sharing one would halve it).
_MQ_STEP_S = 0.08
_mq_banner_t = 0.0
_mq_row_t = 0.0


def _advance_banner(max_w):
    """Tick the marquee forward one character (call every main-loop tick when
    the current view uses a marqueeable banner). Returns True when it actually
    wrote the label (caller must display.refresh() to make it visible).
    No-op if the banner is short or empty."""
    global _mq_off, _mq_banner_t
    if not _mq_text or len(_mq_text) <= _mq_win:
        return False
    if time.monotonic() - _mq_banner_t < _MQ_STEP_S:
        return False
    _mq_banner_t = time.monotonic()
    overflow = len(_mq_text) - _mq_win
    _mq_off += 1
    if _mq_off > overflow:
        _mq_off = 0  # tail fully exited -> wrap
    banner.text = _mq_text[_mq_off:_mq_off + _mq_win]
    return True


# Selected-row marquee (iPod style): the highlighted row scrolls its full
# text when the list is idle, so long titles are always readable. Other
# rows keep the ellipsis. Reset on every render (selection/rows change).
_selrow_text = ""   # full text of the highlighted row ("" = not scrolling)
_selrow_off = 0     # current scroll offset (chars)
_selrow_i = -1      # row_labels index currently scrolling (-1 = none)
_selrow_dirty = False  # set by render() on a new scroll target; the
                       # marquee must not advance on that same tick


def _setup_selrow(label, text, max_w):
    """Prepare the highlighted row for (possible) marquee scrolling.
    Returns True when the row will scroll."""
    global _selrow_text, _selrow_off
    max_chars = max_w // CHAR_W
    if len(text) <= max_chars:
        _selrow_text = ""
        label.text = text
        return False
    _selrow_text = text
    _selrow_off = 0
    label.text = text[:max_chars]  # first scroll frame
    return True


def _advance_selrow(max_w):
    """Tick the selected-row marquee forward one character (call every
    idle main-loop tick). Returns True when it wrote the label (caller must
    display.refresh()). No-op unless a row is currently scrolling."""
    global _selrow_off, _mq_row_t
    if _selrow_i < 0 or not _selrow_text:
        return False
    max_chars = max_w // CHAR_W
    if len(_selrow_text) <= max_chars:
        return False
    if time.monotonic() - _mq_row_t < _MQ_STEP_S:
        return False
    _mq_row_t = time.monotonic()
    _selrow_off += 1
    overflow = len(_selrow_text) - max_chars
    if _selrow_off > overflow:
        _selrow_off = 0  # tail fully exited -> wrap
    row_labels[_selrow_i].text = _selrow_text[_selrow_off:_selrow_off + max_chars]
    return True


def fmt_time(s):
    return "%d:%02d" % (s // 60, s % 60)


# Volume pop-out (Now-Playing screen): a turn of knob 3 arms this; while
# armed the banner shows the level, and it expires after 3s. The main
# loop flips _vol_pop back off (with _vol_dirty set) so a render fires
# that swaps the banner back to the normal status line.
_vol_pop = False
_vol_pop_t = 0
_vol_dirty = False


def render(snap):
    global _banner_dirty, _selrow_i, _selrow_text
    view, t, rows, hi, extra = snap
    if not (view == "nowplaying" and extra):
        _hide_nowplaying()
    fit(title, t, WIDTH - 84)  # -84 reserves the top-right battery meter
    if view in ("home", "artists", "albums", "tracks", "settings", "sdview"):
        # Scroll the visible window so the highlighted row is always on
        # screen. One smooth formula, no jumps: start follows the
        # selection (highlight sits ~mid-window), clamped to 0 at the
        # top and to the last 7 rows at the bottom.
        n = len(rows)
        start = 0
        if n > N_ROWS:
            start = max(0, min(hi - 3, n - N_ROWS))
        for i in range(N_ROWS):
            ri = start + i
            if 0 <= ri < n:
                prefix = "> " if ri == hi else "  "
                full = prefix + rows[ri]
                if ri == hi:
                    if _setup_selrow(row_labels[i], full, WIDTH - 8):
                        _selrow_i = i
                        _selrow_dirty = True
                    elif _selrow_i == i:
                        _selrow_i = -1
                else:
                    if _selrow_i == i:
                        _selrow_i = -1  # highlight left this row
                    fit(row_labels[i], full, WIDTH - 8)
            else:
                row_labels[i].text = ""
                if _selrow_i == i:
                    _selrow_i = -1
        if _selrow_i >= 0 and not (start <= hi < start + N_ROWS):
            # The highlighted row scrolled out of the visible window (or the
            # view/rows changed underneath): stop scrolling the old target.
            _selrow_i = -1
            _selrow_text = ""
        if view == "settings" and extra:
            if extra.get("editing"):
                fit(banner, "k1: char  k4: DEL  k3: back", WIDTH - 8)
            elif state.banner:
                # Transient result/status line (sound test, play errors):
                # draw it instead of the static hint so it's visible here.
                fit(banner, state.banner, WIDTH - 8)
            elif extra.get("saved"):
                fit(banner, "SAVED  (k2: reconnect)", WIDTH - 8)
            elif extra.get("nettest"):
                fit(banner, extra["nettest"], WIDTH - 8)
            else:
                fit(banner, "k1: select  k2: save", WIDTH - 8)
        elif view == "sdview" and extra:
            if not sd.sd_present:
                fit(banner, "insert card and reboot  (k3: back)", WIDTH - 8)
            elif extra.get("n", 0) == 0:
                fit(banner, "(empty)  k1: up  k3: back", WIDTH - 8)
            else:
                fit(banner, "k1: enter  k3: back  k4: up a level", WIDTH - 8)
        else:
            _setup_banner(state.banner, WIDTH - 8)
            _banner_dirty = True
    elif view == "nowplaying" and extra:
        # Clean centered layout: title (big), artist, album, then the
        # progress bar with times at each end. Everything else stays empty.
        e = extra
        _center(np_title, e["title"], 38, 18)
        _center(np_artist, e["artist"], 32, 12)
        _center(np_album, e["album"], 32, 12)
        dur = e["dur"]
        pos = min(e["pos"], dur)
        filled = (32 * pos // dur) if dur > 0 else 0
        np_bar.text = "#" * filled + "_" * (32 - filled)
        np_t1.text = fmt_time(pos)
        np_t2.text = fmt_time(dur)
        np_t2.x = WIDTH - len(np_t2.text) * 12 - 4
        for lab in row_labels:
            lab.text = ""
        if not e["playing"]:
            fit(banner, "PAUSED", WIDTH - 8)
        else:
            fit(banner, "k1: next/prev  k2: pause  k4: stop", WIDTH - 8)
        # Volume pop-out: for ~3s after a knob turn the banner shows the
        # level instead of the status line, then falls back on its own
        # (the main loop flips _vol_pop and the render key picks it up).
        if _vol_pop:
            vol = e["volume"]
            bar = "#" * (vol // 5) + "-" * (20 - vol // 5)
            fit(banner, "VOL [%s] %d" % (bar, vol), WIDTH - 8)
    # auto_refresh is off: push every label change this render made as ONE
    # frame, and let the audio background callback run at the same moment
    # (an explicit refresh runs background tasks, so this keeps audio fed).
    display.refresh()
