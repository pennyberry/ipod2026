# iPod2026 - hardware + playback + boot.
#   i2c, battery (MAX17048), DAC (TLV320DAC3100), MP3 streaming,
#   seesaw knobs/buttons, PlayerState instance, WiFi/client boot,
#   host() intent dispatcher. Imported by code.py, which then runs
#   the main loop after this module finishes its boot sequence.

import time
import os
import board
import digitalio

import adafruit_seesaw.seesaw
import adafruit_seesaw.rotaryio
import adafruit_seesaw.digitalio
import adafruit_seesaw.neopixel

from net import (JellyfinClient, _find_int, net_reachable)
import settings as sd
from settings import (load_settings, wifi_connect,
                      sd_store_catalog, sd_store_artists,
                      sd_load_artists, sd_clear_catalogs,
                      sd_store_art, sd_clear_art,
                      ARTISTS_CACHE)
import controls
import player
from player import PlayerState
import ui
from ui import render, batt

# ============================================================
# Inputs: quad encoder breakout
# ============================================================
# If you ever see I2C errors/timeout, swap in a slower manual bus:
#   import busio
#   i2c = busio.I2C(board.D15, board.D4, frequency=50000)
i2c = board.STEMMA_I2C()

# ============================================================
# Battery: MAX17048 fuel gauge (3.7V LiPo, 1S)
#   cell_percent is the chip's own 0.0-100.0 estimate (voltage with
#   load compensation), so no divider or chemistry table here.
#   Probe the Stemma QT bus first (with the rotary breakouts), then
#   the SCL/SDA connector; if neither answers, the meter stays blank
#   and playback is unaffected.
# ============================================================
import adafruit_max1704x

# Optional: wire the MAX17048 CHG pin (Low while a charger is active)
# to a GPIO to show "USB" instead of a percentage when plugged in.
CHARGE_PIN = None  # e.g. board.D5
charge_pin = None
if CHARGE_PIN is not None:
    charge_pin = digitalio.DigitalInOut(CHARGE_PIN)
    charge_pin.direction = digitalio.Direction.INPUT
    charge_pin.pull_up = True

max17 = None
for _bus in (i2c, None):
    try:
        _cand = adafruit_max1704x.MAX17048(_bus if _bus is not None else board.I2C())
        _ = _cand.cell_voltage  # force a live read to confirm a device
        max17 = _cand
        break
    except Exception:
        max17 = None

# ============================================================
# Audio out: TLV320DAC3100 I2S DAC (headphones only)
#   A0/BCK=GPIO14  A1/WSEL=GPIO15  A2/DIN=GPIO16  RST=D12
#   MCK=D4 fed a 15 MHz PWM clock (mclk_freq) for low-noise PLL lock;
#   without it the DAC PLL runs from BCLK (higher noise floor, distortion)
#   VIN -> 3V3 (speaker amp disabled), short GND wire required
#   Reset toggle (low->high) MUST happen before any I2S use.
# ============================================================
import adafruit_tlv320
import audiobusio
import pwmio

rst = digitalio.DigitalInOut(board.D12)
rst.direction = digitalio.Direction.OUTPUT
rst.value = False
time.sleep(0.1)
rst.value = True

dac = adafruit_tlv320.TLV320DAC3100(i2c)   # existing i2c object
# MCLK: feed the DAC a clean 15 MHz reference on MCK (D4) instead of letting
# its PLL derive from BCLK -- per the library, BCLK mode has a higher noise
# floor and lots of harmonic distortion (sounds "lower quality").
mclk_pwm = None
MCLK_HZ = 15000000
try:
    mclk_pwm = pwmio.PWMOut(board.D4, frequency=MCLK_HZ, duty_cycle=2 ** 15)
except Exception:
    mclk_pwm = None  # fall back to BCLK mode; audio still works, noisier
dac.configure_clocks(sample_rate=48000, bit_depth=16,
                     mclk_freq=MCLK_HZ if mclk_pwm else None)
try:
    print("MCLK:", "15 MHz PWM (low-noise PLL)" if mclk_pwm
          else "BCLK fallback (NOISIER -- check MCK wiring to D4)")
except Exception:
    pass
dac.headphone_output = True                 # disables the speaker amp, per the guide
try:
    # headphone_output=True leaves the headphone mixer pad at its -30.1 dB
    # default -- far too low. The signal ends up tiny and the DAC's own noise
    # floor rides on top of it (hiss). Set a healthy fixed trim (the library's
    # own "good balance for headphones" value) and use dac_volume as the fader.
    dac.headphone_volume = -15.5
except Exception:
    pass
dac.dac_volume = -10                        # dB

audio = audiobusio.I2SOut(board.A0, board.A1, board.A2)
# audio.play(sample, sample_rate=44100, bits=16)

# ============================================================
# Real audio: MP3 streaming over HTTPS -> audiomp3 -> I2S DAC
#   Every track is fetched server-transcoded to MP3 (the library is
#   ~94% FLAC and the ESP32 can only decode MP3, so the "Audio format"
#   setting is accepted but all formats go through this one path):
#       GET /Audio/{id}/stream.mp3?audioCodec=mp3&audioBitRate=192000
#   over HTTP/1.0 (close-delimited body, no chunked framing).
#   The decoder reads the RAW ssl.SSLSocket (headers consumed first);
#   it runs on a non-blocking socket, so EAGAIN keeps playback going,
#   a hard error stops cleanly, and the server closing the stream is a
#   clean EOF -> the queue auto-advances.
#   Seek re-opens the stream and skips MP3 frames client-side to the
#   offset (the server ignores StartIndex); seek_offset_s feeds the true
#   skipped position into audio_tick's wall-clock pos math. Pause still
#   stops (no in-place pause); resume / "seek:0" restart the track from
#   the top.
# ============================================================
import audiomp3

# 32 KiB decode buffer (~2s of 128kbps audio): more underrun headroom so a
# brief stall (catalog-fetch handshake, display refresh) can't starve the
# MP3 decoder. Costs ~12 KiB of RAM over the 20480 default -- worth it.
AUDIO_BUF_SIZE = 32768
audio_buf = bytearray(AUDIO_BUF_SIZE)
audio_decoder = None     # current audiomp3.MP3Decoder (None = idle)
audio_sock = None        # raw ssl.SSLSocket the decoder reads from
TEST_FILE = "/sd/test.mp3"   # Sound test file on the SD card
test_file = None         # open file object for the sound test (closed on EOF)
_last_volume = None      # last applied DAC volume (skip redundant I2C writes)
play_start_t = 0.0       # monotonic() when the current track started (pos)
seek_offset_s = 0.0      # seconds into the track the current stream started at


def _apply_volume(vol):
    """state.volume 0-100 -> TLV320DAC3100 dac_volume (dB). 0 maps to
    -70 dB (inaudible), 100 to -3 dB (kept below 0 so the DAC's internal
    DSP filter never clips, per the driver docs). No-op while unchanged."""
    global _last_volume
    if vol == _last_volume:
        return
    _last_volume = vol
    try:
        dac.dac_volume = -70 + vol * 67 // 100
    except Exception:
        pass
def audio_stop():
    """Stop playback and release the decoder + stream socket (idempotent)."""
    global audio_decoder, audio_sock, test_file, seek_offset_s
    seek_offset_s = 0.0
    try:
        if audio.playing:
            audio.stop()
    except Exception:
        pass
    if audio_decoder is not None:
        try:
            audio_decoder.deinit()
        except Exception:
            pass
        audio_decoder = None
    if audio_sock is not None:
        try:
            audio_sock.close()
        except Exception:
            pass
        audio_sock = None
    if test_file is not None:
        try:
            test_file.close()
        except Exception:
            pass
        test_file = None


def audio_play(track_id, start_index_ms=0):
    """Stream `track_id` from the server into the DAC. Blocks while the
    TLS handshake + the first MP3 frame arrive (Jellyfin starts the
    transcode, typically ~1-3 s). Returns True if playback started; on
    failure the banner carries the error."""
    global audio_decoder, audio_sock, play_start_t, seek_offset_s
    audio_stop()
    if not client:
        state.banner = "play failed: no server"
        return False
    try:
        audio_sock, _skipped_s = client.open_audio_stream(
            track_id, start_index_ms=start_index_ms)
    except Exception as e:
        try:
            print("AUDIO OPEN ERROR:", repr(e))
        except Exception:
            pass
        audio_sock = None
        state.banner = "play failed: %s" % str(e)
        return False
    try:
        # The constructor BLOCKS until the first MP3 frame is found
        # (skips the ID3v2 tag and learns the sample rate from the
        # frame header); audio.play() itself is non-blocking.
        audio_decoder = audiomp3.MP3Decoder(audio_sock, audio_buf)
        # Re-tune the DAC PLL to THIS track's real sample rate before the
        # first samples hit the bus. The server transcodes most sources to
        # 48k, but a few MP3s arrive natively at 44.1k (it won't resample
        # them). A mismatched frame rate plays the track off-pitch (flat at
        # 48k-on-44.1k, or sped-up/chipmunk at 44.1k-on-48k). configure_clocks
        # is cheap (a few I2C writes + a 10 ms PLL-lock sleep) and runs once
        # per track, so per-track re-tuning is negligible.
        try:
            _sr = audio_decoder.sample_rate
            if _sr not in (48000, 44100):
                _sr = 48000
            dac.configure_clocks(sample_rate=_sr, bit_depth=16,
                                 mclk_freq=MCLK_HZ if mclk_pwm else None)
        except Exception:
            # If sample_rate isn't readable on this firmware, keep the default
            # (48000) that was set at startup; 48k tracks stay correct.
            pass
        audio.play(audio_decoder)
    except Exception as e:
        try:
            print("AUDIO START ERROR:", repr(e))
        except Exception:
            pass
        audio_stop()
        state.banner = "play failed: %s" % str(e)
        return False
    seek_offset_s = _skipped_s  # the true position the stream started at
    play_start_t = time.monotonic()
    _apply_volume(state.volume)
    state.banner = ""
    try:
        print("PLAYING", track_id)
    except Exception:
        pass
    return True


def _restart_current():
    """Restart the current queue track from the top (the only 'seek' a
    live stream can do without re-fetching). Used for "resume"/"seek:0"."""
    if not (0 <= state.queue_pos < len(state.queue)):
        return
    t = state.queue[state.queue_pos]
    state.pos = 0
    if not audio_play(t[0]):
        state.playing = False


def _seek_current(target_s):
    """Restart the current queue track from `target_s` seconds in by
    re-opening the stream and skipping MP3 frames client-side to the
    offset (the server ignores StartIndex). audio_play resets play_start_t
    and sets seek_offset_s to the true skipped position, so audio_tick's
    wall-clock math (pos = now - play_start_t + seek_offset_s) tracks from
    the offset."""
    if not (0 <= state.queue_pos < len(state.queue)):
        return
    t = state.queue[state.queue_pos]
    state.pos = target_s
    if not audio_play(t[0], start_index_ms=int(target_s * 1000)):
        state.playing = False


def _advance_queue():
    """Move to the next queue track and start it (EOF auto-advance)."""
    if not state.queue:
        state.playing = False
        return
    state.queue_pos = (state.queue_pos + 1) % len(state.queue)
    t = state.queue[state.queue_pos]
    state.dur = t[3]
    state.pos = 0
    if not audio_play(t[0]):
        state.playing = False


def audio_tick(now):
    """Drive playback from the main loop: keep state.pos in lockstep with
    the decoder (wall-clock; the audio is real-time) and auto-advance
    the queue when the current track's stream hits EOF. When the sound
    test file has hit EOF instead, just stop (no queue advance)."""
    global test_file
    if not state.playing or audio_decoder is None:
        return
    if audio.playing:
        if play_start_t:
            state.pos = min(state.dur, int(now - play_start_t + seek_offset_s))
        return
    # audio.playing went False: the stream hit EOF (server closed) or the
    # decoder failed. Grace period so a slow transcode start isn't read
    # as an instant "end of track".
    if play_start_t and now - play_start_t > 2.0:
        if test_file is not None:
            # Sound test finished (or failed): stop and report.
            state.playing = False
            state.pos = 0
            audio_stop()
            state.banner = "test done"
            return
        _advance_queue()


def play_test_file(path=TEST_FILE):
    """Play an MP3 from the SD card (TEST_FILE) using the SAME non-blocking
    mechanism as normal playback: open the file, hand it to the MP3Decoder,
    start it, and return at once -- the main loop's audio_tick() then drives
    it to EOF (closing the file and stopping when it finishes). This way the
    test exercises exactly the code path the music uses.
    Returns (ok: bool, msg: str) for the banner."""
    global audio_decoder, test_file, play_start_t
    if not sd.sd_present:
        return (False, "no SD card")
    audio_stop()
    try:
        test_file = open(path, "rb")
    except OSError as e:
        test_file = None
        return (False, "open %s failed: %s" % (path, str(e)))
    try:
        # The constructor BLOCKS until the first MP3 frame is found
        # (skips the ID3v2 tag and learns the sample rate from the
        # frame header); audio.play() itself is non-blocking.
        audio_decoder = audiomp3.MP3Decoder(test_file, audio_buf)
        # Same per-track re-tune as the stream path: local files may be 44.1k
        # or 48k, and a DAC/decoder frame-rate mismatch plays off-pitch.
        try:
            _sr = audio_decoder.sample_rate
            if _sr not in (48000, 44100):
                _sr = 48000
            dac.configure_clocks(sample_rate=_sr, bit_depth=16,
                                 mclk_freq=MCLK_HZ if mclk_pwm else None)
        except Exception:
            pass
        audio.play(audio_decoder)
    except Exception as e:
        try:
            print("SOUND TEST ERROR:", repr(e))
        except Exception:
            pass
        audio_stop()
        return (False, "test failed: %s" % str(e))
    play_start_t = time.monotonic()
    state.playing = True
    state.pos = 0
    _apply_volume(state.volume)
    return (True, "playing %s" % path)
seesaw = adafruit_seesaw.seesaw.Seesaw(i2c, 0x49)

# Encoder channels are fixed by the hardware (channel == physical position);
# button pins come from controls.py so a rewire is a one-file change.
encoders = [
    adafruit_seesaw.rotaryio.IncrementalEncoder(seesaw, n)
    for n in range(controls.N_CONTROLS)
]
switches = [
    adafruit_seesaw.digitalio.DigitalIO(seesaw, pin)
    for pin in controls.SWITCH_PINS
]
for switch in switches:
    switch.switch_to_input(digitalio.Pull.UP)
pixels = adafruit_seesaw.neopixel.NeoPixel(seesaw, 18, 4)
pixels.brightness = 0.5
# ============================================================
# Boot: settings -> WiFi -> client -> load artists
# ============================================================
state = PlayerState()
state.settings = load_settings()
ui.state = state  # render() in ui.py reads state at runtime
sd.mount_sd()          # Mount the SD card (no-op if absent) before the UI.

client = None
_fetch_fail_t = 0  # monotonic time of last failed artist fetch (backoff)
# Bring the UI up immediately so the home screen shows regardless of
# whether wifi / the Jellyfin server are reachable.
state.banner = "connecting wifi..."
render(state.snapshot())


def do_connect():
    global client
    state.banner = "connecting wifi..."
    ip = wifi_connect(state.settings.get("WiFi SSID", ""),
                      state.settings.get("WiFi password", ""))
    if not ip:
        state.net = "WiFi down"
        state.net_ok = False
        state.banner = "WiFi down - set SSID in Settings"
        return None
    # link is up; now confirm there's a route past it before we
    # touch the server (a 30s socket timeout is the other way this fails)
    state.banner = "testing network..."
    r = net_reachable()
    if r["ok"]:
        state.net = "wifi " + ip
        state.net_ok = True
    else:
        state.net = "wifi %s (no internet)" % ip
        state.net_ok = False
        state.banner = "no internet - check WiFi/router"
        return None
    client = JellyfinClient(state.settings.get("Server URL", ""),
                            state.settings.get("API key", ""))
    state.banner = "wifi %s - loading artists..." % ip
    return ip


def load_artists_page():
    """Fetch the next page of artists so we buffer past the selection."""
    global _fetch_fail_t
    if not client:
        return
    if state.artists_done:
        return
    if state.artists_total and state.artists_loaded >= state.artists_total:
        state.artists_done = True
        return
    # back off after a failed fetch so a dead server doesn't block the
    # main loop (each attempt can hang up to the 30s socket timeout)
    if _fetch_fail_t and time.monotonic() - _fetch_fail_t < 30:
        return
    start = state.artists_loaded
    state.banner = "loading artists (%d)..." % start
    render(state.snapshot())
    tail = []
    try:
        page = list(client.get_items_stream('/Artists/AlbumArtists',
                      {'Recursive': 'true', 'Limit': str(JellyfinClient.PAGE),
                       'StartIndex': str(start)}, tail))
    except Exception as e:
        _fetch_fail_t = time.monotonic()
        state.net = "artist fetch error"
        try:
            print("ARTIST FETCH ERROR:", repr(e))
        except Exception:
            pass
        state.banner = "artist fetch error: %s" % str(e)
        return
    for it in page:
        state.artists.append((it['Id'], it['Name']))
    state.artists_loaded = len(state.artists)
    # The server reports the true count next to the Items array
    # ("TotalRecordCount":211). The first page sets it; later pages
    # keep it (it only changes if the library changes).
    m = _find_int('TotalRecordCount', ''.join(tail))
    if m:
        state.artists_total = m
    else:
        state.artists_total = max(state.artists_total, state.artists_loaded)
    if not page:
        state.artists_done = True
    elif state.artists_total and state.artists_loaded >= state.artists_total:
        state.artists_done = True
    _fetch_fail_t = 0
    state.banner = ""


def load_artist_catalog():
    """Fetch all albums+tracks for the currently selected artist (on a
    cache miss) and persist them to the SD card so the next open is instant.

    Paging an artist's whole catalog takes dozens of requests, so show the
    bottom status line BEFORE the fetch and update it live (with running
    album/track counts) as each page lands. render() is called here
    directly: the main loop's render step never runs until the fetch
    returns, so without it the banner would sit undrawn the whole time."""
    if not client:
        return
    state.banner = "loading catalog... 0 albums, 0 tracks"
    render(state.snapshot())

    def progress(n_albums, n_tracks):
        state.banner = "loading catalog... %d albums, %d tracks" % (n_albums, n_tracks)
        render(state.snapshot())

    try:
        albums, tracks = client.artist_albums_and_tracks(state.artist_id, progress)
    except Exception as e:
        try:
            print("CATALOG FETCH ERROR:", repr(e))
        except Exception:
            pass
        state.banner = "catalog fetch error: %s" % str(e)
        return
    state.albums = albums
    state.track_cache = tracks
    state.albums_loaded = True
    state._cat_store(state.artist_id, albums, tracks)
    # Persist to the SD cache (best-effort; the RAM cache is already set).
    sd_store_catalog(state.artist_id, albums, tracks)
    fetch_album_art(albums)
    state.banner = ""


def fetch_album_art(albums):
    """Fetch each album's artwork from the server and store it on the SD
    card (/sd/cache/art/<album_id>.jpg). Runs right after a catalog load:
    the art is then available offline for the Now-Playing screen.

    Best-effort throughout -- one failed image (or a dead network) must
    never break playback, so errors stop the loop quietly and whatever
    already landed stays cached. Albums whose art file already exists on
    the card are skipped (a re-open of a known artist costs zero requests)."""
    if not client or not sd.sd_present:
        return   # nowhere to cache it -> don't spend the bandwidth
    n = len(albums)
    for i, a in enumerate(albums):
        aid = a[0]
        # Skip albums whose art is already on the card (a partial fill from
        # an earlier interrupted run heals itself; deleting only the
        # catalog file never re-fetches art that exists).
        try:
            os.stat(sd._art_path(aid))
            continue
        except OSError:
            pass
        try:
            data = client.fetch_image(
                "/Items/%s/Images/Primary" % aid,
                {"maxWidth": "230", "maxHeight": "230", "quality": "80"})
        except Exception as e:
            # Network/HTTP failure (not a 404): stop fetching the rest;
            # the ones already stored are still good.
            try:
                print("ART FETCH ERROR:", repr(e))
            except Exception:
                pass
            break
        if data is None or not sd_store_art(aid, data):
            continue   # no art for this album / card write failed
        state.banner = "loading artwork... %d/%d" % (i + 1, n)
        render(state.snapshot())


def topup_album_art():
    """Fetch artwork only for the CURRENT artist's albums that are missing
    from the SD cache. Called from the main loop when _art_pending is set:
    a catalog loaded from the RAM/SD cache never ran fetch_album_art (that
    runs on network loads only), so artists cached before the art feature --
    or whose first art run was interrupted -- would otherwise play with no
    tile. Albums already on the card are skipped via a cheap stat, so an
    artist whose art is complete costs zero requests and returns instantly."""
    if not client or not sd.sd_present:
        return   # nowhere to cache it -> don't spend the bandwidth
    albums = state.albums
    n = len(albums)
    for i, a in enumerate(albums):
        aid = a[0]
        try:
            os.stat(sd._art_path(aid))
            continue   # already cached
        except OSError:
            pass
        try:
            data = client.fetch_image(
                "/Items/%s/Images/Primary" % aid,
                {"maxWidth": "230", "maxHeight": "230", "quality": "80"})
        except Exception as e:
            # Network/HTTP failure (not a 404): stop; the rest stays for a
            # later top-up (the flag is re-set on every artist select).
            try:
                print("ART FETCH ERROR:", repr(e))
            except Exception:
                pass
            break
        if data is None or not sd_store_art(aid, data):
            continue   # no art for this album / card write failed
        state.banner = "loading artwork... %d/%d" % (i + 1, n)
        render(state.snapshot())
    state.banner = ""


def boot_load_library():
    """Boot-time library load.
      1. If the SD already has a full artists cache -> load it from the card
         (instant, and works with no network at all). Done.
      2. Otherwise, if we have a server client -> gather the ENTIRE artist
         list, store it to the SD cache, and load it into RAM. This one-time
         cost is what makes every future boot instant.
    Per-artist catalogs are cached lazily (as you open them) so boot stays
    fast no matter how big the library is."""
    # 1) SD cache hit: instant, offline.
    if sd.sd_present:
        cached_artists, total = sd_load_artists()
        if cached_artists:
            state.artists = cached_artists
            state.artists_total = total or len(cached_artists)
            state.artists_loaded = len(cached_artists)
            state.artists_done = True
            state._artists_rows_n = -1
            state.banner = ""
            return
    # 2) SD cache miss: gather the full list once and store it to the card.
    if not client:
        return
    state.banner = "building library cache... 0 artists"
    render(state.snapshot())

    def progress(n_artists):
        state.banner = "building library cache... %d artists" % n_artists
        render(state.snapshot())

    try:
        artists, total = client.album_artists(progress)
    except Exception as e:
        try:
            print("LIBRARY FETCH ERROR:", repr(e))
        except Exception:
            pass
        state.banner = "library fetch error: %s" % str(e)
        return
    state.artists = artists
    state.artists_total = total or len(artists)
    state.artists_loaded = len(artists)
    state.artists_done = True
    state._artists_rows_n = -1
    # Store to SD so the next boot reads the card instead of the server.
    sd_store_artists(artists, state.artists_total)
    state.banner = ""


do_connect()
# Boot library load: prefer the SD cache (instant, offline); on a miss,
# gather the full artist list once and store it so future boots are instant.
boot_load_library()

render(state.snapshot())
_batt_txt = ""    # current meter text ("" = no gauge / no read yet)
_batt_t = -1.0    # monotonic() of the last gauge read (throttled to 1/s)


def battery_tick(now):
    """Refresh the top-right SoC meter at most once per second.
    Returns True when the visible text changed."""
    global _batt_txt, _batt_t
    if max17 is None or now - _batt_t < 1.0:
        return False
    _batt_t = now
    try:
        if charge_pin is not None and charge_pin.value == 0:
            txt = "USB"  # charger active (CHG Low)
        else:
            pct = max(0, min(100, int(round(max17.cell_percent))))
            txt = "%d%%" % pct
    except Exception:
        return False
    if txt != _batt_txt:
        _batt_txt = txt
        batt.text = txt
        return True
    return False


battery_tick(time.monotonic())


def host(ev):
    i = state.on_event(ev)
    if isinstance(i, str) and i.startswith("seek:"):
        _seek_current(int(i[5:]))
    elif isinstance(i, str) and i.startswith("play:"):
        # SELECT on a track / NEXT / PREV: start streaming that track
        if not audio_play(i[5:]):
            state.playing = False
    elif i == "pause":
        # the MP3 stream can't pause in place: stop for now
        audio_stop()
    elif i == "resume":
        # no real resume yet: restart the current track from the top
        _restart_current()
    elif i == "stop":
        audio_stop()
    elif i == "nettest":
        # Manual egress test from Settings: run it right here. It blocks up
        # to the 5s socket timeout while the banner says so.
        state.banner = "testing 8.8.8.8..."
        render(state.snapshot())
        r = net_reachable()
        if r["ok"]:
            state.net_ok = True
            state.net = "wifi %s" % r["ip"] if not state.net.startswith("wifi") \
                else state.net
            state.net_test_msg = "OK 8.8.8.8:%d %dms (ip %s)" % (53, r["ms"], r["ip"])
        else:
            state.net_ok = False
            state.net_test_msg = ("FAIL " + (r["err"] or "no route") +
                                  ("  (ip %s)" % r["ip"] if r["ip"] else ""))
        state.banner = ""
    elif i == "soundtest":
        # Manual sound test from Settings: play /sd/test.mp3 through the
        # normal (non-blocking) playback path; audio_tick drives it to EOF
        # and reports "test done" in the banner.
        state.banner = play_test_file()[1]
    elif i == "rebuild":
        # Rebuild cache from Settings: wipe the SD library cache (catalogs
        # AND artwork), reconnect, and re-gather the artist list (stored
        # back to SD). Per-artist catalogs + art are re-cached lazily as you
        # browse. Blocks while it runs; the banner shows progress.
        if not client and not do_connect():
            state.banner = "rebuild failed: no network"
            return
        if not sd.sd_present:
            state.banner = "rebuild failed: no SD card"
            return
        state.banner = "wiping cache..."
        render(state.snapshot())
        sd_clear_catalogs()
        sd_clear_art()
        try:
            os.remove(ARTISTS_CACHE)
        except OSError:
            pass
        state.banner = "refetching artists..."
        render(state.snapshot())
        state.artists = []
        state.artists_loaded = 0
        state.artists_total = 0
        state.artists_done = False
        state._artists_rows_n = -1
        state._catalog_pending = False
        state._art_pending = False
        state._cat_clear()
        boot_load_library()
        state.banner = "cache rebuilt"
