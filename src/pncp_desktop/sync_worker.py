from __future__ import annotations

import asyncio
import contextlib
import traceback
from typing import Any

from pypncp import PNCPError
from PySide6.QtCore import QThread, Signal

from pncp_sync.adapters.pypncp_source import SourceError
from pncp_sync.application.catalog_sync import CatalogSync
from pncp_sync.application.plan_details import plan_details
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_details import run_details
from pncp_sync.application.run_sync import run_sync
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import (
    BatchPlanSummary,
    DetailRunSummary,
    FullSyncProgress,
    RunSummary,
    SyncWindow,
)
from pncp_sync.persistence.detail_repositories import DetailRepository
from pncp_sync.persistence.repositories import SyncRepository


class SyncTaskThread(QThread):
    _PLANNING_ATTEMPTS = 5
    _PLANNING_PACE_SECONDS = 2.5
    _SAMPLE_WINDOWS = 12
    planned = Signal(object)
    detail_planned = Signal(str)
    progress = Signal(str, object)
    full_progress = Signal(object)
    activity = Signal(str)
    completed = Signal(object, object)
    paused = Signal(object, object)
    failed = Signal(str, str)
    catalog_completed = Signal(object)

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
        include_contracts: bool = False,
        include_atas: bool = False,
        estimated_total_pages: int | None = None,
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
        self.include_contracts = include_contracts
        self.include_atas = include_atas
        self.estimated_total_pages = estimated_total_pages
        self.replace_plan_id = replace_plan_id
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._planned_count = 0
        self._planned_total = 0
        self._full_total_windows = 0
        self._full_completed_windows = 0
        self._full_current_index: int | None = None
        self._full_current_window: SyncWindow | None = None
        self._full_confirmed_pages = 0

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
            if self.action in {"plan", "plan_all", "plan_sample"}:
                if isinstance(exc, SourceError):
                    user_message = (
                        "O PNCP respondeu, mas o conteúdo não estava no formato esperado. "
                        "Nenhum download foi iniciado; consulte o detalhe técnico."
                    )
                else:
                    user_message = (
                        "Não foi possível concluir a estimativa. Nenhum download foi iniciado. "
                        "O detalhe técnico informa se houve timeout, resposta HTTP ou validação."
                    )
                if self.action in {"plan_all", "plan_sample"} and self._planned_count:
                    user_message += (
                        f" O progresso foi preservado: {self._planned_count}/"
                        f"{self._planned_total} lotes já estimados serão reutilizados "
                        "na próxima tentativa."
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
        if self.action in {"plan", "plan_all", "plan_sample"}:
            if self.action in {"plan_all", "plan_sample"}:
                if not self.windows:
                    raise ValueError("As modalidades da sincronização não foram informadas.")
                planning_windows = (
                    self._sample_windows(self.windows)
                    if self.action == "plan_sample"
                    else self.windows
                )
                plans = []
                self._planned_total = len(planning_windows)
                try:
                    for index, window in enumerate(planning_windows, start=1):
                        self.activity.emit(
                            f"Estimando modalidade {window.modalidade} "
                            f"({index}/{len(planning_windows)})…"
                        )
                        plan = await self._plan_with_retry(window)
                        plans.append(plan)
                        self.run_ids = tuple(item.run_id for item in plans)
                        self.run_id = self.run_ids[0]
                        self._planned_count = len(plans)
                        if index < len(planning_windows) and not plan.reused:
                            await asyncio.sleep(self._PLANNING_PACE_SECONDS)
                except Exception:
                    raise
                summary = BatchPlanSummary(
                    tuple(plans),
                    population_windows=len(self.windows)
                    if self.action == "plan_sample"
                    else None,
                )
                self.run_ids = summary.run_ids
                self.run_id = summary.run_id
                self.planned.emit(summary)
                return
            if self.window is None:
                raise ValueError("A janela de sincronização não foi informada.")
            if self.replace_plan_id:
                with SyncRepository(self.config.db_path) as repository:
                    repository.discard_unused_plan(self.replace_plan_id)
            summary = await self._plan_with_retry(self.window)
            self.run_id = summary.run_id
            self.planned.emit(summary)
            return
        if self.action == "full_sync":
            await self._run_full_sync()
            return
        if self.action == "run_all":
            if not self.run_ids:
                raise ValueError("As execuções planejadas não foram informadas.")
            summaries = []
            detail_summaries = []
            for index, current_run_id in enumerate(self.run_ids, start=1):
                self.run_id = current_run_id
                self.activity.emit(f"Sincronizando lote {index}/{len(self.run_ids)}…")
                with SyncRepository(self.config.db_path) as repository:
                    reopened = repository.retry_recoverable_units(current_run_id)
                if reopened:
                    self.activity.emit(
                        f"Retomando {reopened} página(s) do lote {index}."
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
            await self._run_catalog_resources()
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
            await self._run_catalog_resources()
            self.completed.emit(main_summary, detail_summary)

    @classmethod
    def _sample_windows(
        cls, windows: tuple[SyncWindow, ...]
    ) -> tuple[SyncWindow, ...]:
        """Amostra uniformemente início, meio e fim de toda a população."""
        if len(windows) <= cls._SAMPLE_WINDOWS:
            return windows
        last = len(windows) - 1
        indexes = {
            round(index * last / (cls._SAMPLE_WINDOWS - 1))
            for index in range(cls._SAMPLE_WINDOWS)
        }
        return tuple(windows[index] for index in sorted(indexes))

    async def _run_full_sync(self) -> None:
        """Planeja e confirma um recorte por vez, com checkpoint durável."""
        if not self.windows:
            raise ValueError("Os lotes da carga completa não foram informados.")
        summaries = []
        detail_summaries = []
        self._planned_total = len(self.windows)
        self._full_total_windows = len(self.windows)
        self._full_completed_windows = 0
        self._full_confirmed_pages = 0
        self._emit_full_progress()
        for index, window in enumerate(self.windows, start=1):
            self._full_current_index = index
            self._full_current_window = window
            self.activity.emit(
                f"Carga completa: lote {index}/{len(self.windows)} — "
                f"{window.data_inicial:%d/%m/%Y} a {window.data_final:%d/%m/%Y}, "
                f"modalidade {window.modalidade}."
            )
            with SyncRepository(self.config.db_path) as repository:
                completed_run = repository.find_completed_run(window)
            if completed_run:
                with SyncRepository(self.config.db_path) as repository:
                    summary = repository.get_summary(completed_run)
                summaries.append(summary)
                self._full_completed_windows = index
                self._full_confirmed_pages += (
                    summary.succeeded_units + summary.partial_units
                )
                self._emit_full_progress()
                continue
            with SyncRepository(self.config.db_path) as repository:
                resumable_run = repository.find_resumable_run(window)
                if resumable_run:
                    repository.retry_recoverable_units(resumable_run)
            plan = None if resumable_run else await self._plan_with_retry(window)
            current_run_id = resumable_run or plan.run_id
            self.run_id = current_run_id
            self.run_ids = (*self.run_ids, current_run_id)
            self._planned_count = index
            with SyncRepository(self.config.db_path) as repository:
                self._emit_full_progress(repository.get_summary(current_run_id))
            main_summary = await self._run_full_window_continuously(current_run_id)
            summaries.append(main_summary)
            if not main_summary.status.startswith("COMPLETED"):
                self._emit_full_progress(main_summary)
                break
            self._full_completed_windows = index
            self._full_confirmed_pages += (
                main_summary.succeeded_units + main_summary.partial_units
            )
            self._emit_full_progress()
            if self.include_details:
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
            if index < len(self.windows) and plan is not None and not plan.reused:
                await asyncio.sleep(self._PLANNING_PACE_SECONDS)

        aggregate = self._aggregate_runs(tuple(summaries))
        aggregate_details = (
            self._aggregate_details(tuple(detail_summaries)) if detail_summaries else None
        )
        if aggregate.status == "PAUSED":
            self.paused.emit(aggregate, aggregate_details)
        else:
            if aggregate.status.startswith("COMPLETED"):
                await self._run_catalog_resources()
            self.completed.emit(aggregate, aggregate_details)

    async def _run_full_window_continuously(self, run_id: str) -> RunSummary:
        """Repete falhas recuperáveis até concluir ou receber cancelamento do usuário."""
        consecutive_failures = 0
        previous_done = -1
        while True:
            summary = await run_sync(
                self.config,
                run_id,
                progress=self._main_progress,
                activity=self._main_activity,
                status=self.activity.emit,
            )
            if summary.status.startswith("COMPLETED"):
                return summary

            with SyncRepository(self.config.db_path) as repository:
                reopened = repository.retry_recoverable_units(run_id)
                latest_error = repository.latest_error(run_id)
            if reopened <= 0:
                # Erro de validação, contrato da fonte ou outra falha definitiva.
                return summary

            done = summary.succeeded_units + summary.partial_units
            consecutive_failures = (
                1 if done > previous_done else consecutive_failures + 1
            )
            previous_done = done
            delay = min(
                self.config.continuous_retry_base_seconds
                * (2 ** min(10, max(0, consecutive_failures - 1))),
                self.config.continuous_retry_max_seconds,
            )
            reason = (
                str(latest_error.get("message") or latest_error.get("category"))
                if latest_error
                else "falha temporária do PNCP"
            )[:240]
            await self._wait_before_full_retry(
                delay,
                reason=reason,
                reopened=reopened,
                cycle=consecutive_failures,
            )

    async def _wait_before_full_retry(
        self,
        seconds: int,
        *,
        reason: str,
        reopened: int,
        cycle: int,
    ) -> None:
        """Espera cancelável e atualiza a tela sem fazer novas requisições."""
        remaining = seconds
        while remaining > 0:
            self.activity.emit(
                f"PNCP indisponível: {reason}. {reopened} página(s) continuam pendentes. "
                f"Nova tentativa automática em {remaining} s (ciclo {cycle}); "
                "use Pausar para interromper com segurança."
            )
            step = min(30, remaining)
            await asyncio.sleep(step)
            remaining -= step

    async def _plan_with_retry(self, window: SyncWindow) -> Any:
        """Planeja um recorte com espera adequada para timeout e HTTP 429."""
        for attempt in range(1, self._PLANNING_ATTEMPTS + 1):
            try:
                return await plan_sync(self.config, window)
            except PNCPError as exc:
                if attempt >= self._PLANNING_ATTEMPTS:
                    raise
                message = str(exc).lower()
                rate_limited = "too many requests" in message or "429" in message
                delay = 60 if rate_limited else min(10 * (2 ** (attempt - 1)), 60)
                reason = "limite de requisições HTTP 429" if rate_limited else "falha temporária"
                self.activity.emit(
                    f"PNCP informou {reason}. Aguardando {delay} s antes da tentativa "
                    f"{attempt + 1}/{self._PLANNING_ATTEMPTS}; não feche o programa."
                )
                await asyncio.sleep(delay)

        raise RuntimeError("A estimativa encerrou sem resultado e sem exceção identificada.")

    async def _run_catalog_resources(self) -> None:
        if not self.include_contracts and not self.include_atas:
            return
        windows = self.windows or (() if self.window is None else (self.window,))
        if not windows:
            return
        start = min(window.data_inicial for window in windows)
        end = max(window.data_final for window in windows)
        service = CatalogSync(self.config)
        reports = []
        for resource, enabled, label in (
            ("CONTRACTS", self.include_contracts, "contratos e empenhos"),
            ("ATAS", self.include_atas, "atas de registro de preços"),
        ):
            if not enabled:
                continue
            self.activity.emit(f"Planejando {label}…")
            plan = await service.plan(resource, start, end)
            self.activity.emit(
                f"Baixando {label}: {plan['total_pages']} página(s), "
                f"{plan['total_records']} registro(s)…"
            )
            reports.append(await service.run(plan["run_id"]))
        self.catalog_completed.emit(reports)

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
            summary = repository.get_summary(self.run_id)
            self.progress.emit("contratacoes", summary)
            if self.action == "full_sync":
                self._emit_full_progress(summary)

    def _emit_full_progress(self, summary: RunSummary | None = None) -> None:
        """Publica o total global e somente as páginas realmente conhecidas."""
        done = 0
        total = 0
        failed = 0
        records = 0
        received = 0
        if summary is not None:
            done = summary.succeeded_units + summary.partial_units
            total = summary.planned_units
            failed = summary.failed_units
            records = summary.records_received
            received = summary.bytes_received
        self.full_progress.emit(
            FullSyncProgress(
                total_windows=self._full_total_windows,
                completed_windows=self._full_completed_windows,
                current_window_index=self._full_current_index,
                current_window=self._full_current_window,
                current_pages_done=done,
                current_pages_total=total,
                current_failed_pages=failed,
                confirmed_pages=self._full_confirmed_pages + done,
                estimated_total_pages=self.estimated_total_pages,
                records_received=records,
                bytes_received=received,
            )
        )

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
