from pathlib import Path
from zipfile import ZipFile

from hub.signer import CHANGAN_SERIAL


def test_bundled_quickbar_apk() -> None:
    apk = Path(__file__).resolve().parents[1] / "apps" / "QuickBar.apk"
    assert apk.exists(), "QuickBar.apk must be built and committed"
    with ZipFile(apk) as zf:
        names = set(zf.namelist())
        assert "classes.dex" in names
        assert "AndroidManifest.xml" in names
        assert "META-INF/CERT.RSA" in names
        from cryptography.hazmat.primitives.serialization import pkcs7

        certs = pkcs7.load_der_pkcs7_certificates(zf.read("META-INF/CERT.RSA"))
        assert certs[0].serial_number == CHANGAN_SERIAL
