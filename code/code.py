# Audio is server-transcoded to MP3
# (/Audio/{id}/stream.mp3?audioCodec=mp3) and streamed over HTTPS into
# the audiomp3 decoder -> I2S DAC (see the audio section below).
# Seek is real: it re-opens the stream and skips MP3 frames client-side
# to the offset (10 s steps on the TRANSPORT knob). Pause still stops (no
# in-place pause); resume restarts the track from the top. Browse is LIVE
# against the real server.
#
# Knob map (left -> right):
#   1  NAV       turn: scroll list / next-prev track   press: SELECT
#   2  TRANSPORT turn: fast seek                       press: PLAY_PAUSE / SAVE
#   3  VOLUME    turn: volume up/down                  press: BACK (MENU)
#   4  AUX       turn: (reserved)                      press: STOP / DEL char
#
# LED: white while its button is held; colorwheel flash when it is turned.
#
# Server notes (verified against this build, 10.11.11):
#   * Fields= and AlbumId= query params are SILENTLY IGNORED -> must page with
#     Limit/StartIndex and filter client-side.
#   * /Items ignores AlbumArtists= ; use ArtistIds=.
#   * Responses are large (~300KB/artist) -> stream + parse, never buffer whole.
#   * CircuitPython has NO `socket` module (that is MicroPython) and this
#     firmware's socketpool does not export AF_INET/SOCK_STREAM, so the
#     constants are defined at the top of this file (stable lwIP/POSIX
#     values: AF_INET=2, SOCK_STREAM=1) and sockets open via
#     socketpool.SocketPool(wifi.radio).socket(...).
#   * `urllib.request` is also not bundled, so HTTP goes through socketpool
#     + ssl directly.

import time
from rainbowio import colorwheel

import audio as A
from audio import (state, encoders, switches, pixels,
                   host, audio_tick, battery_tick, _apply_volume,
                   load_artists_page, load_artist_catalog,
                   do_connect, boot_load_library)
from settings import save_settings
import ui as U
from ui import (render, display, WIDTH, _advance_banner,
                _advance_selrow)

# ============================================================
# Main loop
# ============================================================
last_pos = [-1, -1, -1, -1]
was_pressed = [False, False, False, False]
press_t = [0.0, 0.0, 0.0, 0.0]
led_flash = [0.0, 0.0, 0.0, 0.0]
last_t = time.monotonic()
last_input_t = time.monotonic()   # last knob/button input (auto-return timer)
_last_snap = None
while True:
    now = time.monotonic()
    dt = now - last_t
    last_t = now

    # --- knob deltas -> context events ---
    for n in range(4):
        pos = encoders[n].position
        if pos != last_pos[n]:
            d = pos - last_pos[n]
            last_pos[n] = pos
            last_input_t = now
            led_flash[n] = now
            fast = "FAST" if abs(d) >= 3 else ""
            if n == 0:
                ev = ("KNOB_CW" if d > 0 else "KNOB_CCW") + fast
            elif n == 1:
                ev = "KNOB_CW_FAST" if d > 0 else "KNOB_CCW_FAST"
            elif n == 2:
                ev = "VOL_UP" if d > 0 else "VOL_DOWN"
                if state.view() == "nowplaying":
                    # arm the Now-Playing volume pop-out (and re-arm on
                    # every further turn while it is up)
                    U._vol_pop = True
                    U._vol_pop_t = now
                    U._vol_dirty = True
            else:
                continue
            host(ev)
    if U._vol_pop and now - U._vol_pop_t >= 3.0:
        U._vol_pop = False
        U._vol_dirty = True  # force the render that drops back to the status line

    # --- button edges (debounced) -> events ---
    for n in range(4):
        pressed = switches[n].value == 0
        if pressed and not was_pressed[n]:
            press_t[n] = now
            last_input_t = now
        if was_pressed[n] and not pressed:
            if now - press_t[n] >= 0.05:
                if state.view() == "settings" and state.set_editing and n == 3:
                    host("DEL:1")
                elif n == 0:
                    host("SELECT")
                elif n == 1:
                    if state.view() == "settings":
                        save_settings(state.settings)
                        state.banner = "saved - press k2 to reconnect"
                        host("PLAY_PAUSE")
                    else:
                        host("PLAY_PAUSE")
                elif n == 2:
                    host("BACK")
                elif n == 3:
                    if state.view() == "settings" and state.set_saved:
                        # reconnect with (possibly new) settings
                        A._fetch_fail_t = 0
                        state.artists = []
                        state.artists_loaded = 0
                        state.artists_total = 0
                        state.artists_done = False
                        state._artists_rows_n = -1
                        state._catalog_pending = False
                        state._cat_clear()
                        do_connect()
                        boot_load_library()
                    else:
                        host("STOP")
        was_pressed[n] = pressed

    # --- auto-return to Now Playing ---
    # While music is playing and the user is off the Now Playing screen, an
    # 8s stretch with no knob/button input brings them back to it.
    if state.playing and state.view() != "nowplaying" and now - last_input_t >= 8.0:
        state._view_set("nowplaying")

    # --- lazy loads triggered by selection (only when egress was OK) ---
    # The artists list is fully loaded at boot (SD cache or one-time gather),
    # so this only covers the no-network-and-no-cache edge (list came up empty).
    if state.view() == "artists" and not state.artists and A.client and state.net_ok:
        load_artists_page()
    # Catalog: one-shot flag set on artist SELECT when both the RAM and SD
    # caches missed. Cleared here so it fetches exactly once.
    if state._catalog_pending:
        if A.client and state.net_ok:
            state._catalog_pending = False
            load_artist_catalog()
        else:
            state._catalog_pending = False
            state.banner = "no network to load catalog"

    # --- playback: real MP3 stream (audio section above) ---
    # audio_tick keeps state.pos in lockstep with the decoder and
    # auto-advances the queue when a track hits EOF. The volume knob is
    # mapped to the DAC here (no-op while unchanged).
    audio_tick(now)
    _apply_volume(state.volume)
    # battery meter updates outside render(): auto_refresh is off, so a
    # changed meter needs its own one-off refresh to become visible.
    if battery_tick(now):
        display.refresh()

    # --- LEDs ---
    for n in range(4):
        if was_pressed[n]:
            pixels[n] = (255, 255, 255)
        elif now - led_flash[n] < 1.0:
            pixels[n] = colorwheel((abs(last_pos[n]) * 32) % 256)
        else:
            pixels[n] = (0, 0, 0)

    # --- render only when something visible changed ---
    snap = state.snapshot()
    key = (snap[0], snap[1], tuple(snap[2]), snap[3], state.banner,
           snap[4].get("pos") if snap[4] and "pos" in snap[4] else None,
           snap[4].get("playing") if snap[4] else None,
           snap[4].get("volume") if snap[4] else None,
           snap[4].get("editing") if snap[4] else None,
           snap[4].get("saved") if snap[4] else None,
           snap[4].get("nettest") if snap[4] else None,
           U._vol_pop if snap[0] == "nowplaying" else None, A._batt_txt)
    if key != _last_snap:
        render(snap)
        _last_snap = key
        U._vol_dirty = False
    if snap[0] != "nowplaying" and U._vol_pop:
        # left the screen: drop the pop-out (and render the status line back)
        U._vol_pop = False
        U._vol_dirty = True
    # Marquee: scroll an over-long banner one char per tick so the whole
    # message (e.g. a full fetch error) is readable. Only the list views use
    # a marqueeable banner (settings/nowplaying draw fixed banners).
    if snap[0] in ("home", "artists", "albums", "tracks", "settings", "sdview"):
        if U._banner_dirty:
            # banner text changed this tick (e.g. a live load-progress
            # update): the first frame was just drawn; advancing now would
            # skip it and make the text jump a char every update
            U._banner_dirty = False
            _adv = False
        else:
            _adv = _advance_banner(WIDTH - 8)
        if U._selrow_dirty:
            # highlighted row just (re)started scrolling: its first frame
            # was just drawn; don't advance on this same tick
            U._selrow_dirty = False
        else:
            _adv = _advance_selrow(WIDTH - 8) or _adv
        # auto_refresh is off: an advance writes a label that nothing else
        # repaints, so refresh once per tick when anything actually moved.
        if _adv:
            display.refresh()

    time.sleep(0.01)
