"""Open APKs that Android accepts but Python zipfile rejects.

HUD.apk and some HU-community packages have junk between the central
directory and EOCD, a false EOCD in a comment, or a truncated catalog.
Android PackageManager still installs them. Hub must re-sign, so we rebuild
a clean ZIP from local file headers when zipfile raises BadZipFile.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

LOCAL_SIG = b"PK\x03\x04"
CD_SIG = b"PK\x01\x02"
EOCD_SIG = b"PK\x05\x06"
DATA_DESC_SIG = b"PK\x07\x08"


def open_apk_zip(path: Path | str) -> zipfile.ZipFile:
    """Return a readable ZipFile, repairing a broken catalog if needed."""
    src = Path(path)
    try:
        return zipfile.ZipFile(src, "r")
    except zipfile.BadZipFile:
        repaired = repair_apk_bytes(src.read_bytes())
        return zipfile.ZipFile(io.BytesIO(repaired), "r")


def repair_apk_bytes(data: bytes) -> bytes:
    if not data:
        raise zipfile.BadZipFile("empty APK")
    trimmed = _trim_zip_view(data)
    try:
        with zipfile.ZipFile(io.BytesIO(trimmed), "r") as zin:
            return _rewrite_from_zip(zin)
    except zipfile.BadZipFile:
        pass
    entries = _parse_local_entries(trimmed)
    if not entries:
        entries = _parse_local_entries(data)
    if not entries:
        raise zipfile.BadZipFile("Bad magic number for central directory")
    return _rewrite_entries(entries)


def _trim_zip_view(data: bytes) -> bytes:
    first = data.find(LOCAL_SIG)
    if first < 0:
        return data
    body = data[first:]
    eocd = _find_eocd(body)
    if eocd is None:
        return body
    comment_len = int.from_bytes(body[eocd + 20 : eocd + 22], "little")
    end = min(len(body), eocd + 22 + comment_len)
    return body[:end]


def _find_eocd(data: bytes) -> int | None:
    start = max(0, len(data) - 65557)
    pos = data.rfind(EOCD_SIG, start)
    while pos >= start:
        if pos + 22 <= len(data):
            comment_len = int.from_bytes(data[pos + 20 : pos + 22], "little")
            if pos + 22 + comment_len <= len(data):
                cd_off = int.from_bytes(data[pos + 16 : pos + 20], "little")
                cd_size = int.from_bytes(data[pos + 12 : pos + 16], "little")
                if cd_off + cd_size <= pos and data[cd_off : cd_off + 4] == CD_SIG:
                    return pos
        nxt = data.rfind(EOCD_SIG, start, pos)
        if nxt == pos:
            break
        pos = nxt
    pos = data.rfind(EOCD_SIG)
    return pos if pos >= 0 else None


def _rewrite_from_zip(zin: zipfile.ZipFile) -> bytes:
    entries: list[tuple[str, bytes]] = []
    for info in zin.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir():
            continue
        entries.append((name, zin.read(info.filename)))
    return _rewrite_entries(entries)


def _rewrite_entries(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for name, payload in entries:
            zi = zipfile.ZipInfo(filename=name)
            if name.replace("\\", "/").startswith("lib/") and name.endswith(".so"):
                zi.compress_type = zipfile.ZIP_STORED
            else:
                zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, payload)
    return buf.getvalue()


def _parse_local_entries(data: bytes) -> list[tuple[str, bytes]]:
    pos = data.find(LOCAL_SIG)
    if pos < 0:
        return []
    entries: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    while pos + 30 <= len(data) and data[pos : pos + 4] == LOCAL_SIG:
        flags, _method = struct.unpack_from("<HH", data, pos + 6)
        _crc, csize, usize = struct.unpack_from("<III", data, pos + 14)
        name_len, extra_len = struct.unpack_from("<HH", data, pos + 26)
        name_start = pos + 30
        extra_start = name_start + name_len
        data_start = extra_start + extra_len
        if extra_start > len(data) or data_start > len(data):
            break
        try:
            name = data[name_start:extra_start].decode("utf-8")
        except UnicodeDecodeError:
            name = data[name_start:extra_start].decode("cp437", errors="replace")
        extra = data[extra_start:data_start]
        csize, usize = _zip64_sizes(extra, csize, usize)
        payload, next_pos = _read_payload(data, data_start, flags, csize)
        if payload is None:
            break
        if name and not name.endswith("/") and name not in seen:
            seen.add(name)
            entries.append((name.replace("\\", "/"), payload))
        pos = next_pos
        nxt = _next_sig(data, pos)
        if nxt is None:
            break
        pos = nxt
        if data[pos : pos + 4] != LOCAL_SIG:
            break
    return entries


def _zip64_sizes(extra: bytes, csize: int, usize: int) -> tuple[int, int]:
    off = 0
    while off + 4 <= len(extra):
        header, size = struct.unpack_from("<HH", extra, off)
        off += 4
        if off + size > len(extra):
            break
        blob = extra[off : off + size]
        off += size
        if header != 0x0001:
            continue
        cur = 0
        if usize == 0xFFFFFFFF and cur + 8 <= len(blob):
            usize = struct.unpack_from("<Q", blob, cur)[0]
            cur += 8
        if csize == 0xFFFFFFFF and cur + 8 <= len(blob):
            csize = struct.unpack_from("<Q", blob, cur)[0]
    return csize, usize


def _read_payload(data: bytes, start: int, flags: int, csize: int) -> tuple[bytes | None, int]:
    if flags & 0x01:
        return None, start
    if flags & 0x08 and csize == 0:
        desc = data.find(DATA_DESC_SIG, start)
        local = data.find(LOCAL_SIG, start + 4)
        cd = data.find(CD_SIG, start + 4)
        candidates = [n for n in (desc, local, cd) if n >= start]
        if not candidates:
            return None, start
        end = min(candidates)
        if data[end : end + 4] == DATA_DESC_SIG:
            return data[start:end], end + 16
        return data[start:end], end
    end = start + csize
    if end > len(data):
        return None, start
    nxt = end
    if flags & 0x08:
        if data[end : end + 4] == DATA_DESC_SIG:
            nxt = end + 16
        else:
            nxt = end + 12
    return data[start:end], nxt


def _next_sig(data: bytes, pos: int) -> int | None:
    while pos + 4 <= len(data):
        sig = data[pos : pos + 4]
        if sig in (LOCAL_SIG, CD_SIG, EOCD_SIG):
            return pos
        pos += 1
    return None
