# iPod2026 - networking: socket constants, CA bundle, streaming
# JSON, Jellyfin client, egress test.

import json
import time

import mp3

# CircuitPython's socketpool exposes AF_INET/SOCK_STREAM on newer firmware
# (as socketpool.AF_INET or pool.AF_INET) but this build has them nowhere,
# and there is NO `socket` module in CircuitPython to borrow them from.
# Define them here from the stable lwIP/POSIX values that CircuitPython
# itself uses internally (shared-bindings/socketpool/enum.h:
#   SOCKETPOOL_AF_INET = 2,  SOCKETPOOL_SOCK_STREAM = 1).
AF_INET = 2
SOCK_STREAM = 1
# Trust anchor + intermediates for Let's Encrypt
# cert. CircuitPython's bundled root list predates LE's 2025/2026 rotation,
# so a plain ssl.create_default_context() cannot verify the chain (the leaf
# is issued via the new "YR1" / "ISRG Root YR" intermediates). Loading
# ISRG Root X1 plus the two intermediates the server sends lets the
# handshake verify on ANY device: if the server omits an intermediate it
# is already in this bundle. (X1 alone verified the live chain as of
# 2026-08-29; the intermediates are belt-and-braces.)
CA_CERTS = (
'-----BEGIN CERTIFICATE-----' '\n'
'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' '\n'
'-----END CERTIFICATE-----' '\n'
'-----BEGIN CERTIFICATE-----' '\n'
'MIIE2zCCAsOgAwIBAgIRAKICU/FfJpHAXcHOE7m8yk4wDQYJKoZIhvcNAQELBQAw' '\n'
'LjELMAkGA1UEBhMCVVMxDTALBgNVBAoTBElTUkcxEDAOBgNVBAMTB1Jvb3QgWVIw' '\n'
'HhcNMjUwOTAzMDAwMDAwWhcNMjgwOTAyMjM1OTU5WjAzMQswCQYDVQQGEwJVUzEW' '\n'
'MBQGA1UEChMNTGV0J3MgRW5jcnlwdDEMMAoGA1UEAxMDWVIxMIIBIjANBgkqhkiG' '\n'
'9w0BAQEFAAOCAQ8AMIIBCgKCAQEAoVi8X2xCYgMXvJxNPKp/oF13UMgmPABB07VC' '\n'
'LNDtoXmt9luEZNJSBV10VyT1Pz6LD8Zq1d2gc43WNl1AdRrj4sEnazbOiz0nPpmG' '\n'
'Bp2hui49oZtDIY6wdKeZAi5BbNU20CH6RSBBMLSQ9cXrH8dxdv4PAJ45ssGML68U' '\n'
'SE3BsjC2a6cAN9L5CgXVIQi5tfNiTPoFZZ3S0OlXqLmmtdV95udWAb5b6e/F49Di' '\n'
'CsH0Y00Ag72BVIb1hzynmKe+X0mERBTtsb3BwmpV9ipeBjMLoR/D9cHxHQCWoi5l' '\n'
'TmXwY015J5rGelz1nZjJuxc2kioaX29XJBnhMkP531rSdG5uMwIDAQABo4HuMIHr' '\n'
'MA4GA1UdDwEB/wQEAwIBhjATBgNVHSUEDDAKBggrBgEFBQcDATASBgNVHRMBAf8E' '\n'
'CDAGAQH/AgEAMB0GA1UdDgQWBBQfLzW+RhSCzUCxrnksVXj699Ro+zAfBgNVHSME' '\n'
'GDAWgBTe51tg0CJtQCh9Pw0B/qS1UrRRlDAyBggrBgEFBQcBAQQmMCQwIgYIKwYB' '\n'
'BQUHMAKGFmh0dHA6Ly95ci5pLmxlbmNyLm9yZy8wEwYDVR0gBAwwCjAIBgZngQwB' '\n'
'AgEwJwYDVR0fBCAwHjAcoBqgGIYWaHR0cDovL3lyLmMubGVuY3Iub3JnLzANBgkq' '\n'
'hkiG9w0BAQsFAAOCAgEA0+zvMq3kHig1ddTmmm+RibTr9/RpX7k4buanMMRqbV/y' '\n'
'IvP82zAHN3mvaw+cASuVsdpd0ikjhr4hnhJQLQOzOp2ccKrsdGOAgo0vddeISFAq' '\n'
'EWEV4lmUM3vFF796up+bSgmJ1u6RupDCMxDgF8M3eLvGuj6L0lu3zkQ0KuQLnKxL' '\n'
'tB0oQqn1Idg5CuuGpMvQzk29Pa3D/qHurc0EIM9SxukQuJqq63lxsYyRQFU8yMBO' '\n'
'hq1w5LbfaWNRrz1uklOfI/pYkAb2E2MTZrAMQkBIE2S8Jt1F8gRc96o/xOsrgvSk' '\n'
'a84AisX6xq1lz1Z7jGvrnXc4TMcjxZTjiTaihcYI1JIXZiLtEMSCa5l3cu8YWd6z' '\n'
'dLRQlqRdclVjuQfNHawRJ6GWlkK0QJosivTKwdBw3KxEtzGo8yMHERbsy57gP1UX' '\n'
'HOMcmZYQC0gtyR3SxfenIM/MxC3Ia2Ypab/kQ/CTnlIn2KQ5JUC6NYrGCbhFN9bp' '\n'
'5lKJStEwCUnLpntcrXk5XVDCNv/5RyWpRThkGOV7GetKkQ0qAY8hCzWK6oqnAhDZ' '\n'
'cjlYVdWfqOw3DIOX6EDNBgAqHarRVxyF9QZdOaXSyPJ0ueD2BYJEBgaCGQ8rAaU/' '\n'
'Qc123V5LTXDZW4CcsPBDyhy4v+c8hClAyw/IkJlfBqxB9D+/wvIMHgECZ4ptP6o=' '\n'
'-----END CERTIFICATE-----' '\n'
'-----BEGIN CERTIFICATE-----' '\n'
'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' '\n'
'-----END CERTIFICATE-----' '\n'
)
# Chunked HTTP reader + streaming Items extractor.
#
#   * Locate the "Items" array SPECIFICALLY, not "first array" -- the old
#     extractor yielded the three top-level keys as strings and never
#     returned a single real item.
#   * The current element is buffered as a char list (any Unicode, incl.
#     raw multibyte), so one ~700-1000-char item is all that's ever in RAM.
#     That small span is decoded with the NATIVE json module (import json
#     at the top), so ~300KB server responses never sit whole in RAM.


def parse_item(span):
    """Decode one element span with the native json module. ValueError ->
    None keeps the lenient skip-one-item behavior: a bad element is
    dropped, the rest of the page survives."""
    span = span.strip()
    if not span:
        return None
    try:
        return json.loads(span)
    except ValueError:
        return None


# ============================================================
# Generic reader: anything exposing .read(n) -> bytes
# ============================================================

class BytesReader(object):
    """Wraps bytes (or any .read(n) source) with a read(n) interface so the
    streaming extractor has one uniform reader contract to code against."""
    def __init__(self, data=None, src=None):
        if src is not None:
            self._src = src
            self._buf = b''
            self._pos = 0
        else:
            self._src = None
            self._buf = data if data is not None else b''
            self._pos = 0

    def read(self, n):
        if self._src is not None:
            while len(self._buf) - self._pos < n:
                d = self._src.read(n)
                if not d:
                    break
                self._buf += d
            chunk = self._buf[self._pos:self._pos + n]
            self._pos += len(chunk)
            if self._pos == len(self._buf):
                self._buf = b''
                self._pos = 0
            return chunk
        chunk = self._buf[self._pos:self._pos + n]
        self._pos += len(chunk)
        if self._pos >= len(self._buf):
            self._buf = b''
            self._pos = 0
        return chunk


# ============================================================
# Chunked-transfer-encoding reader
#   Kestrel/ASP.NET answers with "Transfer-Encoding: chunked" and no
#   Content-Length. A raw socket read(n) returns the WIRE bytes:
#       <hex-size>\r\n <data> \r\n ... 0\r\n\r\n
#   This wraps a raw reader and yields only the dechunked body.
#
#   It SNIFFS the first body byte: a hex digit means the body is
#   chunked (size line); anything else (e.g. '{' from plain JSON)
#   means the body is plain and is passed straight through. The
#   caller therefore never has to know which encoding the server used.
# ============================================================

_HEX = b'0123456789abcdefABCDEF'

class ChunkedReader(object):
    def __init__(self, raw):
        self.raw = raw
        self.buf = b''
        self.state = 'sniff'
        self.remaining = 0
        self._eof = False

    def _eof_read(self, want):
        """Append raw bytes to self.buf until >= want or EOF.
        Returns True iff the buffer now holds >= want bytes."""
        while len(self.buf) < want and not self._eof:
            d = self.raw.read(512)
            if not d:
                self._eof = True
                break
            self.buf += d
        return len(self.buf) >= want

    def _raw_read(self, n):
        d = self.raw.read(n)
        if not d:
            self._eof = True
        return d

    def read(self, n):
        if self.state == 'done' or n <= 0:
            return b''
        out = bytearray()
        while len(out) < n and self.state != 'done':
            st = self.state
            if st == 'sniff':
                if not self._eof_read(1):
                    break
                b0 = self.buf[0]
                self.state = 'size' if b0 in _HEX else 'plain'
                continue
            if st == 'plain':
                # Body is NOT chunk-encoded. Drain any buffered bytes first
                # (the sniffed leading byte), then stream raw reads.
                if self.buf:
                    take = n - len(out)
                    if take > len(self.buf):
                        take = len(self.buf)
                    out += self.buf[:take]
                    self.buf = self.buf[take:]
                    continue
                if self._eof:
                    self.state = 'done'
                    break
                d = self._raw_read(n - len(out))
                if d:
                    out += d
                else:
                    self.state = 'done'
                continue
            if st == 'size':
                # grow buf until a complete "<hex>\r\n" size line or EOF
                while True:
                    idx = self.buf.find(b'\r\n')
                    if idx >= 0 or self._eof:
                        break
                    d = self.raw.read(512)
                    if not d:
                        self._eof = True
                        break
                    self.buf += d
                idx = self.buf.find(b'\r\n')
                if idx < 0:
                    break
                line = self.buf[:idx]
                self.buf = self.buf[idx + 2:]
                semi = line.find(b';')
                if semi >= 0:
                    line = line[:semi]
                if not line:
                    continue
                size = int(line, 16)
                if size == 0:
                    self.state = 'trailer'
                    continue
                self.remaining = size
                self.state = 'data'
                continue
            if st == 'trailer':
                # eat trailer header lines up to the final blank line
                while True:
                    idx = self.buf.find(b'\r\n')
                    if idx >= 0 or self._eof:
                        break
                    d = self.raw.read(512)
                    if not d:
                        self._eof = True
                        break
                    self.buf += d
                idx = self.buf.find(b'\r\n')
                if idx < 0:
                    self.state = 'done'
                    break
                if idx == 0:
                    self.buf = self.buf[2:]
                    self.state = 'done'
                    break
                self.buf = self.buf[idx + 2:]
                continue
            if st == 'data':
                if self.remaining == 0:
                    self.state = 'data_crlf'
                    continue
                take = n - len(out)
                if take > self.remaining:
                    take = self.remaining
                if len(self.buf) < take:
                    self._eof_read(take)
                    if len(self.buf) < take:
                        take = len(self.buf)   # partial chunk at EOF
                if take == 0:
                    break
                out += self.buf[:take]
                self.buf = self.buf[take:]
                self.remaining -= take
                continue
            # data_crlf: consume the \r\n after a chunk body
            if len(self.buf) < 2:
                if not self._eof_read(2):
                    break
                continue
            self.buf = self.buf[2:]
            self.state = 'size'
        return bytes(out)


# ============================================================
# Streaming "Items" array extractor
# ============================================================

def _utf8_split(data):
    """Split bytes into (complete_prefix, trailing_incomplete_bytes)."""
    for i in range(min(4, len(data)), 0, -1):
        b = data[-i]
        if (b & 0xC0) != 0x80:
            if b < 0x80:
                ln = 1
            elif (b & 0xE0) == 0xC0:
                ln = 2
            elif (b & 0xF0) == 0xE0:
                ln = 3
            else:
                ln = 4
            if i >= ln:
                return data, b''
            return data[:-i], data[-i:]
    return data, b''


def _find_items_open(text):
    """Index just past the '[' of the top-level "Items": [ , or None."""
    n = len(text)
    key = '"Items"'
    i = 0
    while True:
        i = text.find(key, i)
        if i < 0:
            return None
        j = i + len(key)
        while j < n and text[j] in ' \t\r\n':
            j += 1
        if j < n and text[j] == ':':
            j += 1
            while j < n and text[j] in ' \t\r\n':
                j += 1
            if j < n and text[j] == '[':
                return j + 1
        i += 1


def stream_items(reader, tail_holder=None):
    """reader: object with .read(n) -> bytes (dechunked body).
    Yields one dict per element of the "Items" array.

    tail_holder: optional list. When given, the body text AFTER the Items
    array's closing bracket (small: e.g. ,\"TotalRecordCount\":211,
    \"StartIndex\":0}) is appended to it, so callers can read paging
    metadata the server puts next to the array."""
    # ---- phase 1: locate the Items array open bracket ----
    carry = b''
    head_text = None
    while head_text is None:
        d = reader.read(1024)
        if not d:
            return
        carry += d
        text, tail = _utf8_split(carry)
        pos = _find_items_open(text.decode('utf-8', 'replace'))
        if pos is not None:
            head_text = text.decode('utf-8', 'replace')[pos:]
            carry = tail

    # ---- phase 2: element state machine (item = list of chars) ----
    # depth counts open { and [ brackets. The array's own '[' is the frame:
    # we start at depth=1, and an element is a complete object at depth 2..N
    # that returns to depth 1 (its closing '}'). Strings are skipped so
    # brackets/commas inside them never count.
    in_str = False
    esc = False
    depth = 1
    item = []
    started = False

    def flush():
        nonlocal in_str, esc, item, started
        s = ''.join(item).strip()
        item = []
        in_str = False
        esc = False
        started = False
        if s:
            return parse_item(s)
        return None

    def process(text2):
        nonlocal in_str, esc, depth, item, started
        results = []
        tail = []
        done = False
        for c in text2:
            if done:
                tail.append(c)
                continue
            if in_str:
                # Append the RAW char (escapes stay intact for parse_item to
                # unescape exactly once). Boolean escape tracking: a backslash
                # escapes the single next char, so an escaped quote does NOT
                # close the string, and \uXXXX's hex digits are inert.
                item.append(c)
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
                item.append(c)
                continue
            if c in '{[':
                depth += 1
                if not started:
                    started = True
                item.append(c)
                continue
            if c in '}]':
                depth -= 1
                item.append(c)
                if depth == 1 and c == '}':
                    # element object closed -> back to array level
                    r = flush()
                    if r is not None:
                        results.append(r)
                elif depth == 0:
                    # closed the array itself; flush any dangling element
                    if started:
                        r = flush()
                        if r is not None:
                            results.append(r)
                    done = True
                    tail.append(c)
                    # keep looping: the rest of this chunk (e.g.
                    # ,"TotalRecordCount":211,"StartIndex":0}) is tail
                    continue
                # CRITICAL: do not fall through to the generic append below,
                # or every nested closer (depth>=2) lands in the item span
                # TWICE, corrupting the JSON (decoder then truncates the
                # object at the first phantom closer -- dropped Album/AlbumId
                # and every field after the first nested array).
                continue
            if c == ',' and depth == 1:
                # safety: separator between elements (defensive)
                if started:
                    r = flush()
                    if r is not None:
                        results.append(r)
                continue
            # Preserve everything else (values, keys, colons, commas, and any
            # whitespace between tokens) so the element span is a faithful
            # substring the decoder can parse verbatim.
            if started or c in ' \t\r\n':
                item.append(c)
        return results, done, ''.join(tail)

    results, done, tail = process(head_text)
    for r in results:
        yield r
    if done:
        if tail_holder is not None:
            tail_holder.append(tail + carry.decode('utf-8', 'replace'))
        return

    while True:
        d = reader.read(512)
        if not d:
            break
        carry += d
        text, tail = _utf8_split(carry)
        carry = tail
        if text:
            res, done, t2 = process(text.decode('utf-8', 'replace'))
            for r in res:
                yield r
            if done:
                if tail_holder is not None:
                    tail_holder.append(t2 + carry.decode('utf-8', 'replace'))
                return
    if started:
        s = ''.join(item).strip()
        if s:
            r = parse_item(s)
            if r is not None:
                yield r
# ============================================================
# Jellyfin client (HTTPS, paging, streaming)
# ============================================================

def _find_int(key, text):
    """Find "key":<int> in a short text fragment; return the int or 0."""
    k = '"%s"' % key
    i = text.find(k)
    if i < 0:
        return 0
    j = i + len(k)
    while j < len(text) and text[j] in ' \t\r\n:':
        j += 1
    if j >= len(text) or text[j] == '-':
        return 0
    v = 0
    ok = False
    while j < len(text) and '0' <= text[j] <= '9':
        v = v * 10 + (ord(text[j]) - 48)
        j += 1
        ok = True
    return v if ok else 0


class JellyfinClient(object):

    PAGE = 1000  # items per request (~25KB raw) JOE SET THIS MANUALLY

    def __init__(self, url, api_key):
        self.url = url.rstrip('/')
        self.key = api_key

    def _get(self, path, params):
        """Open an HTTPS GET over socketpool (CircuitPython has no
        urllib.request). Returns a reader object with .read(n) -> bytes."""
        import ssl
        import socketpool
        import wifi

        url = self.url
        rest = path
        if params:
            qs = []
            for k, v in params.items():
                qs.append("%s=%s" % (k, v))
            if "?" in rest:
                rest += "&" + "&".join(qs)
            else:
                rest += "?" + "&".join(qs)

        if url.startswith("https://"):
            host = url[8:].split("/")[0]
            port = 443
        elif url.startswith("http://"):
            host = url[7:].split("/")[0]
            port = 80
        else:
            raise ValueError("bad server url: " + url)
        if ":" in host:
            host, p = host.rsplit(":", 1)
            port = int(p)

        pool = socketpool.SocketPool(wifi.radio)
        ctx = ssl.create_default_context()
        # CircuitPython's bundled roots predate LE's 2026 rotation; load the
        # trust anchor + intermediates for our server so the chain verifies.
        try:
            ctx.load_verify_locations(cadata=CA_CERTS)
        except Exception:
            pass  # fall back to bundled roots if cadata unsupported
        sock = pool.socket(AF_INET, SOCK_STREAM)
        sock.settimeout(30)
        try:
            sock.connect((host, port))
            ssock = ctx.wrap_socket(sock, server_hostname=host)
        except Exception:
            sock.close()
            raise

        req = ("GET " + rest + " HTTP/1.1\r\n"
               "Host: " + host + "\r\n"
               "X-Emby-Token: " + self.key + "\r\n"
               "Accept: application/json\r\n"
               "Connection: close\r\n"
               "\r\n")
        ssock.send(req.encode())

        # CircuitPython's ssl.SSLSocket has NO .read() method -- only
        # recv_into(buf, [bufsize]) and send(). Wrap it in a reader that
        # exposes read(n) -> bytes (and a prefill for head-overrun bytes) so
        # the rest of the HTTP code is unchanged.
        class _SSLSockReader(object):
            def __init__(self, ssock):
                self._s = ssock
                self._closed = False
                self._buf = b""

            def prefill(self, data):
                # body bytes already captured past the blank line
                if data:
                    self._buf = data + self._buf

            def read(self, n):
                if self._closed or n <= 0:
                    return b""
                if self._buf:
                    out = self._buf[:n]
                    self._buf = self._buf[n:]
                    return out
                buf = bytearray(n)
                try:
                    got = self._s.recv_into(buf)
                except Exception:
                    got = 0
                if not got:
                    return b""
                return bytes(buf[:got])

            def close(self):
                if not self._closed:
                    self._closed = True
                    self._s.close()

        reader = _SSLSockReader(ssock)

        # read HTTP status line + headers, chunked, stop at the blank line.
        # Read 256 at a time (not 1 byte) and split precisely on \r\n\r\n so
        # any body bytes already in the buffer get prefilled, not dropped.
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = reader.read(256)
            if not chunk:
                break
            head += chunk
        pos = head.rfind(b"\r\n\r\n")
        if pos >= 0:
            reader.prefill(head[pos + 4:])
        status = head.split(b"\r\n", 1)[0].decode()
        code = int(status.split(" ", 2)[1]) if " " in status else 0
        if code != 200:
            reader.close()
            raise RuntimeError("HTTP %d for %s" % (code, rest))

        return reader

    def open_audio_stream(self, track_id, bit_rate=192000, start_index_ms=0):
        """Open the HTTPS MP3 stream for a track and return
        (ssock, skipped_s): the RAW ssl.SSLSocket with the response headers
        consumed -- ready to hand straight to audiomp3.MP3Decoder (which
        requires a C stream; the Python _SSLSockReader wrapper _get returns
        is rejected) -- plus the seconds skipped client-side when
        start_index_ms is non-zero (the server ignores StartIndex, so the
        client consumes MP3 frames itself up to the offset).

        The request is HTTP/1.0 ON PURPOSE: the server then answers with
        a plain close-delimited body. HTTP/1.1 would use
        Transfer-Encoding: chunked and the decoder would see hex chunk
        size lines as garbage. (The decoder resyncs on the MP3 frame
        sync word, but there's no reason to feed it junk.)

        The socket is left NON-BLOCKING before it's returned: the
        decoder's reads then get EAGAIN when the network is briefly
        starved (no data yet -> keep playing), a hard error raises
        OSError (clean stop), and the server closing the stream gives
        read()==0 = a clean EOF at track end.
        """
        import ssl
        import socketpool
        import wifi

        url = self.url
        rest = ("/Audio/%s/stream.mp3?audioCodec=mp3&audioBitRate=%d&audioSampleRate=44100"
                % (track_id, bit_rate))
        if url.startswith("https://"):
            host = url[8:].split("/")[0]
            port = 443
        elif url.startswith("http://"):
            host = url[7:].split("/")[0]
            port = 80
        else:
            raise ValueError("bad server url: " + url)
        if ":" in host:
            host, p = host.rsplit(":", 1)
            port = int(p)

        pool = socketpool.SocketPool(wifi.radio)
        ctx = ssl.create_default_context()
        try:
            ctx.load_verify_locations(cadata=CA_CERTS)
        except Exception:
            pass  # fall back to bundled roots if cadata unsupported
        sock = pool.socket(AF_INET, SOCK_STREAM)
        sock.settimeout(30)
        try:
            sock.connect((host, port))
            ssock = ctx.wrap_socket(sock, server_hostname=host)
        except Exception:
            sock.close()
            raise
        try:
            req = ("GET " + rest + " HTTP/1.0\r\n"
                   "Host: " + host + "\r\n"
                   "X-Emby-Token: " + self.key + "\r\n"
                   "Connection: close\r\n"
                   "\r\n")
            ssock.send(req.encode())
            # Consume the response headers in small chunks: whatever slips
            # past the blank line is a few dozen bytes of MP3 at most,
            # which the decoder's frame-sync scan resyncs over.
            head = b""
            hbuf = bytearray(64)
            while b"\r\n\r\n" not in head:
                got = ssock.recv_into(hbuf)
                if not got:
                    break
                head += hbuf[:got]
            if b"\r\n\r\n" not in head:
                raise RuntimeError("audio stream: no response")
            status = head.split(b"\r\n", 1)[0].decode()
            code = int(status.split(" ", 2)[1]) if " " in status else 0
            if code != 200:
                raise RuntimeError("audio stream HTTP %d for %s" % (code, rest))
            # Client-side seek: the server ignores StartIndex, so consume
            # MP3 frames ourselves while the socket is still blocking, then
            # hand the decoder a socket that starts exactly at the frame
            # boundary for the skipped position.
            skipped = mp3._mp3_skip(ssock, start_index_ms)
            ssock.settimeout(0)  # non-blocking for the decoder
        except Exception:
            ssock.close()
            raise
        return (ssock, skipped)

    def get_items_stream(self, path, params, tail_holder=None):
        """Yield item dicts from a paged endpoint response (streamed).

        The server answers with Transfer-Encoding: chunked and no
        Content-Length, so the raw socket yields WIRE bytes (hex chunk-size
        lines + \r\n between chunks). Wrap the raw reader in a dechunker
        first; stream_items then sees only the clean JSON body.

        tail_holder: optional list that receives the body text after the
        Items array's closing bracket (e.g. ,\"TotalRecordCount\":211,
        \"StartIndex\":0}) for paging metadata.
        """
        raw = self._get(path, params)
        reader = BytesReader(src=ChunkedReader(raw))
        return stream_items(reader, tail_holder)

    def album_artists(self, progress=None):
        """Return (artists, total_count) paging ALL album artists.
        artists: list of (id, name). total_count: TotalRecordCount from
        the first page (0 if the server omitted it).

        progress: optional callback(n_artists) invoked after each page
        lands, for live load-status display."""
        out = []
        total = 0
        start = 0
        while True:
            tail = []
            page = list(self.get_items_stream('/Artists/AlbumArtists',
                          {'Recursive': 'true', 'Limit': str(self.PAGE), 'StartIndex': str(start)},
                          tail))
            if not total:
                m = _find_int('TotalRecordCount', ''.join(tail))
                if m:
                    total = m
            if not page:
                break
            out.extend((it['Id'], it['Name']) for it in page)
            start += len(page)
            if progress is not None:
                progress(len(out))
            if total and start >= total:
                break
            if start >= 20000:  # hard cap for safety
                break
        return out, total

    def artist_albums_and_tracks(self, artist_id, progress=None):
        """Return (albums, tracks) for an artist by paging all their Audio.

        albums: list of (album_id, name, year)
        tracks: list of (item_id, title, index, runtime, album_id)

        progress: optional callback(n_albums, n_tracks) invoked after each
        page lands, so callers can show live load status while the paging
        (dozens of requests) runs."""
        albums = {}
        tracks = []
        start = 0
        while True:
            page = list(self.get_items_stream('/Items', {
                'Recursive': 'true', 'IncludeItemTypes': 'Audio,Album',
                'ArtistIds': artist_id, 'Limit': str(self.PAGE), 'StartIndex': str(start)}))
            if not page:
                break
            for it in page:
                t = it.get('Type')
                if t == 'Album':
                    albums.setdefault(it['Id'], (it['Id'], it.get('Name') or it['Id'], it.get('ProductionYear')))
                elif t == 'Audio':
                    aid = it.get('AlbumId') or ''
                    if not aid:
                        continue
                    name = it.get('Album') or 'Unknown'
                    if aid not in albums:
                        albums[aid] = (aid, name, it.get('ProductionYear'))
                    ticks = it.get('RunTimeTicks') or 0
                    tracks.append((it['Id'], it['Name'], it.get('ParentIndexNumber') or 0,
                                   int(ticks // 10000000), aid))
            start += len(page)
            if progress is not None:
                progress(len(albums), len(tracks))
            if start >= 200000:  # hard cap for safety
                break
        album_list = list(albums.values())
        album_list.sort(key=lambda a: (a[2] or 0, a[1].lower()))
        tracks.sort(key=lambda t: (t[2] or 0, t[1]))
        return album_list, tracks
def net_reachable(host="8.8.8.8", port=53, timeout=5):
    """Internet egress test: TCP-connect to a well-known host and time the
    handshake. A completed handshake proves there's a route past the WiFi
    link (WiFi can be associated yet have no internet). UDP would not
    verify, so use TCP. Google DNS answers TCP/53, so this is a real
    handshake, not a drop.

    Returns a result dict:
      ok:   True if the handshake completed
      ip:   our IPv4 address ("" if wifi not connected)
      ms:   connect round-trip in ms (0 on failure)
      err:  error string on failure ("" on success)
    """
    import wifi
    ip = str(wifi.radio.ipv4_address) if wifi.radio.connected else ""
    if not ip:
        return {"ok": False, "ip": "", "ms": 0, "err": "wifi not connected"}
    import socketpool
    pool = socketpool.SocketPool(wifi.radio)
    sock = pool.socket(AF_INET, SOCK_STREAM)
    sock.settimeout(timeout)
    t0 = time.monotonic()
    try:
        sock.connect((host, port))
        ms = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "ip": ip, "ms": ms, "err": ""}
    except Exception as e:
        return {"ok": False, "ip": ip, "ms": 0, "err": str(e)}
    finally:
        sock.close()
