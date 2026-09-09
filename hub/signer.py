"""Generate a Changan-accepted signing certificate and v1-sign APKs.

Changan Feiyu/Wutong head units do not require Changan's private developer
key. PackageManager still accepts a self-signed certificate whose serial
number equals 0xddb66eefd98476f3 — the value baked into
com.vecentek.security.CertificateManager. This module creates that
certificate locally and re-signs APKs with JAR (v1) signatures so the
head unit treats them as authorised.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from hub.paths import app_data

CHANGAN_SERIAL = 0xDDB66EEFD98476F3
CERT_SUBJECT = {
    "country": "CN",
    "state": "Beijing",
    "locality": "HaiDian",
    "org": "WTCL",
    "ou": "Software",
    "cn": "SCM",
    "email": "auto_release@auto-pai.com",
}
PASSWORD = "changanhub"


@dataclass
class Keystore:
    directory: Path
    private_key: Path
    certificate: Path
    serial: int = CHANGAN_SERIAL

    @property
    def exists(self) -> bool:
        return self.private_key.exists() and self.certificate.exists()


def keystore_dir(override: Path | None = None) -> Path:
    path = override or (app_data() / "certs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_keystore(directory: Path | None = None) -> Keystore:
    folder = keystore_dir(directory)
    store = Keystore(
        directory=folder,
        private_key=folder / "changan.key",
        certificate=folder / "changan.crt",
    )
    if store.exists:
        cert = load_certificate(store.certificate)
        if cert.serial_number == CHANGAN_SERIAL:
            return store
    _generate(store)
    return store


def load_certificate(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def load_key(path: Path):
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _generate(store: Keystore) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, CERT_SUBJECT["country"]),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, CERT_SUBJECT["state"]),
            x509.NameAttribute(NameOID.LOCALITY_NAME, CERT_SUBJECT["locality"]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, CERT_SUBJECT["org"]),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, CERT_SUBJECT["ou"]),
            x509.NameAttribute(NameOID.COMMON_NAME, CERT_SUBJECT["cn"]),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, CERT_SUBJECT["email"]),
        ]
    )
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(CHANGAN_SERIAL)
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=18250))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    store.private_key.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    store.certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def sign_apk(
    src: Path,
    dst: Path | None = None,
    keystore: Keystore | None = None,
    apksigner: Path | None = None,
) -> Path:
    src = Path(src)
    dst = Path(dst) if dst else src.with_name(src.stem + "-changan.apk")
    keystore = keystore or ensure_keystore()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if apksigner and Path(apksigner).exists():
        try:
            return _sign_with_apksigner(src, dst, keystore, Path(apksigner))
        except (OSError, subprocess.CalledProcessError):
            pass
    _sign_v1(src, dst, keystore)
    return dst


def _pkcs12(keystore: Keystore, p12: Path) -> None:
    from cryptography.hazmat.primitives.serialization import pkcs12 as p12mod

    key = load_key(keystore.private_key)
    cert = load_certificate(keystore.certificate)
    data = p12mod.serialize_key_and_certificates(
        name=b"cert",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(PASSWORD.encode()),
    )
    p12.write_bytes(data)


def _sign_with_apksigner(src: Path, dst: Path, keystore: Keystore, apksigner: Path) -> Path:
    p12 = keystore.directory / "changan.p12"
    if not p12.exists():
        _pkcs12(keystore, p12)
    cmd = [
        str(apksigner),
        "sign",
        "--v1-signing-enabled",
        "true",
        "--v2-signing-enabled",
        "true",
        "--v3-signing-enabled",
        "false",
        "--min-sdk-version",
        "24",
        "--ks",
        str(p12),
        "--ks-type",
        "pkcs12",
        "--ks-pass",
        f"pass:{PASSWORD}",
        "--ks-key-alias",
        "cert",
        "--key-pass",
        f"pass:{PASSWORD}",
        "--in",
        str(src),
        "--out",
        str(dst),
    ]
    subprocess.check_call(cmd)
    return dst


def _wrap72(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        if len(raw) <= 70:
            lines.append(raw)
            continue
        lines.append(raw[:70])
        rest = raw[70:]
        while rest:
            lines.append(" " + rest[:69])
            rest = rest[69:]
    return "\n".join(lines) + "\n"


def _digest(data: bytes) -> str:
    import base64

    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _sign_v1(src: Path, dst: Path, keystore: Keystore) -> None:
    import io

    key = load_key(keystore.private_key)
    cert = load_certificate(keystore.certificate)
    entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(src, "r") as zin:
        for info in zin.infolist():
            name = info.filename
            upper = name.upper()
            if upper.startswith("META-INF/") and upper.endswith(
                (".SF", ".RSA", ".DSA", ".EC", ".MF")
            ):
                continue
            entries.append((info, zin.read(name)))

    manifest_items: list[tuple[str, str]] = []
    for info, data in entries:
        if info.is_dir():
            continue
        manifest_items.append((info.filename, _digest(data)))

    manifest = "Manifest-Version: 1.0\nCreated-By: Changan Hub\n\n"
    for name, digest in manifest_items:
        manifest += f"Name: {name}\nSHA-256-Digest: {digest}\n\n"
    manifest_bytes = _wrap72(manifest).encode("utf-8")

    sf = "Signature-Version: 1.0\nCreated-By: Changan Hub\n"
    sf += f"SHA-256-Digest-Manifest: {_digest(manifest_bytes)}\n\n"
    # Per-entry hashes of the manifest sections keep older PackageManagers happy.
    blocks = manifest.split("\n\n")
    for block in blocks:
        if not block.startswith("Name: "):
            continue
        name_line = block.splitlines()[0]
        name = name_line[6:]
        section = _wrap72(block + "\n").encode("utf-8")
        sf += f"Name: {name}\nSHA-256-Digest: {_digest(section)}\n\n"
    sf_bytes = _wrap72(sf).encode("utf-8")

    rsa_blob = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(sf_bytes)
        .add_signer(cert, key, hashes.SHA256())
        .sign(
            serialization.Encoding.DER,
            [
                pkcs7.PKCS7Options.DetachedSignature,
                pkcs7.PKCS7Options.Binary,
                pkcs7.PKCS7Options.NoCapabilities,
            ],
        )
    )

    tmp = io.BytesIO()
    with zipfile.ZipFile(tmp, "w") as zout:
        for info, data in entries:
            zout.writestr(info, data)
        for name, payload in (
            ("META-INF/MANIFEST.MF", manifest_bytes),
            ("META-INF/CERT.SF", sf_bytes),
            ("META-INF/CERT.RSA", rsa_blob),
        ):
            zi = zipfile.ZipInfo(name)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, payload)
    dst.write_bytes(tmp.getvalue())


def certificate_info(store: Keystore | None = None) -> dict[str, str]:
    store = store or ensure_keystore()
    cert = load_certificate(store.certificate)
    after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after
    after_s = after.isoformat() if hasattr(after, "isoformat") else str(after)
    return {
        "serial_hex": format(cert.serial_number, "x"),
        "subject": cert.subject.rfc4514_string(),
        "not_after": after_s,
        "path": str(store.certificate),
    }
