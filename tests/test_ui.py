from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pncp_desktop.ui import ContractDetailDialog, MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_exposes_three_areas(tmp_path) -> None:
    app = _app()
    window = MainWindow(tmp_path / "ui.sqlite3")
    assert [window.abas.tabText(i) for i in range(window.abas.count())] == [
        "Consulta online",
        "Sincronização",
        "Banco local",
    ]
    assert not window.botao_sincronizar.isEnabled()
    assert window.botao_estimar.isEnabled()
    window.close()
    app.processEvents()


def test_detail_dialog_has_general_extra_and_items_tabs() -> None:
    app = _app()
    detail = {"contratacao": {"numero_controle_pncp": "123"}, "itens": []}
    dialog = ContractDetailDialog(detail)
    tabs = dialog.findChildren(type(dialog.layout().itemAt(0).widget()))
    assert tabs
    assert dialog.windowTitle() == "Detalhes da contratação"
    dialog.close()
    app.processEvents()
