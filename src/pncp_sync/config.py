from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SyncConfig:
    """Configuração segura da primeira fatia do sincronizador."""

    db_path: Path
    base_url: str = "https://pncp.gov.br/api/consulta/v1"
    details_base_url: str = "https://pncp.gov.br/api/pncp/v1"
    # O PNCP apresenta picos reais de latencia. O limite maior evita falsos erros.
    # Cada rodada curta tenta a mesma pagina varias vezes; a carga completa reabre
    # falhas recuperaveis depois de uma espera cancelavel ate o usuario pausar.
    timeout_seconds: int = 90
    max_retries: int = 8
    max_concurrent: int = 1
    publication_page_size: int = 50
    max_window_days: int = 31
    lease_seconds: int = 300
    max_response_bytes: int = 25 * 1024 * 1024
    continuous_retry_base_seconds: int = 60
    continuous_retry_max_seconds: int = 15 * 60

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
        if not 1 <= self.publication_page_size <= 500:
            raise ValueError("O tamanho da página deve ficar entre 1 e 500.")
        if self.max_window_days < 1:
            raise ValueError("A janela máxima deve ser positiva.")
        if self.lease_seconds < 30:
            raise ValueError("A concessão de trabalho deve durar pelo menos 30 segundos.")
        if self.max_response_bytes < 1024 or self.max_response_bytes > 100 * 1024 * 1024:
            raise ValueError("O limite de resposta deve ficar entre 1 KB e 100 MB.")
        if self.continuous_retry_base_seconds < 1:
            raise ValueError("A espera inicial da carga contínua deve ser positiva.")
        if self.continuous_retry_max_seconds < self.continuous_retry_base_seconds:
            raise ValueError("A espera máxima deve ser maior ou igual à espera inicial.")

    def ensure_storage_directory(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
