#!/usr/bin/env python3
"""Compile Lamore Player APK with the Android SDK (aapt2 + javac + d8)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "android" / "player" / "src" / "main"
OUT = ROOT / "build" / "player"
APK_OUT = ROOT / "apps" / "Player.apk"


def sdk_root() -> Path:
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    for candidate in (
        Path("/tmp/android-sdk"),
        Path.home() / "Android" / "Sdk",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk",
    ):
        if candidate and (candidate / "build-tools").exists():
            return candidate
    raise SystemExit("Android SDK not found. Set ANDROID_HOME.")


def javac_bin() -> str:
    homes = [
        "/usr/lib/jvm/java-17-openjdk-amd64",
        "/usr/lib/jvm/java-17-openjdk",
        os.environ.get("JAVA_HOME"),
    ]
    for home in homes:
        if not home:
            continue
        cand = Path(home) / "bin" / "javac"
        if cand.exists():
            return str(cand)
    return "javac"


def latest(path: Path) -> Path:
    versions = sorted(
        [p for p in path.iterdir() if p.is_dir()],
        key=lambda p: [int(x) if x.isdigit() else x for x in p.name.split(".")],
        reverse=True,
    )
    if not versions:
        raise SystemExit(f"Nothing in {path}")
    return versions[0]


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, **kwargs)


def main() -> None:
    sdk = sdk_root()
    build_tools = latest(sdk / "build-tools")
    android_jar = sdk / "platforms" / "android-28" / "android.jar"
    if not android_jar.exists():
        platforms = sorted((sdk / "platforms").glob("android-*"), reverse=True)
        if not platforms:
            raise SystemExit("No android.jar")
        android_jar = platforms[0] / "android.jar"

    aapt2 = build_tools / "aapt2"
    d8 = build_tools / "d8"
    zipalign = build_tools / "zipalign"
    apksigner = build_tools / "apksigner"

    if OUT.exists():
        shutil.rmtree(OUT)
    compiled = OUT / "compiled"
    gen = OUT / "gen"
    classes = OUT / "classes"
    dex_dir = OUT / "dex"
    for folder in (compiled, gen, classes, dex_dir, APK_OUT.parent):
        folder.mkdir(parents=True, exist_ok=True)

    res_zip = OUT / "res.zip"
    run([str(aapt2), "compile", "--dir", str(SRC / "res"), "-o", str(res_zip)])

    linked = OUT / "linked.apk"
    run(
        [
            str(aapt2),
            "link",
            "-o",
            str(linked),
            "-I",
            str(android_jar),
            "--manifest",
            str(SRC / "AndroidManifest.xml"),
            "--java",
            str(gen),
            "--custom-package",
            "com.changanhub.player",
            "--version-code",
            "2",
            "--version-name",
            "1.0.1",
            "--auto-add-overlay",
            str(res_zip),
        ]
    )

    java_files = [str(p) for p in (SRC / "java").rglob("*.java")]
    java_files += [str(p) for p in gen.rglob("*.java")]
    run(
        [
            javac_bin(),
            "-g:none",
            "-source",
            "8",
            "-target",
            "8",
            "-Xlint:-options",
            "-bootclasspath",
            str(android_jar),
            "-classpath",
            str(android_jar),
            "-d",
            str(classes),
            *java_files,
        ]
    )

    class_files = [str(p) for p in classes.rglob("*.class")]
    run(
        [
            str(d8),
            "--min-api",
            "24",
            "--lib",
            str(android_jar),
            "--output",
            str(dex_dir),
            *class_files,
        ]
    )

    unsigned = OUT / "unsigned.apk"
    shutil.copy2(linked, unsigned)
    import zipfile

    dex = dex_dir / "classes.dex"
    tmp = OUT / "with-dex.apk"
    with zipfile.ZipFile(unsigned, "r") as src, zipfile.ZipFile(
        tmp, "w", compression=zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.write(dex, "classes.dex")

    aligned = OUT / "aligned.apk"
    run([str(zipalign), "-f", "4", str(tmp), str(aligned)])

    sys.path.insert(0, str(ROOT))
    from hub.signer import ensure_keystore, sign_apk

    keystore = ensure_keystore(OUT / "debug-keystore")
    signed = sign_apk(aligned, APK_OUT, keystore=keystore, apksigner=apksigner)
    print(f"Built {signed}")


if __name__ == "__main__":
    main()
