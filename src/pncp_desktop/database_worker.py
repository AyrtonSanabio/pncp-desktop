from __future__ import annotations

from threading import Event
from typing import Any

from PySide6.QtCore import QThread, Signal

from pncp_desktop.local_database import LocalDatabase


class DatabaseTaskThread(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)
    progress = Signal(str, int, int)

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
        self._cancelled = Event()

    def cancel_backup(self) -> None:
        if self.action == "create_backup":
            self._cancelled.set()

    def run(self) -> None:
        try:
            actions = {
                "recalculate_progress": "recalculate_progress",
                "snapshot": "snapshot",
                "advanced_search": "advanced_search",
                "advanced_search_all": "advanced_search_all",
                "hybrid_search": "hybrid_search",
                "duplicate_candidates": "duplicate_candidates",
                "performance_report": "performance_report",
                "sync_history": "sync_history",
                "analytics": "analytics",
                "refresh_insights": "refresh_insights",
                "price_history": "price_history",
                "semantic_search": "semantic_search",
                "rebuild_semantic_index": "rebuild_semantic_index",
                "saved_queries": "saved_queries",
                "save_query": "save_query",
                "latest_completed_date": "latest_completed_date",
                "latest_completed_date_all": "latest_completed_date_all",
                "diagnostics": "diagnostics",
                "quick_check": "quick_check",
                "create_backup": "create_backup",
                "safe_maintenance": "safe_maintenance",
                "import_new_database": "import_new_database",
                "detail": "contract_detail",
                "detail_by_control": "contract_detail_by_control",
            }
            method_name = actions.get(self.action)
            if method_name is None:
                raise ValueError(f"Tarefa de banco desconhecida: {self.action}")
            method = getattr(self.database, method_name, None)
            if method is None:
                raise RuntimeError(
                    f"O banco desta versão ainda não oferece a operação {self.action}."
                )
            arguments = dict(self.arguments)
            if self.action == "create_backup":
                arguments.update(progress=self.progress.emit, cancelled=self._cancelled.is_set)
            result = method(**arguments)
        except Exception as exc:
            self.failed.emit(self.action, f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(self.action, result)
