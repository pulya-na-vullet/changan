#!/usr/bin/env python3
"""Fetch RHVoice arm64 JNI + Elena Russian voice into the AI Chat tree."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "android" / "aichat" / "src" / "main"
JNI = SRC / "jniLibs" / "arm64-v8a"
DATA = SRC / "assets" / "rhvoice"
APK_URL = "https://f-droid.org/repo/com.github.olga_yakovleva.rhvoice.android_118040.apk"
ELENA_URL = (
    "https://github.com/RHVoice/elena-rus/releases/download/v4.3/"
    "RHVoice-voice-Russian-Elena-4.3.2011.10.nvda-addon"
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        apk = tmp_path / "rhvoice.apk"
        addon = tmp_path / "elena.nvda-addon"
        subprocess.check_call(["curl", "-fsSL", "-o", str(apk), APK_URL])
        subprocess.check_call(["curl", "-fsSL", "-o", str(addon), ELENA_URL])
        if JNI.exists():
            shutil.rmtree(JNI.parent)
        JNI.mkdir(parents=True)
        with zipfile.ZipFile(apk) as zf:
            JNI.joinpath("libRHVoice_jni.so").write_bytes(zf.read("lib/arm64-v8a/libRHVoice_jni.so"))
        unpacked = tmp_path / "elena"
        unpacked.mkdir()
        with zipfile.ZipFile(addon) as zf:
            zf.extractall(unpacked)
        if DATA.exists():
            shutil.rmtree(DATA)
        lang = DATA / "languages" / "Russian"
        voice = DATA / "voices" / "elena"
        lang.mkdir(parents=True)
        voice.mkdir(parents=True)
        shutil.copytree(unpacked / "langdata", lang, dirs_exist_ok=True)
        shutil.copytree(unpacked / "data", voice, dirs_exist_ok=True)
        readme = voice / "README.md"
        if readme.exists():
            readme.unlink()
        hi = voice / "24000"
        if hi.exists():
            shutil.rmtree(hi)
    print(f"JNI {JNI / 'libRHVoice_jni.so'}")
    print(f"data {DATA}")


if __name__ == "__main__":
    main()
