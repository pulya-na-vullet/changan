"""XAPK / APKM / APKS containers: zip of split APKs, not a single pm-install APK."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

BUNDLE_SUFFIXES = {".xapk", ".apkm", ".apks"}
PACKAGE_SUFFIXES = (".apk", ".xapk", ".apkm", ".apks")
# Windows filedialog wants semicolons; Hub on-site is Windows.
PACKAGE_FILE_TYPES = [
    ("APK / XAPK", "*.apk;*.xapk;*.apkm;*.apks"),
    ("APK", "*.apk"),
    ("XAPK", "*.xapk"),
    ("APKM / APKS", "*.apkm;*.apks"),
    ("Все файлы", "*.*"),
]
_SESSION_ID = re.compile(r"\[(\d+)\]")
_SESSION_WORD = re.compile(r"session\s+(\d+)", re.I)
_PKG_STEM = re.compile(r"[A-Za-z][\w]*(?:\.[A-Za-z][\w]*){2,}")


@dataclass
class BundleSplit:
    path: Path
    name: str
    size: int = 0


@dataclass
class ExtractedBundle:
    package: str | None
    splits: list[BundleSplit]
    obb: list[Path] = field(default_factory=list)
    work_dir: Path | None = None


def is_apk_bundle(path: Path) -> bool:
    """True when pm install cannot parse this zip as one APK (XAPK/APKM/APKS)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 32:
        return False
    suffix = path.suffix.lower()
    if suffix in BUNDLE_SUFFIXES:
        return True
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            names = [_norm_zip_name(item) for item in zf.namelist()]
    except zipfile.BadZipFile:
        return False
    nested = [name for name in names if name.lower().endswith(".apk") and not name.endswith("/")]
    if not nested:
        return False
    if "AndroidManifest.xml" in names:
        return False
    return True


def bundle_package_name(path: Path) -> str | None:
    path = Path(path)
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            meta = _read_manifest_json(zf)
            pkg = _package_from_meta(meta)
            if pkg:
                return pkg
            for name in zf.namelist():
                stem = Path(_norm_zip_name(name)).stem
                if name.lower().endswith(".apk") and _PKG_STEM.fullmatch(stem):
                    return stem
    except (zipfile.BadZipFile, OSError):
        return None
    return None


def extract_bundle(src: Path, dest: Path) -> ExtractedBundle:
    src = Path(src)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(src):
        raise ValueError(f"не zip/xapk: {src.name}")

    apks: list[Path] = []
    obbs: list[Path] = []
    split_ids: dict[str, str] = {}
    package: str | None = None
    used_names: set[str] = set()

    with zipfile.ZipFile(src) as zf:
        meta = _read_manifest_json(zf)
        package = _package_from_meta(meta)
        for item in (meta or {}).get("split_apks") or []:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file") or "").replace("\\", "/")
            split_id = str(item.get("id") or "").strip()
            if file_name and split_id:
                split_ids[Path(file_name).name.lower()] = split_id
        for name in zf.namelist():
            norm = _norm_zip_name(name)
            lower = norm.lower()
            if lower.endswith("/") or lower.startswith("__macosx/") or "/." in f"/{lower}":
                continue
            if lower.endswith(".apk"):
                target = _unique_dest(dest, Path(norm).name, used_names)
                _write_zip_entry(zf, name, target)
                if target.stat().st_size > 0:
                    apks.append(target)
            elif lower.endswith(".obb"):
                obb_dir = dest / "obb"
                obb_dir.mkdir(parents=True, exist_ok=True)
                target = _unique_dest(obb_dir, Path(norm).name, used_names)
                _write_zip_entry(zf, name, target)
                if target.stat().st_size > 0:
                    obbs.append(target)

    if not apks:
        raise ValueError("в контейнере нет APK")

    splits: list[BundleSplit] = []
    seen_split: set[str] = set()
    for apk in apks:
        raw = split_ids.get(apk.name.lower()) or _infer_split_name(apk, apks, package)
        name = _unique_split_name(raw, seen_split)
        splits.append(BundleSplit(path=apk, name=name, size=apk.stat().st_size))

    if len(splits) > 1 and not any(item.name == "base" for item in splits):
        largest = max(splits, key=lambda item: item.size)
        if largest.name in seen_split:
            seen_split.discard(largest.name)
        largest.name = _unique_split_name("base", seen_split)

    return ExtractedBundle(package=package, splits=splits, obb=obbs, work_dir=dest)


def parse_install_session(text: str) -> str | None:
    blob = text or ""
    match = _SESSION_ID.search(blob)
    if match:
        return match.group(1)
    match = _SESSION_WORD.search(blob)
    return match.group(1) if match else None


def _norm_zip_name(name: str) -> str:
    return name.replace("\\", "/").lstrip("/")


def _package_from_meta(meta: dict | None) -> str | None:
    if not meta:
        return None
    for key in ("package_name", "package", "packageName"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_manifest_json(zf: zipfile.ZipFile) -> dict | None:
    names = {_norm_zip_name(item): item for item in zf.namelist()}
    raw_name = names.get("manifest.json")
    if raw_name is None:
        for norm, original in names.items():
            if norm.lower().endswith("/manifest.json") or norm.lower() == "manifest.json":
                raw_name = original
                break
    if raw_name is None:
        return None
    try:
        data = json.loads(zf.read(raw_name).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, KeyError):
        return None
    return data if isinstance(data, dict) else None


def _write_zip_entry(zf: zipfile.ZipFile, name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(name) as src, dest.open("wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _unique_dest(folder: Path, filename: str, used: set[str]) -> Path:
    safe = Path(filename).name or "split.apk"
    stem, suffix = Path(safe).stem, Path(safe).suffix
    candidate = safe
    index = 2
    while candidate.lower() in used:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used.add(candidate.lower())
    return folder / candidate


def _infer_split_name(apk: Path, all_apks: list[Path], package: str | None) -> str:
    stem = apk.stem
    low = stem.lower()
    if low == "base" or low.endswith(".base") or low.startswith("base."):
        return "base"
    if package:
        pkg = package.lower()
        if low == pkg or low.startswith(pkg):
            return "base"
    if len(all_apks) == 1:
        return "base"
    return stem


def _unique_split_name(raw: str, seen: set[str]) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._" else "_" for ch in (raw or "split"))
    cleaned = re.sub(r"_+", "_", cleaned).strip("._") or "split"
    if cleaned[0].isdigit():
        cleaned = "s" + cleaned
    cleaned = cleaned[:80]
    name = cleaned
    index = 2
    while name.lower() in seen:
        name = f"{cleaned}_{index}"[:80]
        index += 1
    seen.add(name.lower())
    return name
