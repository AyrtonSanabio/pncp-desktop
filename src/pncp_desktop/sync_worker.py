from __future__ import annotations

import asyncio
import contextlib
import traceback
from typing import Any

from PySide6.QtCore import QThread, Signal

from pncp_sync.application.plan_details import plan_details
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_details import run_details
from pncp_sync.application.run_sync import run_sync
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import SyncWindow
from pncp_sync.persistence.detail_repositories import DetailRepository
from pncp_sync.persistence.repositories import SyncRepository


class SyncTaskThread(QThread):
    planned = Signal(object)
    detail_planned = Signal(str)
    progress = Signal(str, object)
    completed = Signal(object, object)
    paused = Signal(object, object)
    failed = Signal(str, str)

    def __init__(
        self,
        config: SyncConfig,
        *,
        action: str,
        window: SyncWindow | None = None,
        run_id: str | None = None,
        detail_run_id: str | None = None,
        include_details: bool = True,
        replace_plan_id: str | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.action = action
        self.window = window
        self.run_id = run_id
        self.detail_run_id = detail_run_id
        self.include_details = include_details
        self.replace_plan_id = replace_plan_id
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._task = loop.create_task(self._execute())
        try:
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            main, details = self._summaries()
            self.paused.emit(main, details)
        except Exception as exc:
            if self.action == "plan":
                user_message = (
                    "O PNCP não respondeu à estimativa dentro do tempo esperado. "
                    "Nenhum download foi iniciado; tente novamente mais tarde."
                )
            else:
                user_message = "Não foi possível concluir a sincronização."
            self.failed.emit(
                user_message,
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
            )
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._task = None
            self._loop = None
            loop.close()

    async def _execute(self) -> None:
        if self.action == "plan":
            if self.window is None:
                raise ValueError("A janela de sincronização não foi informada.")
            if self.replace_plan_id:
                with SyncRepository(self.config.db_path) as repository:
                    repository.discard_unused_plan(self.replace_plan_id)
            summary = await plan_sync(self.config, self.window)
            self.run_id = summary.run_id
            self.planned.emit(summary)
            return
        if self.action != "run" or not self.run_id:
            raise ValueError("A execução planejada não foi informada.")

        main_summary = await run_sync(
            self.config,
            self.run_id,
            progress=self._main_progress,
        )
        detail_summary = None
        if main_summary.status.startswith("COMPLETED") and self.include_details:
            if not self.detail_run_id:
                detail_plan = plan_details(self.config, self.run_id)
                self.detail_run_id = detail_plan.detail_run_id
                self.detail_planned.emit(self.detail_run_id)
            detail_summary = await run_details(
                self.config,
                self.detail_run_id,
                progress=self._detail_progress,
            )
        if main_summary.status == "PAUSED" or (
            detail_summary is not None and detail_summary.status == "PAUSED"
        ):
            self.paused.emit(main_summary, detail_summary)
        else:
            self.completed.emit(main_summary, detail_summary)

    def _main_progress(self, *_: Any) -> None:
        if not self.run_id:
            return
        with SyncRepository(self.config.db_path) as repository:
            self.progress.emit("contratacoes", repository.get_summary(self.run_id))

    def _detail_progress(self, *_: Any) -> None:
        if not self.detail_run_id:
            return
        with DetailRepository(self.config.db_path) as repository:
            self.progress.emit("detalhes", repository.get_detail_summary(self.detail_run_id))

    def _summaries(self) -> tuple[Any, Any]:
        main = None
        details = None
        if self.run_id:
            with contextlib.suppress(Exception), SyncRepository(self.config.db_path) as repository:
                main = repository.get_summary(self.run_id)
        if self.detail_run_id:
            with (
                contextlib.suppress(Exception),
                DetailRepository(self.config.db_path) as repository,
            ):
                details = repository.get_detail_summary(self.detail_run_id)
        return main, details

    def pause(self) -> None:
        self.requestInterruption()
        if self._loop is not None and self._task is not None and not self._loop.is_closed():
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._task.cancel)
