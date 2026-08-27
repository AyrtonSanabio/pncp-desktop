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
from pncp_sync.domain.models import (
    BatchPlanSummary,
    DetailRunSummary,
    RunSummary,
    SyncWindow,
)
from pncp_sync.persistence.detail_repositories import DetailRepository
from pncp_sync.persistence.repositories import SyncRepository


class SyncTaskThread(QThread):
    planned = Signal(object)
    detail_planned = Signal(str)
    progress = Signal(str, object)
    activity = Signal(str)
    completed = Signal(object, object)
    paused = Signal(object, object)
    failed = Signal(str, str)

    def __init__(
        self,
        config: SyncConfig,
        *,
        action: str,
        window: SyncWindow | None = None,
        windows: tuple[SyncWindow, ...] | None = None,
        run_id: str | None = None,
        run_ids: tuple[str, ...] | None = None,
        detail_run_id: str | None = None,
        include_details: bool = True,
        replace_plan_id: str | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.action = action
        self.window = window
        self.windows = windows or ()
        self.run_id = run_id
        self.run_ids = run_ids or (() if run_id is None else (run_id,))
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
            if self.action in {"plan", "plan_all"}:
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
        if self.action in {"plan", "plan_all"}:
            if self.action == "plan_all":
                if not self.windows:
                    raise ValueError("As modalidades da sincronização não foram informadas.")
                plans = []
                try:
                    for index, window in enumerate(self.windows, start=1):
                        self.activity.emit(
                            f"Estimando modalidade {window.modalidade} "
                            f"({index}/{len(self.windows)})…"
                        )
                        plans.append(await plan_sync(self.config, window))
                except Exception:
                    with SyncRepository(self.config.db_path) as repository:
                        for plan in plans:
                            repository.discard_unused_plan(plan.run_id)
                    raise
                summary = BatchPlanSummary(tuple(plans))
                self.run_ids = summary.run_ids
                self.run_id = summary.run_id
                self.planned.emit(summary)
                return
            if self.window is None:
                raise ValueError("A janela de sincronização não foi informada.")
            if self.replace_plan_id:
                with SyncRepository(self.config.db_path) as repository:
                    repository.discard_unused_plan(self.replace_plan_id)
            summary = await plan_sync(self.config, self.window)
            self.run_id = summary.run_id
            self.planned.emit(summary)
            return
        if self.action == "run_all":
            if not self.run_ids:
                raise ValueError("As execuções planejadas não foram informadas.")
            summaries = []
            detail_summaries = []
            for index, current_run_id in enumerate(self.run_ids, start=1):
                self.run_id = current_run_id
                self.activity.emit(
                    f"Sincronizando modalidade {index}/{len(self.run_ids)}…"
                )
                with SyncRepository(self.config.db_path) as repository:
                    reopened = repository.retry_recoverable_units(current_run_id)
                if reopened:
                    self.activity.emit(
                        f"Retomando {reopened} página(s) da modalidade {index}."
                    )
                main_summary = await run_sync(
                        self.config,
                        current_run_id,
                        progress=self._main_progress,
                        activity=self._main_activity,
                    )
                summaries.append(main_summary)
                if main_summary.status.startswith("COMPLETED") and self.include_details:
                    detail_plan = plan_details(self.config, current_run_id)
                    self.detail_run_id = detail_plan.detail_run_id
                    self.detail_planned.emit(self.detail_run_id)
                    detail_summaries.append(
                        await run_details(
                            self.config,
                            self.detail_run_id,
                            progress=self._detail_progress,
                            activity=self._detail_activity,
                        )
                    )
            aggregate_details = (
                self._aggregate_details(tuple(detail_summaries)) if detail_summaries else None
            )
            self.completed.emit(self._aggregate_runs(tuple(summaries)), aggregate_details)
            return
        if self.action != "run" or not self.run_id:
            raise ValueError("A execução planejada não foi informada.")

        with SyncRepository(self.config.db_path) as repository:
            reopened = repository.retry_recoverable_units(self.run_id)
        if reopened:
            self.activity.emit(
                f"Retomando {reopened} página(s) que tiveram falha temporária no PNCP."
            )
        main_summary = await run_sync(
            self.config,
            self.run_id,
            progress=self._main_progress,
            activity=self._main_activity,
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
                activity=self._detail_activity,
            )
        if main_summary.status == "PAUSED" or (
            detail_summary is not None and detail_summary.status == "PAUSED"
        ):
            self.paused.emit(main_summary, detail_summary)
        else:
            self.completed.emit(main_summary, detail_summary)

    @staticmethod
    def _aggregate_runs(summaries: tuple[RunSummary, ...]) -> RunSummary:
        if any(summary.status == "FAILED" for summary in summaries):
            status = "FAILED"
        elif any(summary.status == "PAUSED" for summary in summaries):
            status = "PAUSED"
        elif any(summary.status == "COMPLETED_WITH_REJECTIONS" for summary in summaries):
            status = "COMPLETED_WITH_REJECTIONS"
        else:
            status = "COMPLETED"
        fields = (
            "planned_units",
            "succeeded_units",
            "partial_units",
            "pending_units",
            "failed_units",
            "records_received",
            "records_inserted",
            "records_updated",
            "records_unchanged",
            "records_rejected",
            "bytes_received",
        )
        totals = {field: sum(getattr(summary, field) for summary in summaries) for field in fields}
        return RunSummary(run_id="batch", status=status, **totals)

    @staticmethod
    def _aggregate_details(summaries: tuple[DetailRunSummary, ...]) -> DetailRunSummary:
        if any(summary.status == "FAILED" for summary in summaries):
            status = "FAILED"
        elif any(summary.status == "PAUSED" for summary in summaries):
            status = "PAUSED"
        elif any(summary.status == "COMPLETED_WITH_REJECTIONS" for summary in summaries):
            status = "COMPLETED_WITH_REJECTIONS"
        else:
            status = "COMPLETED"
        fields = (
            "planned_units",
            "succeeded_units",
            "partial_units",
            "pending_units",
            "failed_units",
            "item_records",
            "result_records",
            "inserted_items",
            "updated_items",
            "unchanged_items",
            "inserted_results",
            "updated_results",
            "unchanged_results",
            "rejected_records",
            "bytes_received",
        )
        totals = {field: sum(getattr(summary, field) for summary in summaries) for field in fields}
        return DetailRunSummary(detail_run_id="batch", status=status, **totals)

    def _main_progress(self, *_: Any) -> None:
        if not self.run_id:
            return
        with SyncRepository(self.config.db_path) as repository:
            self.progress.emit("contratacoes", repository.get_summary(self.run_id))

    def _main_activity(self, work_unit: Any) -> None:
        self.activity.emit(
            f"Baixando contratações — página {work_unit.page_number} "
            f"({work_unit.data_inicial:%d/%m/%Y} a {work_unit.data_final:%d/%m/%Y})"
        )

    def _detail_progress(self, *_: Any) -> None:
        if not self.detail_run_id:
            return
        with DetailRepository(self.config.db_path) as repository:
            self.progress.emit("detalhes", repository.get_detail_summary(self.detail_run_id))

    def _detail_activity(self, work_unit: Any) -> None:
        if work_unit.resource == "ITEMS":
            description = f"itens, página {work_unit.page_number}"
        else:
            description = f"fornecedores/resultados do item {work_unit.item_number}"
        self.activity.emit(f"Baixando {description} — {work_unit.purchase.numero_controle_pncp}")

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
