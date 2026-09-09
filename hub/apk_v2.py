"""APK Signature Scheme v2 (pure Python).

Feiyu/Wutong CertificateManager reads the signing certificate after
PackageParser. On Android 9 that prefers the v2 signing block over the
JAR (v1) PKCS7 blob. A v1-only APK parses, then fails with
``-118: … is not auth,install failed!`` because the whitelist never sees
the X.509 serial. Community guides therefore use ``apksigner`` (v1+v2).

Layout (https://source.android.com/docs/security/features/apksigning/v2):

    [ZIP entries] [APK Signing Block] [Central Directory] [EOCD]
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509 import Certificate

V2_MAGIC = b"APK Sig Block 42"
V2_BLOCK_ID = 0x7109871A
# RSASSA-PKCS1-v1_5 with SHA-256, chunked SHA-256 content digest.
RSA_PKCS1_SHA256 = 0x0103
CHUNK = 1024 * 1024
EOCD_SIG = b"PK\x05\x06"


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _u64(value: int) -> bytes:
    return struct.pack("<Q", value)


def _len_prefixed(payload: bytes) -> bytes:
    return _u32(len(payload)) + payload


def find_eocd(data: bytes) -> int:
    start = max(0, len(data) - 22 - 65535)
    pos = data.rfind(EOCD_SIG)
    while pos >= start:
        comment_len = struct.unpack_from("<H", data, pos + 20)[0]
        if pos + 22 + comment_len == len(data):
            return pos
        pos = data.rfind(EOCD_SIG, 0, pos)
    raise ValueError("ZIP End of Central Directory not found")


def _cd_offset(data: bytes, eocd: int) -> int:
    return struct.unpack_from("<I", data, eocd + 16)[0]


def _signing_block_start(data: bytes, cd_off: int) -> int | None:
    if cd_off < 32 or data[cd_off - 16 : cd_off] != V2_MAGIC:
        return None
    size = struct.unpack_from("<Q", data, cd_off - 24)[0]
    start = cd_off - size - 8
    if start < 0:
        return None
    if struct.unpack_from("<Q", data, start)[0] != size:
        return None
    return start


def has_v2_block(data: bytes) -> bool:
    try:
        eocd = find_eocd(data)
    except ValueError:
        return False
    return _signing_block_start(data, _cd_offset(data, eocd)) is not None


def _chunk_digests(blob: bytes) -> list[bytes]:
    out: list[bytes] = []
    if not blob:
        return out
    for offset in range(0, len(blob), CHUNK):
        chunk = blob[offset : offset + CHUNK]
        digest = hashlib.sha256()
        digest.update(b"\xa5")
        digest.update(_u32(len(chunk)))
        digest.update(chunk)
        out.append(digest.digest())
    return out


def chunked_sha256(*parts: bytes) -> bytes:
    chunks: list[bytes] = []
    for part in parts:
        chunks.extend(_chunk_digests(part))
    digest = hashlib.sha256()
    digest.update(b"\x5a")
    digest.update(_u32(len(chunks)))
    for item in chunks:
        digest.update(item)
    return digest.digest()


def _build_v2_value(key: RSAPrivateKey, cert: Certificate, content_digest: bytes) -> bytes:
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest_pair = _len_prefixed(_u32(RSA_PKCS1_SHA256) + _len_prefixed(content_digest))
    signed_data = (
        _len_prefixed(digest_pair)
        + _len_prefixed(_len_prefixed(cert_der))
        + _len_prefixed(b"")
    )
    signature = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
    sig_pair = _len_prefixed(_u32(RSA_PKCS1_SHA256) + _len_prefixed(signature))
    signer = _len_prefixed(signed_data) + _len_prefixed(sig_pair) + _len_prefixed(public_key)
    return _len_prefixed(_len_prefixed(signer))


def _apk_signing_block(v2_value: bytes) -> bytes:
    pair = _u32(V2_BLOCK_ID) + v2_value
    pairs = _u64(len(pair)) + pair
    # size field counts everything after the first uint64: pairs + trailing size + magic.
    size = len(pairs) + 8 + 16
    return _u64(size) + pairs + _u64(size) + V2_MAGIC


def attach_v2(data: bytes, key: RSAPrivateKey, cert: Certificate) -> bytes:
    eocd = find_eocd(data)
    cd_off = _cd_offset(data, eocd)
    block_at = _signing_block_start(data, cd_off)
    contents_end = block_at if block_at is not None else cd_off
    contents = data[:contents_end]
    central = data[cd_off:eocd]
    eocd_bytes = bytearray(data[eocd:])
    # Integrity-protected EOCD pretends the Central Directory starts at the signing block.
    struct.pack_into("<I", eocd_bytes, 16, contents_end)
    digest = chunked_sha256(contents, central, bytes(eocd_bytes))
    block = _apk_signing_block(_build_v2_value(key, cert, digest))
    real_eocd = bytearray(data[eocd:])
    struct.pack_into("<I", real_eocd, 16, contents_end + len(block))
    return contents + block + central + bytes(real_eocd)


def sign_file(path: Path, key: RSAPrivateKey, cert: Certificate) -> None:
    path.write_bytes(attach_v2(path.read_bytes(), key, cert))
