from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class SyncWindow:
    data_inicial: date
    data_final: date
    modalidade: int

    def validate(self, *, max_days: int) -> None:
        if self.data_inicial > self.data_final:
            raise ValueError("A data inicial não pode ser posterior à data final.")
        days = (self.data_final - self.data_inicial).days + 1
        if days > max_days:
            raise ValueError(f"A janela pode ter no máximo {max_days} dias nesta fase.")
        if self.modalidade < 1:
            raise ValueError("O código da modalidade deve ser positivo.")

    @property
    def key(self) -> str:
        return f"{self.data_inicial.isoformat()}:{self.data_final.isoformat()}:{self.modalidade}"


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


@dataclass(frozen=True, slots=True)
class BatchPlanSummary:
    plans: tuple[PlanSummary, ...]

    @property
    def run_id(self) -> str:
        return self.plans[0].run_id if self.plans else ""

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(plan.run_id for plan in self.plans)

    @property
    def total_pages(self) -> int:
        return sum(plan.total_pages for plan in self.plans)

    @property
    def total_records(self) -> int:
        return sum(plan.total_records for plan in self.plans)

    @property
    def first_page_records(self) -> int:
        return sum(plan.first_page_records for plan in self.plans)

    @property
    def first_page_bytes(self) -> int:
        return sum(plan.first_page_bytes for plan in self.plans)

    @property
    def estimated_download_bytes(self) -> int:
        return sum(plan.estimated_download_bytes for plan in self.plans)

    @property
    def estimated_database_bytes(self) -> int:
        return sum(plan.estimated_database_bytes for plan in self.plans)

    @property
    def free_disk_bytes(self) -> int:
        return min((plan.free_disk_bytes for plan in self.plans), default=0)

    @property
    def unmodeled_fields(self) -> tuple[str, ...]:
        return tuple(sorted({field for plan in self.plans for field in plan.unmodeled_fields}))

    @property
    def first_page_latency_ms(self) -> float:
        return sum(plan.first_page_latency_ms for plan in self.plans)

    @property
    def remaining_main_requests(self) -> int:
        return sum(plan.remaining_main_requests for plan in self.plans)

    @property
    def estimated_main_seconds(self) -> float:
        return sum(plan.estimated_main_seconds for plan in self.plans)

    @property
    def minimum_detail_requests(self) -> int:
        return sum(plan.minimum_detail_requests for plan in self.plans)


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
