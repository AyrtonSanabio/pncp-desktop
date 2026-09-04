from __future__ import annotations

import asyncio
import contextlib
import traceback
from collections import deque
from dataclasses import replace
from datetime import date
from typing import Any

from pypncp import PNCPError
from PySide6.QtCore import QThread, Signal

from pncp_sync.adapters.pypncp_source import SourceError
from pncp_sync.application.catalog_sync import CatalogSync
from pncp_sync.application.incremental import (
    prepare_incremental,
    session_windows,
    set_session_status,
)
from pncp_sync.application.plan_details import plan_details
from pncp_sync.application.plan_sync import plan_sync
from pncp_sync.application.run_details import run_details
from pncp_sync.application.run_sync import _is_recoverable, run_sync
from pncp_sync.application.run_sync_parallel import ConcurrencyState, run_sync_parallel
from pncp_sync.config import SyncConfig
from pncp_sync.domain.models import (
    UPDATES,
    BatchPlanSummary,
    DetailPlanSummary,
    DetailRunSummary,
    FullSyncProgress,
    RunSummary,
    SyncWindow,
)
from pncp_sync.persistence.detail_repositories import DetailRepository
from pncp_sync.persistence.repositories import SyncRepository


class SyncTaskThread(QThread):
    _PLANNING_ATTEMPTS = 5
    _PLANNING_PACE_SECONDS = 1.0
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
        details_recent_active_only: bool = False,
        include_contracts: bool = False,
        include_atas: bool = False,
        estimated_total_pages: int | None = None,
        estimated_total_records: int | None = None,
        replace_plan_id: str | None = None,
        modalidades: tuple[int, ...] = (),
        target_date: date | None = None,
        update_to_today: bool = False,
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
        self.details_recent_active_only = details_recent_active_only
        self.include_contracts = include_contracts
        self.include_atas = include_atas
        self.estimated_total_pages = estimated_total_pages
        self.estimated_total_records = estimated_total_records
        self.replace_plan_id = replace_plan_id
        self.modalidades = modalidades
        self.target_date = target_date
        self.update_to_today = update_to_today
        self._incremental_created_after = ""
        self._concurrency_state = ConcurrencyState(
            config.max_concurrent, min(2, config.max_concurrent)
        )
        self._empty_failed_sweeps = 0
        self._outage_waits = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._planned_count = 0
        self._planned_total = 0
        self._full_total_windows = 0
        self._full_completed_windows = 0
        self._full_current_index: int | None = None
        self._full_current_window: SyncWindow | None = None
        self._full_confirmed_pages = 0
        self._full_stored_records: int | None = None

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
            if self.action == "incremental":
                user_message = f"Atualização incremental não concluída: {exc}"
                try:
                    if self._incremental_created_after:
                        set_session_status(self.config, active=True, manual_pause=True)
                except Exception:
                    # Preserva o diagnóstico original se o próprio banco/checkpoint falhou.
                    user_message += " Não foi possível registrar a pausa; preserve o banco."
            elif self.action in {"plan", "plan_all", "plan_sample"}:
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
        if self.action == "incremental":
            session = prepare_incremental(
                self.config, self.modalidades, today=self.target_date,
                extend_to_today=self.update_to_today,
                allow_incomplete_history=self.update_to_today,
            )
            self.windows = session_windows(session)
            self.config = replace(self.config, publication_page_size=session["page_size"])
            self._incremental_created_after = session["created_at"]
            self.include_details = self.include_contracts = self.include_atas = False
            self.activity.emit(
                f"Atualização incremental: {len(self.windows)} lotes de publicações e "
                "alterações globais. A carga histórica não será reiniciada."
            )
            await self._run_full_sync()
            return
        if self.action == "recover_failures":
            from pncp_sync.persistence.progress_report import progress_report

            report = progress_report(self.config.db_path)
            self.run_ids = tuple(report["failed_run_ids"])
            summaries = {}
            confirmed = {}
            with SyncRepository(self.config.db_path) as repository:
                for run_id in self.run_ids:
                    repository.retry_failed_units_explicitly(run_id)
                    summary = repository.get_summary(run_id)
                    summaries[run_id] = summary
                    confirmed[run_id] = summary.succeeded_units + summary.partial_units
            await self._retry_deferred_work([], list(self.run_ids), summaries, confirmed, [], set())
            self.completed.emit(self._aggregate_runs(tuple(summaries.values())), None)
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
                main_summary = await self._run_main_continuously(current_run_id)
                summaries.append(main_summary)
                if not main_summary.status.startswith("COMPLETED"):
                    break
                if main_summary.status.startswith("COMPLETED") and self.include_details:
                    detail_plan = self._plan_details(current_run_id)
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
            aggregate = self._aggregate_runs(tuple(summaries))
            if aggregate.status.startswith("COMPLETED"):
                await self._run_catalog_resources()
            self.completed.emit(aggregate, aggregate_details)
            return
        if self.action != "run" or not self.run_id:
            raise ValueError("A execução planejada não foi informada.")

        main_summary = await self._run_main_continuously(self.run_id)
        detail_summary = None
        if main_summary.status.startswith("COMPLETED") and self.include_details:
            if not self.detail_run_id:
                detail_plan = self._plan_details(self.run_id)
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
        """Percorre todos os recortes e revisita falhas temporárias em rodízio."""
        if not self.windows:
            raise ValueError("Os lotes da carga completa não foram informados.")
        summaries: dict[str, RunSummary] = {}
        confirmed_by_run: dict[str, int] = {}
        deferred_windows: list[SyncWindow] = []
        deferred_runs: list[str] = []
        detail_summaries = []
        detailed_runs: set[str] = set()
        self._planned_total = len(self.windows)
        self._full_total_windows = len(self.windows)
        self._full_completed_windows = 0
        self._full_confirmed_pages = 0
        with SyncRepository(self.config.db_path) as repository:
            self._full_stored_records = repository.count_contratacoes()
        self._emit_full_progress()
        for index, window in enumerate(self.windows, start=1):
            self._full_current_index = index
            self._full_current_window = window
            label = "Atualização incremental" if self.action == "incremental" else "Carga completa"
            self.activity.emit(
                f"{label}: "
                f"{'retificações' if window.resource == UPDATES else 'publicações'}, "
                f"lote {index}/{len(self.windows)} — "
                f"{window.data_inicial:%d/%m/%Y} a {window.data_final:%d/%m/%Y}, "
                f"modalidade {window.modalidade}."
            )
            with SyncRepository(self.config.db_path) as repository:
                completed_run = repository.find_completed_run(
                    window, **self._incremental_scope()
                )
            if completed_run:
                with SyncRepository(self.config.db_path) as repository:
                    summary = repository.get_summary(completed_run)
                summaries[completed_run] = summary
                confirmed = summary.succeeded_units + summary.partial_units
                confirmed_by_run[completed_run] = confirmed
                self._full_completed_windows = index
                self._full_confirmed_pages += confirmed
                self._emit_full_progress()
                continue
            with SyncRepository(self.config.db_path) as repository:
                resumable_run = repository.find_resumable_run(
                    window, **self._incremental_scope()
                )
                if resumable_run:
                    repository.reclassify_false_period_limit_errors(resumable_run)
                    repository.retry_recoverable_units(resumable_run)
            try:
                plan = (
                    None
                    if resumable_run
                    else await self._plan_full_window(window)
                )
            except PNCPError as exc:
                deferred_windows.append(window)
                self.activity.emit(
                    f"Planejamento do lote {index}/{len(self.windows)} adiado: {exc}. "
                    "A carga seguirá para o próximo lote e voltará a este depois."
                )
                self._full_completed_windows = index
                self._emit_full_progress()
                continue
            current_run_id = resumable_run or plan.run_id
            self.run_id = current_run_id
            self.run_ids = (*self.run_ids, current_run_id)
            self._planned_count = index
            with SyncRepository(self.config.db_path) as repository:
                self._emit_full_progress(repository.get_summary(current_run_id))
            # Uma carga completa não pode ficar monopolizada por uma única página.
            # Cada lote recebe uma varredura finita; falhas recuperáveis são
            # preservadas e entram no rodízio executado após os lotes primários.
            main_summary = await self._run_main_sweep(current_run_id)
            summaries[current_run_id] = main_summary
            confirmed = main_summary.succeeded_units + main_summary.partial_units
            confirmed_by_run[current_run_id] = confirmed
            self._full_completed_windows = index
            self._full_confirmed_pages += confirmed
            self._emit_full_progress()
            if main_summary.failed_units or main_summary.pending_units:
                with SyncRepository(self.config.db_path) as repository:
                    recoverable = repository.count_recoverable_failed_units(
                        current_run_id
                    )
                has_deferred = recoverable or main_summary.pending_units
                if has_deferred and current_run_id not in deferred_runs:
                    deferred_runs.append(current_run_id)
                self.activity.emit(
                    f"Lote {index}/{len(self.windows)} percorrido com "
                    f"{main_summary.failed_units + main_summary.pending_units} "
                    "página(s) adiada(s). Os índices "
                    "foram catalogados e a carga seguirá para o próximo lote."
                )
            elif self.include_details:
                await self._collect_details_for_run(
                    current_run_id, detail_summaries, detailed_runs
                )
            if index < len(self.windows) and plan is not None and not plan.reused:
                await asyncio.sleep(self._PLANNING_PACE_SECONDS)

            if main_summary.status == "PAUSED":
                break

        if not any(item.status == "PAUSED" for item in summaries.values()):
            await self._retry_deferred_work(
                deferred_windows,
                deferred_runs,
                summaries,
                confirmed_by_run,
                detail_summaries,
                detailed_runs,
            )

        aggregate = self._aggregate_runs(tuple(summaries.values()))
        aggregate_details = (
            self._aggregate_details(tuple(detail_summaries)) if detail_summaries else None
        )
        if aggregate.status == "PAUSED":
            self.paused.emit(aggregate, aggregate_details)
        else:
            if self.action == "incremental":
                # Falhas definitivas/rejeições exigem uma nova leitura explícita do
                # intervalo. Sua cobertura não avançou; um novo ciclo não as pula.
                set_session_status(self.config, active=False)
            if aggregate.status.startswith("COMPLETED"):
                await self._run_catalog_resources()
            self.completed.emit(aggregate, aggregate_details)

    async def _run_main_sweep(self, run_id: str) -> RunSummary:
        """Executa uma rodada finita e deixa falhas recuperáveis para outro momento."""
        with SyncRepository(self.config.db_path) as repository:
            before = repository.get_summary(run_id)
        if self._empty_failed_sweeps >= 3:
            self._outage_waits += 1
            delay = min(
                self.config.continuous_retry_base_seconds
                * 2 ** min(10, self._outage_waits - 1),
                self.config.continuous_retry_max_seconds,
            )
            await self._wait_before_retry(
                delay, reason="três lotes seguidos sem confirmar páginas",
                reopened=before.failed_units + before.pending_units, cycle=self._outage_waits,
            )
            self._empty_failed_sweeps = 0
        with SyncRepository(self.config.db_path) as repository:
            corrected = repository.reclassify_false_period_limit_errors(run_id)
            reopened = repository.retry_recoverable_units(run_id)
        if corrected:
            self.activity.emit(
                f"Corrigido o diagnóstico de {corrected} página(s) da execução."
            )
        if reopened:
            self.activity.emit(
                f"Revisitando {reopened} página(s) temporariamente pendente(s), "
                "sem bloquear os outros lotes."
            )
        # Uma rodada nacional visita cada página no máximo uma vez. O erro fica
        # catalogado e a página volta somente no próximo ciclo do rodízio; assim
        # um único 504 não monopoliza oito tentativas nem impede páginas saudáveis.
        sweep_config = replace(self.config, max_retries=1)
        result = await self._run_main_sync(
            run_id,
            status_updates=True,
            config=sweep_config,
            stop_after_failed_batch=True,
        )
        progressed = result.succeeded_units > before.succeeded_units
        failed = bool(result.failed_units or result.pending_units)
        if progressed:
            self._empty_failed_sweeps = self._outage_waits = 0
        elif failed and result.status != "PAUSED":
            self._empty_failed_sweeps += 1
        return result

    async def _retry_deferred_work(
        self,
        deferred_windows: list[SyncWindow],
        deferred_runs: list[str],
        summaries: dict[str, RunSummary],
        confirmed_by_run: dict[str, int],
        detail_summaries: list[DetailRunSummary],
        detailed_runs: set[str],
    ) -> None:
        """Revisita planejamentos e páginas em rodadas sem inanição."""
        windows = deque(dict.fromkeys(deferred_windows))
        runs = deque(dict.fromkeys(deferred_runs))
        queue: deque[tuple[str, SyncWindow | str]] = deque()
        # Intercala desde a primeira rodada e prioriza páginas já catalogadas.
        while windows or runs:
            if runs:
                queue.append(("run", runs.popleft()))
            if windows:
                queue.append(("window", windows.popleft()))

        cycle = 1
        remaining_in_cycle = len(queue)
        processed_run_ids: set[str] = set()
        scheduled_run_ids = {
            str(value) for kind, value in queue if kind == "run"
        }
        if queue:
            self.activity.emit(
                f"Rodada {cycle} de recuperação: revisitando "
                f"{len(queue)} lote(s) pendente(s)."
            )

        while queue:
            if remaining_in_cycle == 0:
                cycle += 1
                delay = min(
                    self.config.continuous_retry_base_seconds
                    * (2 ** min(10, cycle - 2)),
                    self.config.continuous_retry_max_seconds,
                )
                await self._wait_before_retry(
                    delay,
                    reason="pendências temporárias catalogadas",
                    reopened=len(queue),
                    cycle=cycle,
                )
                remaining_in_cycle = len(queue)
                processed_run_ids.clear()
                self.activity.emit(
                    f"Rodada {cycle} de recuperação: revisitando "
                    f"{len(queue)} lote(s) pendente(s)."
                )

            kind, value = queue.popleft()
            remaining_in_cycle -= 1
            if kind == "window":
                window = value
                if not isinstance(window, SyncWindow):
                    raise TypeError("Item inválido na fila de planejamento.")
                try:
                    plan = await self._plan_full_window(window)
                except PNCPError as exc:
                    queue.append(("window", window))
                    self.activity.emit(
                        f"Planejamento ainda indisponível para "
                        f"{window.data_inicial:%d/%m/%Y} a "
                        f"{window.data_final:%d/%m/%Y}, modalidade "
                        f"{window.modalidade}: {exc}. Mantido no rodízio."
                    )
                    continue
                run_id = plan.run_id
                if run_id in scheduled_run_ids or run_id in processed_run_ids:
                    self.activity.emit(
                        f"A execução {run_id[:8]} já está neste rodízio; "
                        "a duplicata foi ignorada."
                    )
                    continue
                processed_run_ids.add(run_id)
                self.run_id = run_id
                if run_id not in self.run_ids:
                    self.run_ids = (*self.run_ids, run_id)
                summary = await self._run_main_sweep(run_id)
                self._record_recovery_progress(
                    summary, summaries, confirmed_by_run
                )
                if summary.status == "PAUSED":
                    return
                with SyncRepository(self.config.db_path) as repository:
                    recoverable = repository.count_recoverable_failed_units(run_id)
                if recoverable or summary.pending_units:
                    queue.append(("run", run_id))
                    scheduled_run_ids.add(run_id)
                elif summary.status.startswith("COMPLETED"):
                    await self._collect_details_for_run(
                        run_id, detail_summaries, detailed_runs
                    )
                continue

            run_id = str(value)
            scheduled_run_ids.discard(run_id)
            if run_id in processed_run_ids:
                continue
            processed_run_ids.add(run_id)
            summary = await self._run_main_sweep(run_id)
            self._record_recovery_progress(summary, summaries, confirmed_by_run)
            if summary.status == "PAUSED":
                return
            with SyncRepository(self.config.db_path) as repository:
                recoverable = repository.count_recoverable_failed_units(run_id)
            if recoverable or summary.pending_units:
                queue.append(("run", run_id))
                scheduled_run_ids.add(run_id)
            elif summary.status.startswith("COMPLETED"):
                self.activity.emit(
                    f"Pendências da execução {run_id[:8]} concluídas."
                )
                await self._collect_details_for_run(
                    run_id, detail_summaries, detailed_runs
                )

    def _record_recovery_progress(
        self,
        summary: RunSummary,
        summaries: dict[str, RunSummary],
        confirmed_by_run: dict[str, int],
    ) -> None:
        """Atualiza o resumo sem contar novamente páginas já confirmadas."""
        confirmed = summary.succeeded_units + summary.partial_units
        previous = confirmed_by_run.get(summary.run_id, 0)
        self._full_confirmed_pages += max(0, confirmed - previous)
        confirmed_by_run[summary.run_id] = confirmed
        summaries[summary.run_id] = summary
        self._emit_full_progress(summary)

    async def _collect_details_for_run(
        self,
        run_id: str,
        detail_summaries: list[DetailRunSummary],
        detailed_runs: set[str],
    ) -> None:
        """Coleta detalhes uma única vez quando a execução principal é concluída."""
        if not self.include_details or run_id in detailed_runs:
            return
        detail_plan = self._plan_details(run_id)
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
        detailed_runs.add(run_id)

    def _plan_details(self, run_id: str) -> DetailPlanSummary:
        detail_plan = plan_details(
            self.config,
            run_id,
            recent_active_only=self.details_recent_active_only,
        )
        if detail_plan.planned_contracts == 0 and self.details_recent_active_only:
            self.activity.emit(
                "Este lote não possui licitações divulgadas, ainda abertas e publicadas "
                "nos últimos 12 meses; nenhuma consulta de itens foi criada."
            )
        return detail_plan

    async def _run_main_continuously(
        self,
        run_id: str,
    ) -> RunSummary:
        """Repete falhas recuperáveis até concluir ou receber cancelamento do usuário.

        Este é o caminho único para cargas novas e retomadas. Uma falha temporária
        esgota primeiro as tentativas curtas da página, entra em espera progressiva
        e depois reabre apenas unidades cujo diagnóstico mais recente é recuperável.
        """
        consecutive_failures = 0
        previous_done = -1

        with SyncRepository(self.config.db_path) as repository:
            corrected_at_start = repository.reclassify_false_period_limit_errors(run_id)
            reopened_at_start = repository.retry_recoverable_units(run_id)
        if corrected_at_start:
            self.activity.emit(
                f"Corrigido o diagnóstico de {corrected_at_start} página(s) cuja janela "
                "era válida, mas o PNCP respondeu incorretamente sobre o período."
            )
        if reopened_at_start:
            self.activity.emit(
                f"Retomando {reopened_at_start} página(s) que tiveram falha temporária "
                "no PNCP."
            )

        while True:
            summary = await self._run_main_sync(
                run_id,
                status_updates=True,
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
            await self._wait_before_retry(
                delay,
                reason=reason,
                reopened=reopened,
                cycle=consecutive_failures,
            )
            # O controlador conserva o nível entre rodadas; uma página defeituosa
            # não reinicia toda a carga com uma única requisição.

    async def _run_main_sync(
        self,
        run_id: str,
        *,
        status_updates: bool = False,
        config: SyncConfig | None = None,
        stop_after_failed_batch: bool = False,
    ) -> RunSummary:
        effective_config = config or self.config
        status = (
            self.activity.emit
            if status_updates or effective_config.max_concurrent > 1
            else None
        )
        if effective_config.max_concurrent > 1:
            return await run_sync_parallel(
                effective_config,
                run_id,
                concurrency_state=self._concurrency_state,
                stop_after_failed_batch=stop_after_failed_batch,
                progress=self._main_progress,
                activity=self._main_activity,
                status=status,
            )
        return await run_sync(
            effective_config,
            run_id,
            stop_after_failure=stop_after_failed_batch,
            progress=self._main_progress,
            activity=self._main_activity,
            status=status,
        )

    async def _wait_before_retry(
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

    async def _plan_with_retry(
        self,
        window: SyncWindow,
    ) -> Any:
        """Planeja um recorte com tentativas finitas para não bloquear outros lotes."""
        for attempt in range(1, self._PLANNING_ATTEMPTS + 1):
            try:
                return await plan_sync(self.config, window)
            except PNCPError as exc:
                if attempt >= self._PLANNING_ATTEMPTS:
                    raise
                message = str(exc).lower()
                rate_limited = "too many requests" in message or "429" in message
                delay = (
                    60
                    if rate_limited
                    else min(
                        self.config.continuous_retry_base_seconds
                        * (2 ** min(10, max(0, attempt - 1))),
                        self.config.continuous_retry_max_seconds,
                    )
                )
                reason = "limite de requisições HTTP 429" if rate_limited else "falha temporária"
                self.activity.emit(
                    f"PNCP informou {reason}. Aguardando {delay} s antes da tentativa "
                    f"{attempt + 1}/{self._PLANNING_ATTEMPTS}; use Pausar para "
                    "interromper com segurança."
                )
                await asyncio.sleep(delay)

        raise RuntimeError("A estimativa encerrou sem resultado e sem exceção identificada.")

    async def _plan_full_window(self, window: SyncWindow) -> Any:
        """Sonda um lote rapidamente para não bloquear toda a carga nacional."""
        planning_config = replace(
            self.config,
            max_retries=1,
            timeout_seconds=min(30, self.config.timeout_seconds),
        )
        try:
            return await plan_sync(planning_config, window, **self._incremental_scope())
        except PNCPError as exc:
            if self.action == "incremental" and not _is_recoverable(exc):
                raise SourceError(
                    f"Endpoint incremental indisponível ou não autorizado: {exc}"
                ) from exc
            if self.action == "incremental" and (
                "429" in str(exc) or "too many requests" in str(exc).casefold()
            ):
                self.activity.emit(
                    "PNCP limitou as consultas; aguardando 60 s antes do próximo lote."
                )
                await asyncio.sleep(60)
            raise

    def _incremental_scope(self) -> dict[str, str]:
        # Não reutiliza o resultado da sobreposição de um ciclo anterior.
        return (
            {"created_after": self._incremental_created_after}
            if self.action == "incremental" else {}
        )

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

    def _main_progress(self, *args: Any) -> None:
        if not self.run_id:
            return
        if self.action in {"full_sync", "incremental"} and len(args) >= 2:
            inserted = int(getattr(args[1], "inserted", 0))
            if self._full_stored_records is not None:
                self._full_stored_records += inserted
        with SyncRepository(self.config.db_path) as repository:
            summary = repository.get_summary(self.run_id)
            self.progress.emit("contratacoes", summary)
            if self.action in {"full_sync", "incremental"}:
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
        if self._full_stored_records is None:
            with SyncRepository(self.config.db_path) as repository:
                self._full_stored_records = repository.count_contratacoes()
        stored_records = self._full_stored_records
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
                stored_records=stored_records,
                estimated_total_records=self.estimated_total_records,
                records_received=records,
                bytes_received=received,
            )
        )

    def _main_activity(self, work_unit: Any) -> None:
        label = "retificações" if work_unit.resource == UPDATES else "publicações"
        self.activity.emit(
            f"Baixando contratações ({label}) — página {work_unit.page_number} "
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
