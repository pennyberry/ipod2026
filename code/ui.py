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

try:
    from jpegio import JpegDecoder
except ImportError:
    JpegDecoder = None   # firmware without jpegio: no art, text-only NP screen
if JpegDecoder is not None:
    try:
        from displayio import ColorConverter, Colorspace
    except ImportError:
        ColorConverter = None

import settings as sd

state = None  # runtime-bound by audio.py; read by render()

# ============================================================
# Display
# ============================================================
#clear previous displayio root_group (if any) so we can take over the SPI bus
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
#initialize the display with a blank frame
display.refresh()

title = Label(font=FONT, scale=2, text="")
title.x = 4
title.y = 8
ui.append(title)

# Now-Playing screen: big album art on the left (ART_W x ART_H), with a
# text column to its right -- song title, artist, album (each word-wrapped
# onto up to 3 / 2 / 2 lines so long names don't get cut off), then the
# progress bar and times. All scale=2; every label's position is written by
# render() each tick (this firmware build's Label metrics are unreliable --
# see fit() -- so nothing relies on anchors). Without art the first line of
# each field centers across the full width instead.
NP_TXT_X = 244                    # left edge of the text column (right of art)
NP_TXT_W = WIDTH - NP_TXT_X - 4   # 152px -> 12 chars at scale=2
NP_LH = 18                        # line height for wrapped fields
# Field labels: [line1, line2, line3]. render() positions them per field --
# a one-line field uses only its first label; the rest are blanked.
np_title = []
for i in range(3):
    lab = Label(font=FONT, scale=2, text="")
    lab.x = NP_TXT_X
    lab.y = 56 + i * NP_LH
    ui.append(lab)
    np_title.append(lab)

np_artist = []
for i in range(2):
    lab = Label(font=FONT, scale=2, text="")
    lab.x = NP_TXT_X
    lab.y = 56 + 3 * NP_LH + i * NP_LH   # after the title's max of 3 lines
    ui.append(lab)
    np_artist.append(lab)

np_album = []
for i in range(2):
    lab = Label(font=FONT, scale=2, text="")
    lab.x = NP_TXT_X
    lab.y = 56 + 5 * NP_LH + i * NP_LH   # after artist's max of 2 lines
    ui.append(lab)
    np_album.append(lab)

# Progress: a track of cells ("#" = elapsed, "_" = remaining) with the
# times underneath, elapsed left / total right. Fixed at the bottom of the
# text column (below the fields' max extent); 12 cells in the art layout
# (fits the column), 32 full-width in the no-art fallback.
np_bar = Label(font=FONT, scale=2, text="")
np_bar.x = NP_TXT_X
np_bar.y = 56 + 7 * NP_LH          # 196: below every field's last line
ui.append(np_bar)

np_t1 = Label(font=FONT, scale=2, text="")
np_t1.x = NP_TXT_X
np_t1.y = np_bar.y + 24            # 220; banner row starts at y=228
ui.append(np_t1)

np_t2 = Label(font=FONT, scale=2, text="")
np_t2.x = WIDTH - 4
np_t2.y = np_t1.y
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

# Now-Playing album art: a JPEG decoded from the SD cache into an RGB565
# bitmap, shown as a TileGrid. The Sharp panel is 1-bit grayscale (the
# framebuffer driver reports get_grayscale=True), so a ColorConverter maps
# each decoded pixel to black/white by luminance -- jpegio writes full
# RGB565 values into the bitmap, and TileGrid REQUIRES a pixel_shader
# (None raises TypeError at construction). The tile fills most of the
# screen on the left; the text column sits right of it. Height stops 3px
# short of the banner row (y=228) so the status line never overlaps art.
# One JpegDecoder + one Bitmap are reused for every album (a fresh decode
# allocates a few KB each time, so reusing keeps RAM flat across track
# changes).
ART_W = 230
ART_H = 220
art_decoder = None
art_bitmap = None
art_tile = None
if JpegDecoder is not None and ColorConverter is not None:
    try:
        art_decoder = JpegDecoder()
        art_bitmap = displayio.Bitmap(ART_W, ART_H, 65535)
        # jpegio decodes into RGB565 (its own test suite reads pixels back
        # with the 0x7E0 green mask), so convert from RGB565. The converter
        # thresholds to the panel's single bit by luminance: dark JPEG
        # areas -> ink, light areas -> paper.
        art_tile = displayio.TileGrid(
            art_bitmap,
            pixel_shader=displayio.ColorConverter(
                input_colorspace=displayio.Colorspace.RGB565))
        art_tile.x = 4
        art_tile.y = 5
        ui.append(art_tile)
        # Hidden until a Now-Playing render decodes real art: the bitmap is
        # zero-filled at creation, and on this monochrome panel that would
        # draw as a solid black box in the top-left corner of EVERY screen.
        art_tile.hidden = True
    except Exception:
        # decoder/bitmap/shader alloc failed (low RAM): fall back to
        # text-only NP
        art_decoder = None
        art_bitmap = None
        art_tile = None
_art_shown_for = ""   # album id currently decoded onto the tile (""), and
                      # whether its bitmap is dithered (see _dither_art)


def _bayer8():
    """The 8x8 Bayer ordered-dither matrix, normalized to [0,1). NOT a naive
    y*8+x ramp -- the boustrophedonic ordering spreads thresholds so adjacent
    cells rarely share one (a ramp bands and moires)."""
    m = [[0,   32, 8,  40, 2,  34, 10, 42],
         [48, 16, 56, 24, 50, 18, 58, 26],
         [12, 44, 4,  36, 14, 46, 6,  38],
         [60, 28, 52, 20, 62, 30, 54, 22],
         [3,   35, 11, 43, 1,  33, 9,  41],
         [51, 19, 59, 27, 49, 17, 57, 25],
         [15, 47, 7,  39, 13, 45, 5,  37],
         [63, 31, 55, 23, 61, 29, 53, 21]]
    return [[v / 64.0 for v in row] for row in m]


# Dithering tables (built once at import; ~78KB total -- fine on this board:
# the 230x220 RGB565 bitmap alone is ~100KB, and the Metro ESP32-S3 has MBs
# of PSRAM). The panel is 1-bit: the ColorConverter thresholds each decoded
# pixel to ink/paper by luminance, and a plain threshold on a photo bands --
# flat grey regions lose all their tonal gradation. Bayer ordered dithering
# instead maps every pixel through a position-dependent threshold, so
# mid-tones become a regular dot lattice the eye averages into smooth grey
# (the classic iPod look). Two tables make the per-pixel pass one lookup +
# one multiply:
#   _dith_lum[v]  = luminance bucket of RGB565 pixel v (0..1023), for all
#                   65536 possible pixels -- Rec.601 weights on the 5/6-bit
#                   channels, r5*629 + g6*608 + b5*240 >> 6 (black -> 0).
#   _dith_tab[b*64 + (y&7)*8 + (x&7)] = 0xFFFF paper / 0 ink for that pixel.
_dith_lum = None
_dith_tab = None
if art_bitmap is not None:
    try:
        _b = _bayer8()
        _dith_lum = [(((v >> 11) & 31) * 629 + ((v >> 5) & 63) * 608
                      + (v & 31) * 240) // 64 for v in range(65536)]
        _dith_tab = []
        for b in range(1024):
            f = b / 1024.0
            row = [0xFFFF if f > t else 0 for t in _b[0]] + \
                  [0xFFFF if f > t else 0 for t in _b[1]] + \
                  [0xFFFF if f > t else 0 for t in _b[2]] + \
                  [0xFFFF if f > t else 0 for t in _b[3]] + \
                  [0xFFFF if f > t else 0 for t in _b[4]] + \
                  [0xFFFF if f > t else 0 for t in _b[5]] + \
                  [0xFFFF if f > t else 0 for t in _b[6]] + \
                  [0xFFFF if f > t else 0 for t in _b[7]]
            _dith_tab += row
    except Exception:
        # table alloc failed (low RAM): keep the plain threshold path
        _dith_lum = None
        _dith_tab = None

# Optional histogram stretch before dithering (0 = off, 1 = on). Dark or
# low-contrast covers collapse under any dither -- their luminance range is
# too narrow for the dots to spread. Stretch maps [p2, p98] of the decoded
# region onto full 0..1023 first. Off by default: on already-decent art it
# adds dot-static in flat backgrounds. Flip to 1 if covers look washed out.
ART_STRETCH = 0

# Chunked dither state: _dith_active means "a decode is waiting for its
# dither pass"; the tile stays hidden until _advance_dither() finishes it,
# so a half-dithered frame never reaches the panel.
_dith_active = False
_dith_x = 0
_dith_y = 0
_dith_w = 0
_dith_h = 0
_dith_row = 0
_dith_lo = 0      # stretch range (luminance buckets), computed once per decode
_dith_hi = 1023
_DITH_ROWS_PER_TICK = 16   # ~4K pixel passes per tick: a few ms at most, so
                           # the MP3 decode callback keeps its background slot


def _advance_dither(show):
    """Dither the pending region in row chunks (call from render() EVERY
    tick; no-op unless a pass is armed). Returns True when it just finished.
    The tile stays hidden until then, and is only revealed when `show` is
    true -- i.e. we are still on the Now-Playing screen: if the user backed
    out mid-pass the finish is cancelled instead of flashing art onto some
    other view (the memo keeps holding, so returning to Now Playing shows it
    instantly with zero re-decode). A full 230x230 cover takes ~15 ticks
    (~0.15s at the 100 Hz main loop) -- one short pause per album change."""
    global _dith_active, _dith_row
    if not _dith_active:
        return False
    lum = _dith_lum
    tab = _dith_tab
    bm = art_bitmap
    if tab is None or lum is None or bm is None:
        # Tables failed to allocate (low RAM): skip dithering; the
        # ColorConverter's plain luminance threshold still draws the art.
        _dith_active = False
        return True
    x0 = _dith_x
    w = _dith_w
    stretch = ART_STRETCH != 0 and (_dith_hi > _dith_lo + 1)
    span = _dith_hi - _dith_lo if stretch else 0
    for r in range(_dith_row, min(_dith_row + _DITH_ROWS_PER_TICK,
                                  _dith_y + _dith_h)):
        base = r * ART_W
        trow = (r & 7) << 3
        if stretch:
            lo = _dith_lo
            for c in range(x0, x0 + w):
                b = lum[bm[base + c]]
                b = ((b - lo) * 1024 // span) if b > lo else 0
                bm[base + c] = tab[b * 64 + trow + (c & 7)]
        else:
            for c in range(x0, x0 + w):
                bm[base + c] = tab[lum[bm[base + c]] * 64 + trow + (c & 7)]
    _dith_row += _DITH_ROWS_PER_TICK
    if _dith_row >= _dith_y + _dith_h:
        _dith_active = False
        if show and art_tile is not None:
            art_tile.hidden = False   # done, still on Now Playing -> reveal
        return True
    return False


def _show_art(album_id):
    """Decode the album's cached JPEG onto the art tile and start its dither
    pass (chunked across ticks by render() calling _advance_dither()).
    Returns True when art is (or will be) visible. Memoized by album id:
    render() runs every tick while a track plays, so only an album CHANGE
    re-reads the card and re-decodes (~2-4KB SPI read + 230x230 decode). A
    missing/corrupt file hides the tile -- and clears any STALE art from a
    previous album, since render() never repaints the tile on its own (auto_
    refresh is off), so without this the old cover would sit on screen for
    the new track. The tile itself stays hidden until dithering completes:
    _art_shown_for is set at DECODE time (so the memo holds while the pass
    runs) and only the visibility flag waits."""
    global _art_shown_for, _dith_active, _dith_x, _dith_y, _dith_w, \
        _dith_h, _dith_row, _dith_lo, _dith_hi
    if art_tile is None or not album_id:
        _hide_art()
        return False
    if album_id == _art_shown_for:
        # Already decoded (dither pass may still be running -- render()
        # drives it; the tile reveals itself when it finishes).
        return True
    data = sd.sd_load_art(album_id)
    if not data:
        _hide_art()
        return False
    try:
        w, h = art_decoder.open(data)
        # The server scales to fit maxWidth/maxHeight (aspect preserved), so
        # the image is <= ART_W x ART_H -- but a SQUARE cover fetched at
        # 230x230 can be TALLER than the 230x220 tile, and a wide/short one
        # leaves margin rows. The bitmap is reused across albums (zero-filled
        # only at creation), so first clear it to paper: anything outside the
        # decoded region would otherwise show STALE pixels from the previous
        # album on this monochrome panel. Then decode into its spot.
        for i in range(ART_W * ART_H):
            art_bitmap[i] = 0xFFFF
        x = max(0, (ART_W - w) // 2)
        y = max(0, (ART_H - h) // 2)
        art_decoder.decode(art_bitmap, x=x, y=y)
    except Exception:
        return False
    # Arm the chunked dither pass over the region that was ACTUALLY decoded:
    # the intersection of the image's placement and the tile (clamped -- a
    # 230x230 cover clipped to the 230x220 tile must not index past the end).
    ix = max(x, 0)
    iy = max(y, 0)
    iw = min(w, ART_W - ix)
    ih = min(h, ART_H - iy)
    if iw <= 0 or ih <= 0:
        art_tile.hidden = False   # degenerate placement; paper tile is fine
        _art_shown_for = album_id
        return True
    _dith_x, _dith_y, _dith_w, _dith_h = ix, iy, iw, ih
    _dith_row = 0
    if ART_STRETCH and _dith_lum is not None:
        # One histogram pass over the region -> [p2, p98] luminance buckets.
        hist = [0] * 1024
        for r in range(y, y + h):
            base = r * ART_W
            for c in range(x, x + w):
                hist[_dith_lum[art_bitmap[base + c]]] += 1
        total = w * h
        lo = hi = -1
        acc = 0
        for b in range(1024):
            if lo < 0 and acc >= total // 50:      # p2
                lo = b
            acc += hist[b]
            if acc >= (total * 98) // 100:         # p98
                hi = b
                break
        _dith_lo, _dith_hi = max(0, lo), hi
    else:
        _dith_lo, _dith_hi = 0, 1023   # no stretch -> range is irrelevant
    if _dith_tab is None or _dith_lum is None:
        art_tile.hidden = False   # no tables: plain threshold, show now
        _art_shown_for = album_id
        return True
    _dith_active = True
    art_tile.hidden = True   # shown once _advance_dither() completes
    _art_shown_for = album_id
    return True


def _hide_art():
    global _art_shown_for, _dith_active
    if art_tile is not None:
        # Hide the node itself. (Filling the bitmap with 0 would instead
        # draw a solid black box on this monochrome panel.)
        art_tile.hidden = True
    _art_shown_for = ""
    _dith_active = False   # cancel any in-flight dither pass

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
    no-art fallback lines (char_w=12 at scale=2)."""
    if len(text) > max_chars:
        text = text[:max_chars - 3] + "..."
    label.text = text
    label.x = max(4, (WIDTH - len(text) * char_w) // 2)
    return label


def _wrap_words(text, width, max_lines):
    """Word-wrap `text` into at most `max_lines` lines of <= `width` chars.
    Breaks on spaces; a single word longer than the line is hard-broken so
    nothing is lost (only an over-long FINAL line gets '...'). Returns a
    list of lines."""
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], ""
    for w in words:
        piece = w
        while len(piece) > width:      # hard-break an over-long word
            take = piece[:width]
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(take)
            piece = piece[width:]
        cand = (cur + " " + piece).strip()
        if len(cand) <= width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = piece
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:         # keep the LAST (most recent) lines
        lines = lines[-max_lines:]
        if len(lines[0]) == width and not lines[0].endswith(" "):
            lines[0] = lines[0][:width - 3] + "..."   # mark the cut
    return lines


def _set_field(labels, text, max_chars, x, center=False):
    """Write a wrapped field onto its label list: line i -> labels[i], any
    surplus labels blanked. With `center` (no-art layout) each line centers
    across the full width; otherwise all lines sit at `x`."""
    lines = _wrap_words(text, max_chars, len(labels))
    for i, lab in enumerate(labels):
        if i < len(lines):
            if center:
                _center(lab, lines[i], max_chars, CHAR_W)
            else:
                lab.text = lines[i]
                lab.x = x
        else:
            lab.text = ""


def _hide_nowplaying():
    # Blank the Now-Playing screen's labels (called on every render of any
    # other view, so the screen always comes back clean).
    for field in (np_title, np_artist, np_album):
        for lab in field:
            lab.text = ""
    np_bar.text = ""
    np_t1.text = ""
    np_t2.text = ""
    _hide_art()


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
    np_view = view == "nowplaying" and extra
    # Drive the chunked art-dither pass every tick (no-op unless armed). It
    # reveals the tile only while we're still on Now Playing; backing out
    # mid-pass just lets it finish in the background.
    _advance_dither(np_view)
    if not np_view:
        _hide_nowplaying()
    # The Now-Playing screen has no header band of its own (the art fills the
    # top-left corner): hide the title/separator there. Hidden labels are also
    # skipped for their text write -- render runs every tick, so that saves a
    # label write + refresh traffic at 100 Hz while playing.
    if np_view:
        title.hidden = True
        sep.hidden = True
    else:
        title.hidden = False
        sep.hidden = False
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
        # Big album art on the left; a text column to its right -- title /
        # artist / album, then the progress bar with times at each end.
        # Without art (or no decoder) the same labels center across the
        # full width instead. Every label's x is written here each tick:
        # fit()/_center only set text, and a label keeps its last position
        # otherwise, so switching between the two layouts would leave stale
        # x values behind.
        e = extra
        has_art = _show_art(e.get("art", ""))
        dur = e["dur"]
        pos = min(e["pos"], dur)
        if has_art:
            # Word-wrapped into the text column (title 3 lines, artist and
            # album 2 each); fixed slots per field so nothing overlaps.
            _set_field(np_title, e["title"], NP_TXT_W // CHAR_W, NP_TXT_X)
            _set_field(np_artist, e["artist"], NP_TXT_W // CHAR_W, NP_TXT_X)
            _set_field(np_album, e["album"], NP_TXT_W // CHAR_W, NP_TXT_X)
            n_cells = 12   # fits the text column (12 chars at scale=2)
        else:
            # No art: each field's lines center across the full width.
            _set_field(np_title, e["title"], 32, 0, center=True)
            _set_field(np_artist, e["artist"], 32, 0, center=True)
            _set_field(np_album, e["album"], 32, 0, center=True)
            n_cells = 32   # full-width track
        filled = (n_cells * pos // dur) if dur > 0 else 0
        np_bar.text = "#" * filled + "_" * (n_cells - filled)
        np_t1.text = fmt_time(pos)
        np_t2.text = fmt_time(dur)
        if has_art:
            np_bar.x = NP_TXT_X
            np_t1.x = NP_TXT_X
        else:
            np_bar.x = 4
            np_t1.x = 4
        np_t2.x = WIDTH - len(np_t2.text) * 12 - 4
        for lab in row_labels:
            lab.text = ""
        if not e["playing"]:
            fit(banner, "PAUSED", WIDTH - 8)
        else:
            fit(banner, "", WIDTH - 8)
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
