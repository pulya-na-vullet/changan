from pathlib import Path
from zipfile import ZipFile

from cryptography.hazmat.primitives.serialization import pkcs7

from hub.apk_v2 import V2_MAGIC, has_v2_block
from hub.signer import CHANGAN_SERIAL


def test_bundled_quickbar_apk() -> None:
    apk = Path(__file__).resolve().parents[1] / "apps" / "QuickBar.apk"
    assert apk.exists(), "QuickBar.apk must be built and committed"
    data = apk.read_bytes()
    assert V2_MAGIC in data
    assert has_v2_block(data)
    with ZipFile(apk) as zf:
        names = set(zf.namelist())
        assert "classes.dex" in names
        assert "AndroidManifest.xml" in names
        assert "META-INF/CERT.RSA" in names
        mf = zf.read("AndroidManifest.xml")
        assert "com.changanhub.qb1_3_15".encode("utf-16-le") in mf
        assert "1.3.15".encode("utf-16-le") in mf
        assert "res/drawable/ic_sign.xml" in names
        dex = zf.read("classes.dex")
        assert b"HuSigner" in dex
        assert b"FeiyuSigner" in dex
        assert b"signFromUsb" in dex
        assert b"ddb66eefd98476f3" in dex
        assert b"memoryRoots" in dex
        assert b"sourcePicker" in dex
        assert b"apk_source" in dex
        certs = pkcs7.load_der_pkcs7_certificates(zf.read("META-INF/CERT.RSA"))
        assert certs[0].serial_number == CHANGAN_SERIAL
