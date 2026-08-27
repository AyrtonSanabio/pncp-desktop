from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal

from pncp_desktop.local_database import LocalDatabase


class DatabaseTaskThread(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        database: LocalDatabase,
        *,
        action: str,
        arguments: dict[str, Any] | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.action = action
        self.arguments = arguments or {}

    def run(self) -> None:
        try:
            if self.action == "snapshot":
                result = self.database.snapshot(**self.arguments)
            elif self.action == "latest_completed_date":
                result = self.database.latest_completed_date(**self.arguments)
            elif self.action == "diagnostics":
                result = self.database.diagnostics(**self.arguments)
            elif self.action == "detail":
                result = self.database.contract_detail(**self.arguments)
            elif self.action == "detail_by_control":
                result = self.database.contract_detail_by_control(**self.arguments)
            else:
                raise ValueError(f"Tarefa de banco desconhecida: {self.action}")
        except Exception as exc:
            self.failed.emit(self.action, f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(self.action, result)
