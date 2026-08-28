from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from pncp_desktop.ui import MainWindow, criar_aplicacao
from pncp_desktop.update_check import UpdateInfo, check_latest_release


class UpdateCheckThread(QThread):
    completed = Signal(object)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = current_version

    def run(self) -> None:
        try:
            self.completed.emit(check_latest_release(self.current_version))
        except Exception:
            # Atualizacao e opcional: falha de rede nunca impede o aplicativo.
            self.completed.emit(None)


def _current_version() -> str:
    try:
        return version("pncp-desktop")
    except PackageNotFoundError:
        return "0.2.0"


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consulta PNCP Desktop")
    parser.add_argument("--screenshot", type=Path, help="salva uma captura e encerra")
    parser.add_argument(
        "--check-updates",
        action="store_true",
        help="consulta opcionalmente a ultima versao publicada no GitHub",
    )
    return parser.parse_args()


def main() -> int:
    argumentos = _argumentos()
    app = criar_aplicacao()
    janela = MainWindow()

    janela.show()
    janela.raise_()
    janela.activateWindow()
    QTimer.singleShot(0, janela.activateWindow)

    update_thread: UpdateCheckThread | None = None
    if argumentos.check_updates:
        update_thread = UpdateCheckThread(_current_version())

        def show_update(info: UpdateInfo | None) -> None:
            if info is None or not info.available:
                return
            answer = QMessageBox.information(
                janela,
                "Atualizacao disponivel",
                f"A versao {info.latest_version} esta disponivel. Deseja abrir a pagina?",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Open:
                QDesktopServices.openUrl(QUrl(info.release_url))

        update_thread.completed.connect(show_update)
        update_thread.start()

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
