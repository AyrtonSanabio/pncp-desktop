from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SyncConfig:
    """Configuração segura da primeira fatia do sincronizador."""

    db_path: Path
    base_url: str = "https://pncp.gov.br/api/consulta/v1"
    details_base_url: str = "https://pncp.gov.br/api/pncp/v1"
    timeout_seconds: int = 30
    max_retries: int = 3
    max_concurrent: int = 1
    max_window_days: int = 31
    lease_seconds: int = 300
    max_response_bytes: int = 25 * 1024 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path).expanduser().resolve())
        if not self.base_url.startswith("https://"):
            raise ValueError("A fonte do PNCP deve usar HTTPS.")
        if not self.details_base_url.startswith("https://"):
            raise ValueError("A fonte de detalhes do PNCP deve usar HTTPS.")
        if self.timeout_seconds < 1:
            raise ValueError("O timeout deve ser positivo.")
        if self.max_retries < 1:
            raise ValueError("O número de tentativas deve ser positivo.")
        if self.max_concurrent < 1 or self.max_concurrent > 4:
            raise ValueError("A concorrência deve ficar entre 1 e 4.")
        if self.max_window_days < 1:
            raise ValueError("A janela máxima deve ser positiva.")
        if self.lease_seconds < 30:
            raise ValueError("A concessão de trabalho deve durar pelo menos 30 segundos.")
        if self.max_response_bytes < 1024 or self.max_response_bytes > 100 * 1024 * 1024:
            raise ValueError("O limite de resposta deve ficar entre 1 KB e 100 MB.")

    def ensure_storage_directory(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
