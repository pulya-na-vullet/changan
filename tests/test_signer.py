from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
from cryptography.x509.oid import NameOID

from hub.apk_v2 import V2_MAGIC, has_v2_block
from hub.signer import (
    CHANGAN_SERIAL,
    cert_matches_whitelist,
    certificate_info,
    ensure_keystore,
    sign_apk,
)


def test_keystore_serial(tmp_path: Path) -> None:
    store = ensure_keystore(tmp_path)
    info = certificate_info(store)
    assert info["serial_hex"] == format(CHANGAN_SERIAL, "x")
    assert "SCM" in info["subject"]
    cert = x509.load_pem_x509_certificate(store.certificate.read_bytes())
    assert cert_matches_whitelist(cert)
    assert list(cert.extensions) == []
    assert list(cert.subject)[0].oid == NameOID.EMAIL_ADDRESS


def test_old_ca_cert_is_regenerated(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime as dt

    folder = tmp_path / "certs"
    folder.mkdir()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
            x509.NameAttribute(NameOID.COMMON_NAME, "SCM"),
        ]
    )
    now = dt.datetime.now(dt.timezone.utc)
    stale = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(CHANGAN_SERIAL)
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=10))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    (folder / "changan.key").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    (folder / "changan.crt").write_bytes(stale.public_bytes(serialization.Encoding.PEM))
    store = ensure_keystore(folder)
    fresh = x509.load_pem_x509_certificate(store.certificate.read_bytes())
    assert cert_matches_whitelist(fresh)
    assert list(fresh.extensions) == []


def test_sign_minimal_apk(tmp_path: Path) -> None:
    import zipfile
    from unittest.mock import patch

    apk = tmp_path / "tiny.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"not-a-real-manifest")
        zf.writestr("classes.dex", b"dex\n")
    store = ensure_keystore(tmp_path / "certs")
    with patch("hub.signer.find_apksigner", return_value=None):
        signed = sign_apk(apk, tmp_path / "tiny-signed.apk", keystore=store)
    data = signed.read_bytes()
    assert V2_MAGIC in data
    assert has_v2_block(data)
    cert = x509.load_pem_x509_certificate(store.certificate.read_bytes())
    assert cert.public_bytes(Encoding.DER) in data
    with zipfile.ZipFile(signed) as zf:
        names = set(zf.namelist())
        assert "META-INF/CERT.RSA" in names
        assert "META-INF/CERT.SF" in names
        assert "META-INF/MANIFEST.MF" in names
        rsa = zf.read("META-INF/CERT.RSA")
        assert len(rsa) > 64
        smime_oid = bytes.fromhex("060b2a864886f70d01090f")
        assert smime_oid not in rsa
        certs = pkcs7.load_der_pkcs7_certificates(rsa)
        assert certs[0].serial_number == CHANGAN_SERIAL
    from hub.signer import apk_certificate_serials
    from hub.apk_v2 import v2_certificate_ders

    assert CHANGAN_SERIAL in apk_certificate_serials(signed)
    assert v2_certificate_ders(data)


def test_switching_serial_keeps_previous_key(tmp_path: Path) -> None:
    first = ensure_keystore(tmp_path, serial=CHANGAN_SERIAL)
    pem = first.certificate.read_bytes()
    other = 0xD42599C0446BDAFC
    second = ensure_keystore(tmp_path, serial=other)
    assert first.certificate.exists()
    assert first.certificate.read_bytes() == pem
    assert second.serial == other
    assert second.certificate.resolve() != first.certificate.resolve()
    assert cert_matches_whitelist(x509.load_pem_x509_certificate(second.certificate.read_bytes()), other)
