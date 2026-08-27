from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import QTimer

from pncp_desktop.ui import MainWindow, criar_aplicacao


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consulta PNCP Desktop")
    parser.add_argument("--demo", action="store_true", help="abre com dados demonstrativos")
    parser.add_argument("--screenshot", type=Path, help="salva uma captura e encerra")
    return parser.parse_args()


def main() -> int:
    argumentos = _argumentos()
    app = criar_aplicacao()
    janela = MainWindow()

    if argumentos.demo:
        janela.carregar_demonstracao()

    janela.show()

    if argumentos.screenshot:
        destino = argumentos.screenshot

        def capturar() -> None:
            destino.parent.mkdir(parents=True, exist_ok=True)
            janela.grab().save(str(destino))
            app.quit()

        QTimer.singleShot(500, capturar)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
