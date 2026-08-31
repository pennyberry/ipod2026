# iPod2026 - MP3 frame helpers (pure functions, no hardware).
def _mp3_frame_len(hdr):
    """Parse a 4-byte MP3 Layer III frame header. Returns
    (frame_len_bytes, samples_per_frame, sample_rate) or None if the
    header is invalid. Standard MPEG-1/2/2.5 L3 tables: 1152 samples per
    frame (MPEG-1), 576 (MPEG-2/2.5)."""
    if hdr[0] != 0xFF or (hdr[1] & 0xE0) != 0xE0:
        return None
    version = (hdr[1] >> 3) & 0x03   # 3 = MPEG-1, 1 = MPEG-2, 2 = MPEG-2.5
    layer = (hdr[1] >> 1) & 0x03     # 1 = Layer III
    if layer != 1 or version not in (1, 2, 3):
        return None
    padding = (hdr[2] >> 1) & 0x01
    br_idx = (hdr[2] >> 4) & 0x0F
    sr_idx = (hdr[2] >> 2) & 0x03
    if version == 3:
        br = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192,
              224, 256, 320, 0)[br_idx] * 1000
        sr = (44100, 48000, 32000, 0)[sr_idx]
        samples, base = 1152, 144
    else:
        br = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112,
              128, 144, 160, 0)[br_idx] * 1000
        sr = ((22050, 24000, 16000, 0) if version == 1
              else (11025, 12000, 8000, 0))[sr_idx]
        samples, base = 576, 72
    if br == 0 or sr == 0:
        return None
    return (base * br // sr + padding, samples, sr)


def _recv_n(ssock, n):
    """Read at most `n` bytes from a BLOCKING socket and return them as
    bytes; returns fewer only on EOF. Never reads past `n`, so the socket
    position advances by exactly what is returned -- the key invariant that
    lets the caller land the stream on a frame boundary."""
    out = bytearray()
    while len(out) < n:
        want = min(1024, n - len(out))
        buf = bytearray(want)
        try:
            got = ssock.recv_into(buf)
        except Exception:
            got = 0
        if not got:
            break
        out += bytes(buf[:got])
    return bytes(out)


def _find_frame(buf, pos):
    """Index of the next plausible MP3 frame header at/after `pos` in `buf`
    (a 0xFF sync byte whose next 3 bytes parse via _mp3_frame_len), else -1."""
    end = len(buf)
    while pos <= end - 4:
        if buf[pos] == 0xFF and (buf[pos + 1] & 0xE0) == 0xE0                 and _mp3_frame_len(buf[pos:pos + 4]):
            return pos
        pos += 1
    return -1


def _mp3_skip(ssock, target_ms):
    """Consume MP3 frames from a BLOCKING stream socket until at least
    `target_ms` of audio has passed; returns the ACTUAL seconds skipped
    (a sum of frame lengths, >= target). The stream is assumed to start at
    the top: anything before the first valid frame (an ID3v2 tag, header-
    overrun bytes) is skipped along the way. On EOF it stops and returns
    what it got. Every socket read is exactly sized, so on return the
    socket sits exactly on the next frame boundary -- the caller's decoder
    starts precisely at `skipped`, never mid-frame."""
    if target_ms <= 0:
        return 0.0
    target_s = target_ms / 1000.0
    buf = b""
    skipped = 0.0
    # Phase 1: find the first frame header (skip the ID3v2 tag / any
    # header-overrun bytes). Chunked reads are fine here; buf accounts for
    # every byte, so overshoot is harmless.
    while True:
        idx = _find_frame(buf, 0)
        if idx >= 0:
            buf = buf[idx:]
            break
        if len(buf) > 16384:
            return skipped  # no frame in 16 KB: not MP3, stop
        chunk = _recv_n(ssock, 1024)
        if not chunk:
            return skipped  # EOF before any frame
        buf += chunk
    # Phase 2: MP3 frames are contiguous, so consume them one at a time,
    # reading exactly the bytes each frame needs. Discarding exactly one
    # frame each step keeps the socket on a frame boundary at all times.
    while True:
        while len(buf) < 4:
            chunk = _recv_n(ssock, 4 - len(buf))
            if not chunk:
                return skipped  # EOF before a full header
            buf += chunk
        fl = _mp3_frame_len(buf[:4])
        if fl is None:
            # stray bytes (Xing gap, etc.): drop one and resync
            buf = buf[1:]
            continue
        frame_len, samples, sr = fl
        while len(buf) < frame_len:
            chunk = _recv_n(ssock, frame_len - len(buf))
            if not chunk:
                return skipped  # EOF mid-frame
            buf += chunk
        skipped += samples / sr
        buf = buf[frame_len:]
        if skipped >= target_s:
            return skipped  # buf is empty here: socket on the boundary
