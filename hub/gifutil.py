"""Decode PNG screenshots and pack them into a GIF (stdlib only)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(rgb[y * stride : (y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def decode_png(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    pos = 8
    width = height = 0
    color_type = 2
    idat = bytearray()
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        name = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if name == b"IHDR":
            width, height, depth, color_type = struct.unpack(">IIBB", chunk[:10])
            if depth != 8 or color_type not in (2, 6):
                raise ValueError(f"unsupported PNG {depth}/{color_type}")
        elif name == b"IDAT":
            idat.extend(chunk)
        elif name == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    bpp = 3 if color_type == 2 else 4
    stride = width * bpp
    rows: list[bytes] = []
    offset = 0
    prev = bytearray(stride)
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        if filter_type == 1:
            for i in range(stride):
                line[i] = (line[i] + (line[i - bpp] if i >= bpp else 0)) & 255
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) // 2)) & 255
        elif filter_type == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        elif filter_type != 0:
            raise ValueError(f"PNG filter {filter_type}")
        prev = line
        if bpp == 4:
            rgb_line = bytearray()
            for i in range(0, stride, 4):
                rgb_line.extend(line[i : i + 3])
            rows.append(bytes(rgb_line))
        else:
            rows.append(bytes(line))
    rgb = b"".join(rows)
    return width, height, rgb


def _scale(width: int, height: int, rgb: bytes, max_side: int = 480) -> tuple[int, int, bytes]:
    side = max(width, height)
    if side <= max_side:
        return width, height, rgb
    step = max(1, round(side / max_side))
    nw, nh = width // step, height // step
    out = bytearray(nw * nh * 3)
    i = 0
    for y in range(nh):
        src_y = y * step
        for x in range(nw):
            src = (src_y * width + x * step) * 3
            out[i : i + 3] = rgb[src : src + 3]
            i += 3
    return nw, nh, bytes(out)


def _palette_index(r: int, g: int, b: int) -> int:
    return ((r >> 5) << 5) | ((g >> 5) << 2) | (b >> 6)


def _palette_bytes() -> bytes:
    raw = bytearray(256 * 3)
    for i in range(256):
        r = ((i >> 5) & 7) * 36
        g = ((i >> 2) & 7) * 36
        b = (i & 3) * 85
        raw[i * 3 : i * 3 + 3] = bytes((min(r, 255), min(g, 255), min(b, 255)))
    return bytes(raw)


def _lzw(indexes: bytes) -> bytes:
    min_code = 8
    clear, end = 256, 257
    next_code = 258
    code_size = 9
    table: dict[bytes, int] = {bytes([i]): i for i in range(256)}
    buf = 0
    bits = 0
    out = bytearray()

    def emit(code: int, size: int) -> None:
        nonlocal buf, bits
        buf |= code << bits
        bits += size
        while bits >= 8:
            out.append(buf & 255)
            buf >>= 8
            bits -= 8

    emit(clear, code_size)
    w = bytes([indexes[0]])
    for byte in indexes[1:]:
        wk = w + bytes([byte])
        if wk in table:
            w = wk
            continue
        emit(table[w], code_size)
        if next_code < 4095:
            table[wk] = next_code
            next_code += 1
            if next_code == (1 << code_size) and code_size < 12:
                code_size += 1
        else:
            emit(clear, code_size)
            table = {bytes([i]): i for i in range(256)}
            next_code = 258
            code_size = 9
        w = bytes([byte])
    emit(table[w], code_size)
    emit(end, code_size)
    if bits:
        out.append(buf & 255)
    packed = bytearray([min_code])
    for i in range(0, len(out), 255):
        chunk = out[i : i + 255]
        packed.append(len(chunk))
        packed.extend(chunk)
    packed.append(0)
    return bytes(packed)


def write_gif(frames: list[Path], dest: Path, delay_cs: int = 40) -> Path:
    if not frames:
        raise ValueError("no frames")
    decoded = []
    width = height = 0
    for path in frames:
        w, h, rgb = decode_png(path)
        w, h, rgb = _scale(w, h, rgb)
        decoded.append((w, h, rgb))
        width, height = w, h
    dest.parent.mkdir(parents=True, exist_ok=True)
    pal = _palette_bytes()
    with dest.open("wb") as handle:
        handle.write(b"GIF89a")
        handle.write(struct.pack("<HH", width, height))
        handle.write(bytes((0xF7, 0, 0)))
        handle.write(pal)
        handle.write(b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")
        for w, h, rgb in decoded:
            indexes = bytes(_palette_index(rgb[i], rgb[i + 1], rgb[i + 2]) for i in range(0, len(rgb), 3))
            handle.write(b"\x21\xf9\x04\x00")
            handle.write(struct.pack("<H", max(2, delay_cs)))
            handle.write(b"\x00\x00")
            handle.write(b",")
            handle.write(struct.pack("<HHHH", 0, 0, w, h))
            handle.write(b"\x00")
            handle.write(_lzw(indexes))
        handle.write(b";")
    return dest
