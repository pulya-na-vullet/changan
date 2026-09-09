"""Command-line entry: python -m hub connect|install|overlay|apps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hub.adb import Adb, AdbError
from hub.installer import install_apk
from hub.overlay import install_overlay, start_overlay, stop_overlay
from hub.signer import certificate_info, ensure_keystore, sign_apk


def _adb() -> Adb:
    adb = Adb()
    if not adb.wait_for_device(8):
        raise AdbError("Головное устройство не видно. Включите ADB и проверьте кабель.")
    adb.pick_serial()
    return adb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Changan Hub CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gui", help="Открыть графический интерфейс")
    sub.add_parser("connect", help="Показать устройства и свойства ГУ")
    sub.add_parser("cert", help="Показать локальный сертификат")
    p_sign = sub.add_parser("sign", help="Переподписать APK под Changan")
    p_sign.add_argument("apk")
    p_inst = sub.add_parser("install", help="Подписать и поставить APK")
    p_inst.add_argument("apk")
    sub.add_parser("overlay", help="Поставить и запустить правую панель")
    sub.add_parser("overlay-start")
    sub.add_parser("overlay-stop")
    sub.add_parser("apps", help="Список пакетов на ГУ")

    args = parser.parse_args(argv)
    if args.cmd == "gui":
        from hub.gui import main as gui_main

        gui_main()
        return 0
    if args.cmd == "cert":
        print(json.dumps(certificate_info(ensure_keystore()), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "sign":
        out = sign_apk(Path(args.apk))
        print(out)
        return 0

    try:
        adb = _adb()
    except AdbError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.cmd == "connect":
        for dev in adb.devices():
            print(dev["raw"])
        for key, value in adb.props().items():
            print(f"{key:12} {value}")
        return 0
    if args.cmd == "install":
        report = install_apk(adb, Path(args.apk))
        print("\n".join(report.log))
        return 0 if report.ok else 1
    if args.cmd == "overlay":
        print("\n".join(install_overlay(adb)))
        return 0
    if args.cmd == "overlay-start":
        print("\n".join(start_overlay(adb)))
        return 0
    if args.cmd == "overlay-stop":
        print("\n".join(stop_overlay(adb)))
        return 0
    if args.cmd == "apps":
        print("\n".join(adb.packages()))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
