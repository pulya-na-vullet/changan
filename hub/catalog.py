"""Recommended apps for an English-language Changan Lamore 2023 head unit.

Proprietary store APKs are not bundled. Drop downloaded APKs into ./apps
and install them from the Hub. F-Droid packages can be fetched directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogApp:
    id: str
    name: str
    summary: str
    package: str
    kind: str
    source: str
    url: str | None = None
    notes: str = ""


CATALOG: list[CatalogApp] = [
    CatalogApp(
        id="quickbar",
        name="QuickBar (правая панель)",
        summary="Всегда поверх всех окон, справа, быстрый запуск установленных приложений.",
        package="com.changanhub.quickkeep",
        kind="dock",
        source="bundled",
        notes="Ставится одной кнопкой из раздела «Панель». В списке ГУ: QuickBar · com.changanhub.quickkeep. Старые quickbar / quickdock / quicklane Feiyu не удаляет (auth).",
    ),
    CatalogApp(
        id="files",
        name="Material Files",
        summary="Файловый менеджер — штатный проводник на английской ГУ часто спрятан.",
        package="me.zhanghai.android.files",
        kind="files",
        source="fdroid",
        url="https://f-droid.org/en/packages/me.zhanghai.android.files/",
        notes="Нужен, чтобы открывать APK, карты и загрузки на накопителе.",
    ),
    CatalogApp(
        id="vlc",
        name="VLC",
        summary="Видео и музыка без штатных ограничений форматов.",
        package="org.videolan.vlc",
        kind="media",
        source="fdroid",
        url="https://f-droid.org/en/packages/org.videolan.vlc/",
    ),
    CatalogApp(
        id="organic",
        name="Organic Maps",
        summary="Офлайн-карты без Google-сервисов — удобно на экспортной ГУ.",
        package="app.organicmaps",
        kind="nav",
        source="fdroid",
        url="https://f-droid.org/en/packages/app.organicmaps/",
    ),
    CatalogApp(
        id="newpipe",
        name="NewPipe",
        summary="YouTube-клиент без Play Services.",
        package="org.schabi.newpipe",
        kind="media",
        source="fdroid",
        url="https://f-droid.org/en/packages/org.schabi.newpipe/",
    ),
    CatalogApp(
        id="fennec",
        name="Fennec / Firefox",
        summary="Полноценный браузер, если штатный урезан.",
        package="org.mozilla.fennec_fdroid",
        kind="web",
        source="fdroid",
        url="https://f-droid.org/en/packages/org.mozilla.fennec_fdroid/",
    ),
    CatalogApp(
        id="yandex-nav",
        name="Яндекс Навигатор",
        summary="Положите APK в папку apps/ и установите через Hub.",
        package="ru.yandex.yandexnavi",
        kind="nav",
        source="local",
        notes="Скачайте APK самостоятельно (сайт Яндекса / RuStore) и перетащите в окно установки.",
    ),
    CatalogApp(
        id="yandex-music",
        name="Яндекс Музыка",
        summary="Локальный APK, подпись Hub ставит автоматически.",
        package="ru.yandex.music",
        kind="media",
        source="local",
    ),
    CatalogApp(
        id="tg",
        name="Telegram",
        summary="Мессенджер. Берите официальный APK и ставьте через Hub.",
        package="org.telegram.messenger",
        kind="chat",
        source="local",
        url="https://telegram.org/android",
    ),
]


def by_id(app_id: str) -> CatalogApp | None:
    for item in CATALOG:
        if item.id == app_id:
            return item
    return None


_EXTRA_LABELS = {
    "net.easyconn": "EasyConnection",
    "gb.xxy.hr": "HR",
    "ru.yandex.androidkeyboard": "Яндекс Клавиатура",
    "ru.kinopoisk": "Кинопоиск",
    "air.StrelkaHUDFREE": "Стрелка",
    "com.changanhub.quickbar": "QuickBar (старая, Feiyu не удаляет)",
    "com.changanhub.quickdock": "QuickBar (предыдущая, Feiyu не удаляет)",
    "com.changanhub.quicklane": "QuickBar (предыдущая, Feiyu не удаляет)",
}


def package_label(package: str) -> str:
    for item in CATALOG:
        if item.package == package:
            return f"{item.name}  ·  {package}"
    extra = _EXTRA_LABELS.get(package)
    if extra:
        return f"{extra}  ·  {package}"
    return package


def package_from_row(row: str) -> str:
    if "  ·  " in row:
        return row.rsplit("  ·  ", 1)[-1].strip()
    return row.strip()
