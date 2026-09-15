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
        name="QuickBar 1.3.16 (правая панель)",
        summary="Всегда поверх всех окон, справа, быстрый запуск установленных приложений.",
        package="com.changanhub.qb1_3_16",
        kind="dock",
        source="bundled",
        notes="Ставится из «Наши приложения». В списке ГУ: QuickBar 1.3.16 · com.changanhub.qb1_3_16. Скрытие, сортировка и свайп «спрятать от дилера» — в зелёной колонке справа. USB или память ГУ: ключ подписывает APK v1+v2 серийником Feiyu (как Hub), зелёная кнопка ставит. Корень флешки тоже читается, в том числе через /mnt/media_rw если /storage/UUID пустой. Свёрнутые кнопки ×2.5. Сторонние приложения — кнопка «окно» (freeform, если ГУ умеет). Старые quickbar / … / quickload / qb1_3_15 Feiyu не удаляет (auth) — это не новая панель.",
    ),
    CatalogApp(
        id="player",
        name="Lamore Player 1.1.5",
        summary="Музыка и видео с флешки ГУ: вкладки, EQ, визуализации, субтитры.",
        package="com.changanhub.pl1_1_5",
        kind="media",
        source="bundled",
        notes="Ставится из «Наши приложения». Пакет com.changanhub.pl1_1_5 (старые pl1_1_4 / pl1_1_3 / playload / playrise / lamoreplayer Feiyu не удаляет). Шрифты ×2. Читает USB ГУ включая корень флешки (не флешку ноутбука), открывает файл через /mnt/media_rw и FileDescriptor если FUSE /storage не играет. Вкладки музыка/видео/эквалайзер/визуализация. Форматы Feiyu: MP3/AAC/FLAC/WAV/OGG/OPUS, MP4/MKV/WebM/MOV/TS и др.",
    ),
    CatalogApp(
        id="aichat",
        name="AI Chat 1.0.5",
        summary="Чат с DeepSeek и YandexGPT, автоозвучка ответов.",
        package="com.changanhub.ch1_0_5",
        kind="chat",
        source="bundled",
        notes="Ставится из «Наши приложения». Пакет com.changanhub.ch1_0_5. Шрифты ×2. Интернет на ГУ. Ключи в Настройках. Озвучка — RHVoice (Елена) внутри APK, не системный TTS. На Feiyu нет Google STT — пишите текстом (Яндекс-клавиатура). Русский UI из приложения, не из языка системы. Старые chatload / chatrise / aichat Feiyu не удаляет.",
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
    "com.yandex.browser.lite": "Яндекс Браузер Лайт",
    "com.android.chrome": "Chrome",
    "air.StrelkaHUDFREE": "Стрелка",
    "com.changanhub.quickbar": "QuickBar (старая, без скрытия/сортировки)",
    "com.changanhub.quickdock": "QuickBar (старая, без скрытия/сортировки)",
    "com.changanhub.quicklane": "QuickBar (старая, без скрытия/сортировки)",
    "com.changanhub.quickkeep": "QuickBar (старая, без скрытия/сортировки)",
    "com.changanhub.quickrise": "QuickBar (старая, без свайпа спрятать)",
    "com.changanhub.quickstash": "QuickBar (старая, без подписи с флешки)",
    "com.changanhub.quickload": "QuickBar (старая, без версии в имени пакета)",
    "com.changanhub.qb1_3_15": "QuickBar (старая, флешка видна без файлов)",
    "com.changanhub.playload": "Lamore Player (старый пакет)",
    "com.changanhub.pl1_1_4": "Lamore Player (старый, флешка видна без звука)",
    "com.changanhub.pl1_1_3": "Lamore Player (старый, флешка видна без файлов)",
    "com.changanhub.playrise": "Lamore Player (старый, без корня флешки)",
    "com.changanhub.lamoreplayer": "Lamore Player (старый пакет)",
    "com.changanhub.chatload": "AI Chat (старый пакет)",
    "com.changanhub.chatrise": "AI Chat (старый пакет)",
    "com.changanhub.aichat": "AI Chat (старый пакет)",
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
