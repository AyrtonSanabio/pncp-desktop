from __future__ import annotations

from typing import Any

from pypncp import PNCPClient, PNCPError

from pncp_desktop.models import ContratoLinha, FiltrosConsulta, ResultadoConsulta


class ErroConsulta(RuntimeError):
    def __init__(self, mensagem_usuario: str, detalhe: str = "") -> None:
        super().__init__(mensagem_usuario)
        self.mensagem_usuario = mensagem_usuario
        self.detalhe = detalhe


class ServicoConsultaContratos:
    """Adaptador que impede a interface de depender diretamente dos modelos do pypncp."""

    def __init__(
        self,
        *,
        timeout: int = 20,
        max_retries: int = 1,
        client_factory: Any = PNCPClient,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._client_factory = client_factory

    async def consultar(self, filtros: FiltrosConsulta) -> ResultadoConsulta:
        try:
            async with self._client_factory(
                timeout=self._timeout,
                max_retries=self._max_retries,
            ) as client:
                page = await client.contratos.list(
                    data_inicial=filtros.data_inicial,
                    data_final=filtros.data_final,
                    cnpj_orgao=filtros.cnpj_orgao,
                    pagina=filtros.pagina,
                )
        except PNCPError as exc:
            detalhe = str(exc)
            if "tentativa" in detalhe.lower() or "timeout" in detalhe.lower():
                mensagem = "O PNCP não respondeu dentro do prazo. Tente novamente mais tarde."
            else:
                mensagem = "O PNCP não conseguiu concluir a consulta."
            raise ErroConsulta(mensagem, detalhe) from exc
        except Exception as exc:
            raise ErroConsulta(
                "Não foi possível acessar o PNCP. Verifique sua conexão e tente novamente.",
                str(exc),
            ) from exc

        contratos = tuple(ContratoLinha.from_pypncp(item) for item in page.data)
        return ResultadoConsulta(
            contratos=contratos,
            pagina=page.numero_pagina,
            total_paginas=page.total_paginas,
            total_registros=page.total_registros,
        )
