"""Generate a Changan-accepted signing certificate and sign APKs (v1 + v2).

Changan Feiyu/Wutong head units do not require Changan's private developer
key. PackageManager still accepts a self-signed certificate whose serial
number equals 0xddb66eefd98476f3 — the value baked into
com.vecentek.security.CertificateManager.

The on-HU dialog ``com.changanhub.quickbar is not auth,install failed!``
(and ``pm install`` ``Failure [-118: …]``) is that whitelist, not a hang.
Feiyu reads the certificate from the APK Signature Scheme v2 block (Android 9
default). A v1-only JAR/PKCS7 signature parses, then fails auth. Community
guides therefore use openssl (exact subject + serial, no extra extensions)
plus apksigner (v1+v2). This module matches that shape in pure Python and
uses apksigner when the Android SDK is already installed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from hub.apk_v2 import attach_v2, has_v2_block
from hub.paths import app_data

CHANGAN_SERIAL = 0xDDB66EEFD98476F3
# openssl -subj order from the Feiyu whitelist guides, not LDAP/C-first.
CERT_SUBJECT = (
    (NameOID.EMAIL_ADDRESS, "auto_release@auto-pai.com"),
    (NameOID.COMMON_NAME, "SCM"),
    (NameOID.ORGANIZATIONAL_UNIT_NAME, "Software"),
    (NameOID.ORGANIZATION_NAME, "WTCL"),
    (NameOID.LOCALITY_NAME, "HaiDian"),
    (NameOID.STATE_OR_PROVINCE_NAME, "Beijing"),
    (NameOID.COUNTRY_NAME, "CN"),
)
PASSWORD = "changanhub"
# Bump when an on-disk cert must be rebuilt (serial alone is not enough).
KEYSTORE_FORMAT = 3


@dataclass
class Keystore:
    directory: Path
    private_key: Path
    certificate: Path
    serial: int = CHANGAN_SERIAL

    @property
    def exists(self) -> bool:
        return self.private_key.exists() and self.certificate.exists()

    @property
    def pkcs12(self) -> Path:
        return self.directory / "changan.p12"


def keystore_dir(override: Path | None = None) -> Path:
    path = override or (app_data() / "certs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _openssl_subject() -> x509.Name:
    return x509.Name([x509.NameAttribute(oid, value) for oid, value in CERT_SUBJECT])


def cert_matches_whitelist(cert: x509.Certificate, serial: int = CHANGAN_SERIAL) -> bool:
    if cert.serial_number != serial:
        return False
    # openssl x509 -req -signkey emits no extensions; CA:TRUE certs were rejected as -118.
    if list(cert.extensions):
        return False
    if serial != CHANGAN_SERIAL:
        return True
    attrs = list(cert.subject)
    if not attrs or attrs[0].oid != NameOID.EMAIL_ADDRESS:
        return False
    if attrs[0].value != "auto_release@auto-pai.com":
        return False
    if cert.signature_hash_algorithm is None:
        return False
    return True


def ensure_keystore(directory: Path | None = None, serial: int | None = None) -> Keystore:
    wanted = serial if serial is not None else CHANGAN_SERIAL
    base = keystore_dir(directory)
    _archive_flat_keystore(base)
    folder = base / format(wanted, "x")
    folder.mkdir(parents=True, exist_ok=True)
    store = Keystore(
        directory=folder,
        private_key=folder / "changan.key",
        certificate=folder / "changan.crt",
        serial=wanted,
    )
    if store.exists:
        try:
            cert = load_certificate(store.certificate)
            if cert.serial_number == wanted and cert_matches_whitelist(cert, wanted):
                return store
        except Exception:
            pass
    # Tests and older Hub copies keep files directly in ``base``.
    flat = Keystore(
        directory=base,
        private_key=base / "changan.key",
        certificate=base / "changan.crt",
        serial=wanted,
    )
    if flat.exists:
        try:
            cert = load_certificate(flat.certificate)
            if cert.serial_number == wanted and cert_matches_whitelist(cert, wanted):
                return flat
        except Exception:
            pass
    _generate(store, serial=wanted)
    return store


def _archive_flat_keystore(base: Path) -> None:
    """Keep the previous key when Hub switches serials. Overwriting it made
    Feiyu refuse updates (UPDATE_INCOMPATIBLE) and refuse deletes (auth app)."""
    crt = base / "changan.crt"
    key = base / "changan.key"
    if not crt.exists() or not key.exists():
        return
    try:
        cert = load_certificate(crt)
    except Exception:
        return
    dest = base / format(cert.serial_number, "x")
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / "changan.crt").exists():
        shutil.copy2(key, dest / "changan.key")
        shutil.copy2(crt, dest / "changan.crt")


def load_certificate(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def load_key(path: Path):
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _generate(store: Keystore, serial: int | None = None) -> None:
    serial = serial if serial is not None else store.serial
    for leftover in (store.private_key, store.certificate, store.pkcs12):
        leftover.unlink(missing_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = _openssl_subject()
    now = dt.datetime.now(dt.timezone.utc)
    # Match `openssl x509 -req -signkey … -days 18250 -set_serial 0xddb66eefd98476f3`:
    # no BasicConstraints / KeyUsage extras — Feiyu compares the serial of this cert.
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(serial)
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=18250))
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
    (store.directory / "format").write_text(str(KEYSTORE_FORMAT), encoding="utf-8")


def sdk_root_from_adb(adb_binary: Path | str | None) -> Path | None:
    if not adb_binary:
        return None
    parent = Path(adb_binary).resolve().parent
    if parent.name.lower() == "platform-tools":
        return parent.parent
    return None


def find_java() -> Path | None:
    found: list[Path] = []
    which = shutil.which("java")
    if which:
        found.append(Path(which))
    home = os.environ.get("JAVA_HOME", "")
    if home:
        for name in ("java", "java.exe"):
            candidate = Path(home) / "bin" / name
            if candidate.exists():
                found.append(candidate)
    local = os.environ.get("LOCALAPPDATA", "")
    program = os.environ.get("ProgramFiles", "")
    program86 = os.environ.get("ProgramFiles(x86)", "")
    extra_roots = [
        Path(local) / "Programs" / "Android" / "Android Studio" / "jbr" / "bin" if local else Path(),
        Path(program) / "Android" / "Android Studio" / "jbr" / "bin" if program else Path(),
        Path(program86) / "Android" / "Android Studio" / "jbr" / "bin" if program86 else Path(),
        Path.home() / "AppData" / "Local" / "Programs" / "Android" / "Android Studio" / "jbr" / "bin",
    ]
    for folder in extra_roots:
        if not folder:
            continue
        for name in ("java.exe", "java"):
            candidate = folder / name
            if candidate.exists():
                found.append(candidate)
    java_dir = Path(program) / "Java" if program else Path()
    if java_dir.is_dir():
        for folder in sorted(java_dir.glob("jdk*"), reverse=True):
            for name in ("java.exe", "java"):
                candidate = folder / "bin" / name
                if candidate.exists():
                    found.append(candidate)
    uniq: list[Path] = []
    seen: set[str] = set()
    for item in found:
        key = str(item)
        if key not in seen:
            uniq.append(item)
            seen.add(key)
    return uniq[0] if uniq else None


def find_apksigner(adb_binary: Path | str | None = None) -> Path | None:
    found: list[Path] = []
    for name in ("apksigner", "apksigner.bat"):
        which = shutil.which(name)
        if which:
            found.append(Path(which))
    roots: list[Path] = []
    hinted = sdk_root_from_adb(adb_binary)
    if hinted:
        roots.append(hinted)
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value))
    local = os.environ.get("LOCALAPPDATA", "")
    roots += [
        Path.home() / "AppData" / "Local" / "Android" / "Sdk",
        Path(local) / "Android" / "Sdk" if local else Path(),
        Path.home() / "Android" / "Sdk",
        Path("/tmp/android-sdk"),
    ]
    adb = shutil.which("adb")
    extra = sdk_root_from_adb(adb)
    if extra:
        roots.append(extra)
    for root in roots:
        tools = root / "build-tools"
        if not tools.is_dir():
            continue
        versions = sorted(
            [p for p in tools.iterdir() if p.is_dir()],
            key=lambda p: [int(x) if x.isdigit() else x for x in p.name.split(".")],
            reverse=True,
        )
        for version in versions:
            jar = version / "lib" / "apksigner.jar"
            if jar.exists():
                found.append(jar)
            for name in ("apksigner", "apksigner.bat"):
                candidate = version / name
                if candidate.exists():
                    found.append(candidate)
    uniq: list[Path] = []
    seen: set[str] = set()
    for item in found:
        key = str(item)
        if key not in seen:
            uniq.append(item)
            seen.add(key)
    return uniq[0] if uniq else None


def sign_apk(
    src: Path,
    dst: Path | None = None,
    keystore: Keystore | None = None,
    apksigner: Path | None = None,
    adb_binary: Path | str | None = None,
) -> Path:
    path, _method = sign_apk_with_method(
        src, dst=dst, keystore=keystore, apksigner=apksigner, adb_binary=adb_binary
    )
    return path


def sign_apk_with_method(
    src: Path,
    dst: Path | None = None,
    keystore: Keystore | None = None,
    apksigner: Path | None = None,
    adb_binary: Path | str | None = None,
) -> tuple[Path, str]:
    src = Path(src)
    dst = Path(dst) if dst else src.with_name(src.stem + "-changan.apk")
    keystore = keystore or ensure_keystore()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tool = Path(apksigner) if apksigner else find_apksigner(adb_binary)
    fallback = ""
    if tool and tool.exists():
        try:
            _sign_with_apksigner(src, dst, keystore, tool)
            return dst, f"apksigner:{tool.name}"
        except (OSError, subprocess.CalledProcessError, ValueError, FileNotFoundError) as exc:
            fallback = f"apksigner {tool.name} не запустился ({exc})"
    elif tool is None:
        java = find_java()
        if java is None:
            fallback = "apksigner/java не найдены рядом с Android SDK"
        else:
            fallback = f"apksigner.jar не найден, java={java}"
    _sign_python(src, dst, keystore)
    if fallback:
        return dst, f"python-v1v2; {fallback}"
    return dst, "python-v1v2"


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


def _apksigner_cmd(apksigner: Path) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    java = find_java()
    if java:
        env["JAVA_HOME"] = str(java.resolve().parent.parent)
        env["PATH"] = str(java.resolve().parent) + os.pathsep + env.get("PATH", "")
    if apksigner.suffix.lower() == ".jar":
        if not java:
            raise FileNotFoundError("java не найден (нужен для apksigner.jar)")
        return [str(java), "-jar", str(apksigner)], env
    jar = apksigner.parent / "lib" / "apksigner.jar"
    if jar.exists() and java:
        return [str(java), "-jar", str(jar)], env
    if not java:
        raise FileNotFoundError("java не найден (apksigner.bat без Java в PATH не стартует)")
    return [str(apksigner)], env


def _sign_with_apksigner(src: Path, dst: Path, keystore: Keystore, apksigner: Path) -> Path:
    p12 = keystore.pkcs12
    if not p12.exists():
        _pkcs12(keystore, p12)
    cmd, env = _apksigner_cmd(apksigner)
    cmd += [
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
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"code {proc.returncode}"
        raise subprocess.CalledProcessError(proc.returncode, cmd, tail)
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


def _sign_python(src: Path, dst: Path, keystore: Keystore) -> None:
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
    signed = attach_v2(tmp.getvalue(), key, cert)
    if not has_v2_block(signed):
        raise RuntimeError("v2 signing block missing after Python sign")
    dst.write_bytes(signed)


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
        "format": "openssl-v2",
    }


def apk_certificate_serials(apk: Path) -> list[int]:
    """Serial numbers of v1 PKCS7 and v2 signing certificates in an APK."""
    from hub.apk_v2 import v2_certificate_ders

    serials: list[int] = []
    data = Path(apk).read_bytes()
    with zipfile.ZipFile(apk) as zf:
        for name in zf.namelist():
            upper = name.upper()
            if not (upper.startswith("META-INF/") and upper.endswith((".RSA", ".DSA", ".EC"))):
                continue
            try:
                for cert in pkcs7.load_der_pkcs7_certificates(zf.read(name)):
                    serials.append(cert.serial_number)
            except ValueError:
                continue
    for der in v2_certificate_ders(data):
        try:
            serials.append(x509.load_der_x509_certificate(der).serial_number)
        except ValueError:
            continue
    uniq: list[int] = []
    for item in serials:
        if item not in uniq:
            uniq.append(item)
    return uniq
