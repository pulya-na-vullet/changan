from pathlib import Path

from hub.signer import CHANGAN_SERIAL, certificate_info, ensure_keystore, sign_apk


def test_keystore_serial(tmp_path: Path) -> None:
    store = ensure_keystore(tmp_path)
    info = certificate_info(store)
    assert info["serial_hex"] == format(CHANGAN_SERIAL, "x")
    assert "SCM" in info["subject"]


def test_sign_minimal_apk(tmp_path: Path) -> None:
    import zipfile

    apk = tmp_path / "tiny.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"not-a-real-manifest")
        zf.writestr("classes.dex", b"dex\n")
    store = ensure_keystore(tmp_path / "certs")
    signed = sign_apk(apk, tmp_path / "tiny-signed.apk", keystore=store)
    with zipfile.ZipFile(signed) as zf:
        names = set(zf.namelist())
        assert "META-INF/CERT.RSA" in names
        assert "META-INF/CERT.SF" in names
        assert "META-INF/MANIFEST.MF" in names
        rsa = zf.read("META-INF/CERT.RSA")
        assert len(rsa) > 64
