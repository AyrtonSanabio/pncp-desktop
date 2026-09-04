from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

PUBLICATIONS = "contratacoes_publicacao"
NEW_PUBLICATIONS = "contratacoes_publicacao_incremental"
UPDATES = "contratacoes_atualizacao"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class SyncWindow:
    data_inicial: date
    data_final: date
    modalidade: int
    resource: str = PUBLICATIONS

    def validate(self, *, max_days: int) -> None:
        if self.resource not in {PUBLICATIONS, NEW_PUBLICATIONS, UPDATES}:
            raise ValueError("Recurso de sincronização desconhecido.")
        if self.data_inicial > self.data_final:
            raise ValueError("A data inicial não pode ser posterior à data final.")
        days = (self.data_final - self.data_inicial).days + 1
        if days > max_days:
            raise ValueError(f"A janela pode ter no máximo {max_days} dias nesta fase.")
        if self.modalidade < 1:
            raise ValueError("O código da modalidade deve ser positivo.")

    @property
    def key(self) -> str:
        return (
            f"{self.resource}:{self.data_inicial.isoformat()}:"
            f"{self.data_final.isoformat()}:{self.modalidade}"
        )

    @property
    def endpoint(self) -> str:
        if self.resource == UPDATES:
            return "/contratacoes/atualizacao"
        return "/contratacoes/publicacao"


@dataclass(frozen=True, slots=True)
class FullSyncProgress:
    """Progresso global conhecido da carga completa.

    O número total de páginas futuras só é conhecido depois que cada janela é
    planejada. A barra principal usa contratos únicos armazenados sobre o total
    projetado pela amostra, deixando a natureza estimada explícita. Lotes e
    páginas continuam disponíveis como métricas exatas separadas.
    """

    total_windows: int
    completed_windows: int
    current_window_index: int | None = None
    current_window: SyncWindow | None = None
    current_pages_done: int = 0
    current_pages_total: int = 0
    current_failed_pages: int = 0
    confirmed_pages: int = 0
    estimated_total_pages: int | None = None
    stored_records: int = 0
    estimated_total_records: int | None = None
    records_received: int = 0
    bytes_received: int = 0

    @property
    def remaining_windows(self) -> int:
        return max(0, self.total_windows - self.completed_windows)

    @property
    def current_pages_remaining(self) -> int:
        return max(0, self.current_pages_total - self.current_pages_done)

    @property
    def estimated_pages_remaining(self) -> int | None:
        if self.estimated_total_pages is None:
            return None
        return max(0, self.estimated_total_pages - self.confirmed_pages)

    @property
    def completed_equivalent_windows(self) -> float:
        fraction = 0.0
        if (
            self.current_pages_total > 0
            and self.current_window_index is not None
            and self.current_window_index > self.completed_windows
        ):
            fraction = min(1.0, self.current_pages_done / self.current_pages_total)
        return min(float(self.total_windows), self.completed_windows + fraction)

    @property
    def window_percentage(self) -> float:
        if self.total_windows <= 0:
            return 0.0
        return self.completed_equivalent_windows / self.total_windows * 100.0

    @property
    def record_percentage(self) -> float | None:
        if self.estimated_total_records is None or self.estimated_total_records <= 0:
            return None
        return self.stored_records / self.estimated_total_records * 100.0

    @property
    def estimated_records_remaining(self) -> int | None:
        if self.estimated_total_records is None:
            return None
        return max(0, self.estimated_total_records - self.stored_records)


@dataclass(frozen=True, slots=True)
class CapturedResponse:
    requested_at: str
    responded_at: str
    status_code: int
    url: str
    headers: dict[str, str]
    content: bytes
    latency_ms: float


@dataclass(frozen=True, slots=True)
class SourcePage:
    page_number: int
    total_pages: int
    total_records: int
    remaining_pages: int
    records: tuple[dict[str, Any], ...]
    request_params: dict[str, Any]
    response: CapturedResponse
    unmodeled_fields: tuple[str, ...] = ()

    @property
    def record_count(self) -> int:
        return len(self.records)


@dataclass(frozen=True, slots=True)
class PurchaseRef:
    contratacao_id: int
    numero_controle_pncp: str
    orgao_cnpj: str
    ano_compra: int
    sequencial_compra: int

    def validate(self) -> None:
        if self.contratacao_id < 1:
            raise ValueError("A contratação local deve ser positiva.")
        if not self.orgao_cnpj.isdigit() or len(self.orgao_cnpj) != 14:
            raise ValueError("O CNPJ do órgão deve possuir 14 dígitos.")
        if self.ano_compra < 2021:
            raise ValueError("O ano da contratação é inválido para o PNCP.")
        if self.sequencial_compra < 1:
            raise ValueError("O sequencial da contratação deve ser positivo.")


@dataclass(frozen=True, slots=True)
class DetailPage:
    resource: str
    page_number: int
    page_size: int
    records: tuple[dict[str, Any], ...]
    request_params: dict[str, Any]
    response: CapturedResponse
    model_validation_errors: tuple[str, ...] = ()
    unmodeled_fields: tuple[str, ...] = ()

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def may_have_next_page(self) -> bool:
        return self.resource == "ITEMS" and self.record_count == self.page_size


@dataclass(frozen=True, slots=True)
class WorkUnit:
    id: int
    run_id: str
    resource: str
    data_inicial: date
    data_final: date
    modalidade: int
    page_number: int
    page_size: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class DetailWorkUnit:
    id: int
    detail_run_id: str
    resource: str
    purchase: PurchaseRef
    item_number: int
    page_number: int
    page_size: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class DetailPlanSummary:
    detail_run_id: str
    source_run_id: str
    planned_contracts: int
    planned_item_requests: int
    page_size: int


@dataclass(frozen=True, slots=True)
class DetailRunSummary:
    detail_run_id: str
    status: str
    planned_units: int
    succeeded_units: int
    partial_units: int
    pending_units: int
    failed_units: int
    item_records: int
    result_records: int
    inserted_items: int
    updated_items: int
    unchanged_items: int
    inserted_results: int
    updated_results: int
    unchanged_results: int
    rejected_records: int
    bytes_received: int


@dataclass(frozen=True, slots=True)
class PlanSummary:
    run_id: str
    total_pages: int
    total_records: int
    first_page_records: int
    first_page_bytes: int
    estimated_download_bytes: int
    estimated_database_bytes: int
    free_disk_bytes: int
    unmodeled_fields: tuple[str, ...]
    first_page_latency_ms: float
    remaining_main_requests: int
    estimated_main_seconds: float
    minimum_detail_requests: int
    reused: bool = False


@dataclass(frozen=True, slots=True)
class BatchPlanSummary:
    plans: tuple[PlanSummary, ...]
    population_windows: int | None = None

    @property
    def _scale(self) -> float:
        if not self.plans or self.population_windows is None:
            return 1.0
        return max(1.0, self.population_windows / len(self.plans))

    @property
    def is_approximate(self) -> bool:
        return self.population_windows is not None and self.population_windows > len(self.plans)

    @property
    def sample_size(self) -> int:
        return len(self.plans)

    @property
    def run_id(self) -> str:
        return self.plans[0].run_id if self.plans else ""

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(plan.run_id for plan in self.plans)

    @property
    def total_pages(self) -> int:
        return round(sum(plan.total_pages for plan in self.plans) * self._scale)

    @property
    def total_records(self) -> int:
        return round(sum(plan.total_records for plan in self.plans) * self._scale)

    @property
    def first_page_records(self) -> int:
        return sum(plan.first_page_records for plan in self.plans)

    @property
    def first_page_bytes(self) -> int:
        return sum(plan.first_page_bytes for plan in self.plans)

    @property
    def estimated_download_bytes(self) -> int:
        return round(sum(plan.estimated_download_bytes for plan in self.plans) * self._scale)

    @property
    def estimated_database_bytes(self) -> int:
        return round(sum(plan.estimated_database_bytes for plan in self.plans) * self._scale)

    @property
    def free_disk_bytes(self) -> int:
        return min((plan.free_disk_bytes for plan in self.plans), default=0)

    @property
    def unmodeled_fields(self) -> tuple[str, ...]:
        return tuple(sorted({field for plan in self.plans for field in plan.unmodeled_fields}))

    @property
    def first_page_latency_ms(self) -> float:
        if not self.plans:
            return 0.0
        return sum(plan.first_page_latency_ms for plan in self.plans) / len(self.plans)

    @property
    def remaining_main_requests(self) -> int:
        return round(sum(plan.remaining_main_requests for plan in self.plans) * self._scale)

    @property
    def estimated_main_seconds(self) -> float:
        return sum(plan.estimated_main_seconds for plan in self.plans) * self._scale

    @property
    def minimum_detail_requests(self) -> int:
        return round(sum(plan.minimum_detail_requests for plan in self.plans) * self._scale)

    @property
    def reused_plans(self) -> int:
        return sum(1 for plan in self.plans if plan.reused)


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    status: str
    planned_units: int
    succeeded_units: int
    partial_units: int
    pending_units: int
    failed_units: int
    records_received: int
    records_inserted: int
    records_updated: int
    records_unchanged: int
    records_rejected: int
    bytes_received: int
