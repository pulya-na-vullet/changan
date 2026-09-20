import io
import zipfile
from pathlib import Path
from unittest.mock import patch

from hub.apk_zip import open_apk_zip, repair_apk_bytes
from hub.signer import ensure_keystore, sign_apk


def _tiny_apk_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"hud-manifest")
        zf.writestr("classes.dex", b"dex\n")
    return buf.getvalue()


def _break_central_directory(data: bytes) -> bytes:
    """Insert junk between the CD and EOCD — Python 3 zipfile then raises BadZipFile."""
    eocd = data.rfind(b"PK\x05\x06")
    assert eocd > 0
    return data[:eocd] + b"JUNK" + data[eocd:]


def test_open_apk_zip_repairs_bad_central_directory(tmp_path: Path) -> None:
    broken = tmp_path / "HUD.apk"
    broken.write_bytes(_break_central_directory(_tiny_apk_bytes()))
    try:
        zipfile.ZipFile(broken, "r").close()
        raise AssertionError("fixture must be rejected by zipfile")
    except zipfile.BadZipFile:
        pass
    with open_apk_zip(broken) as zf:
        assert zf.read("AndroidManifest.xml") == b"hud-manifest"
        assert "classes.dex" in zf.namelist()


def test_repair_apk_bytes_roundtrip() -> None:
    repaired = repair_apk_bytes(_break_central_directory(_tiny_apk_bytes()))
    with zipfile.ZipFile(io.BytesIO(repaired)) as zf:
        assert zf.read("classes.dex") == b"dex\n"


def test_sign_apk_with_bad_central_directory(tmp_path: Path) -> None:
    apk = tmp_path / "HUD.apk"
    apk.write_bytes(_break_central_directory(_tiny_apk_bytes()))
    store = ensure_keystore(tmp_path / "certs")
    with patch("hub.signer.find_apksigner", return_value=None):
        signed = sign_apk(apk, tmp_path / "HUD-changan.apk", keystore=store)
    with zipfile.ZipFile(signed) as zf:
        assert zf.read("AndroidManifest.xml") == b"hud-manifest"
        assert "META-INF/CERT.RSA" in zf.namelist()
