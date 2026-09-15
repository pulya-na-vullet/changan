"""On-HU Feiyu signer used by QuickBar USB install."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs7

from hub.apk_v2 import V2_MAGIC, has_v2_block, v2_certificate_ders
from hub.signer import CHANGAN_SERIAL, apk_certificate_serials, cert_matches_whitelist

ROOT = Path(__file__).resolve().parents[1]
SIGNER_JAVA = (
    ROOT
    / "android"
    / "quickbar"
    / "src"
    / "main"
    / "java"
    / "com"
    / "changanhub"
    / "quickbar"
    / "sign"
    / "FeiyuSigner.java"
)
SMIME_OID = bytes.fromhex("060b2a864886f70d01090f")


def _compile(tmp_path: Path) -> Path:
    classes = tmp_path / "classes"
    classes.mkdir()
    subprocess.check_call(
        [
            "javac",
            "-g:none",
            "-source",
            "8",
            "-target",
            "8",
            "-Xlint:-options",
            "-d",
            str(classes),
            str(SIGNER_JAVA),
        ]
    )
    return classes


def _run(classes: Path, *args: str) -> None:
    subprocess.check_call(
        ["java", "-cp", str(classes), "com.changanhub.quickbar.sign.FeiyuSigner", *args]
    )


def _tiny_apk(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"not-a-real-manifest")
        zf.writestr("classes.dex", b"dex\n")
        zf.writestr("res/layout/main.xml", b"<xml/>")


def test_feiyu_signer_matches_hub_whitelist(tmp_path: Path) -> None:
    classes = _compile(tmp_path)
    certs = tmp_path / "certs"
    apk = tmp_path / "tiny.apk"
    signed = tmp_path / "tiny-changan.apk"
    _tiny_apk(apk)
    _run(classes, "gen", str(certs))
    _run(classes, "sign", str(certs), str(apk), str(signed))

    der = (certs / "changan.der").read_bytes()
    cert = x509.load_der_x509_certificate(der)
    assert cert.serial_number == CHANGAN_SERIAL
    assert cert_matches_whitelist(cert)
    assert list(cert.extensions) == []

    data = signed.read_bytes()
    assert V2_MAGIC in data
    assert has_v2_block(data)
    assert CHANGAN_SERIAL in apk_certificate_serials(signed)
    assert v2_certificate_ders(data)
    v2_cert = x509.load_der_x509_certificate(v2_certificate_ders(data)[0])
    assert v2_cert.serial_number == CHANGAN_SERIAL
    assert cert_matches_whitelist(v2_cert)

    with zipfile.ZipFile(signed) as zf:
        names = zf.namelist()
        assert names[0] == "META-INF/MANIFEST.MF"
        assert "META-INF/CERT.SF" in names
        assert "META-INF/CERT.RSA" in names
        rsa = zf.read("META-INF/CERT.RSA")
        assert SMIME_OID not in rsa
        pkcs = pkcs7.load_der_pkcs7_certificates(rsa)
        assert pkcs[0].serial_number == CHANGAN_SERIAL
        manifest = zf.read("META-INF/MANIFEST.MF").decode("ascii")
        assert "Created-By: Changan Hub" in manifest


def test_feiyu_signer_custom_serial(tmp_path: Path) -> None:
    classes = _compile(tmp_path)
    certs = tmp_path / "certs"
    other = "d42599c0446bdafc"
    _run(classes, "gen", str(certs), other)
    cert = x509.load_der_x509_certificate((certs / "changan.der").read_bytes())
    assert format(cert.serial_number, "x") == other
    assert cert_matches_whitelist(cert, int(other, 16))
