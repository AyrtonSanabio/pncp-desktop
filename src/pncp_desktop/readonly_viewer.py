"""Servidor HTTP local e somente leitura para compartilhar consultas via túnel.

Ele fica deliberadamente separado da interface Qt: escuta apenas em 127.0.0.1,
abre o SQLite em modo ``ro`` e exige autenticação HTTP Basic antes de revelar
qualquer dado. O túnel (ngrok, Tailscale etc.) deve encaminhar somente essa porta.
"""

from __future__ import annotations

import base64
import hmac
import html
import sqlite3
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _fts_query(value: str) -> str:
    terms = [term.strip('"') for term in value.split() if term.strip('"')]
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


@dataclass(frozen=True, slots=True)
class ViewerCredentials:
    username: str
    password: str

    def valid(self) -> bool:
        return bool(self.username.strip() and len(self.password) >= 16)


class ReadonlyCatalog:
    """Consultas explicitamente permitidas sobre uma conexão SQLite read-only."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(f"Banco não encontrado: {self.path}")
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def stats(self) -> tuple[int, int]:
        with self._connect() as connection:
            contracts = int(connection.execute("SELECT COUNT(*) FROM contratacao").fetchone()[0])
            items = int(connection.execute("SELECT COUNT(*) FROM item_contratacao").fetchone()[0])
        return contracts, items

    def search(self, query: str, limit: int = 50) -> list[dict[str, object]]:
        query = query.strip()
        with self._connect() as connection:
            if not query:
                rows = connection.execute(
                    """
                    SELECT id, numero_controle_pncp, orgao_razao_social, orgao_cnpj,
                           objeto_compra, modalidade_nome, situacao_compra_nome,
                           data_encerramento_proposta, valor_total_estimado
                    FROM contratacao
                    ORDER BY COALESCE(data_publicacao_pncp, data_inclusao) DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                expression = _fts_query(query)
                if not expression:
                    return []
                like = f"%{query}%"
                rows = connection.execute(
                    """
                    WITH encontrados AS (
                        SELECT rowid AS contratacao_id FROM contratacao_fts WHERE contratacao_fts MATCH ?
                        UNION
                        SELECT i.contratacao_id FROM item_contratacao_fts f
                        JOIN item_contratacao i ON i.id = f.rowid WHERE item_contratacao_fts MATCH ?
                        UNION
                        SELECT i.contratacao_id FROM resultado_item r
                        JOIN item_contratacao i ON i.id = r.item_id
                        WHERE r.fornecedor_nome LIKE ? OR r.ni_fornecedor LIKE ?
                    )
                    SELECT DISTINCT c.id, c.numero_controle_pncp, c.orgao_razao_social, c.orgao_cnpj,
                           c.objeto_compra, c.modalidade_nome, c.situacao_compra_nome,
                           c.data_encerramento_proposta, c.valor_total_estimado
                    FROM encontrados e JOIN contratacao c ON c.id = e.contratacao_id
                    ORDER BY COALESCE(c.data_publicacao_pncp, c.data_inclusao) DESC, c.id DESC LIMIT ?
                    """,
                    (expression, expression, like, like, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def detail(self, contract_id: int) -> tuple[dict[str, object], list[dict[str, object]]]:
        with self._connect() as connection:
            contract = connection.execute(
                """SELECT numero_controle_pncp, orgao_razao_social, orgao_cnpj, unidade_nome,
                          municipio_nome, uf_sigla, objeto_compra, modalidade_nome,
                          situacao_compra_nome, data_publicacao_pncp, data_abertura_proposta,
                          data_encerramento_proposta, valor_total_estimado, valor_total_homologado
                   FROM contratacao WHERE id = ?""",
                (contract_id,),
            ).fetchone()
            if contract is None:
                raise LookupError("Contratação não encontrada.")
            items = connection.execute(
                """SELECT numero_item, descricao, quantidade, unidade_medida,
                          valor_unitario_estimado, valor_total, situacao_nome
                   FROM item_contratacao WHERE contratacao_id = ? ORDER BY numero_item LIMIT 500""",
                (contract_id,),
            ).fetchall()
        return dict(contract), [dict(row) for row in items]


def _cell(value: object) -> str:
    text = "Não informado" if value is None or str(value).strip() == "" else str(value)
    return html.escape(text)


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(title)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;max-width:1200px;margin:32px auto;padding:0 16px;color:#153e63}}
input{{width:min(680px,100%);padding:10px}}button{{padding:10px 16px;background:#167cac;color:white;border:0}}
table{{border-collapse:collapse;width:100%;margin-top:20px}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #d7e1ea;vertical-align:top}}
th{{background:#edf5fa}}a{{color:#075f98}}.note{{color:#58708a}}.card{{background:#f5faff;padding:16px;border-radius:8px}}</style></head><body>{body}</body></html>""".encode()


def make_handler(catalog: ReadonlyCatalog, credentials: ViewerCredentials) -> type[BaseHTTPRequestHandler]:
    class ViewerHandler(BaseHTTPRequestHandler):
        server_version = "PNCPReadonly/1.0"

        def log_message(self, _format: str, *_args: object) -> None:
            # Não registra termos de busca ou cabeçalhos de autorização no terminal.
            return

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            expected = base64.b64encode(f"{credentials.username}:{credentials.password}".encode()).decode()
            return hmac.compare_digest(header, f"Basic {expected}")

        def _send(self, content: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("WWW-Authenticate", 'Basic realm="Consulta PNCP"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/health":
                    self._send(b"ok")
                    return
                if parsed.path == "/":
                    values = parse_qs(parsed.query)
                    query = values.get("q", [""])[0][:200]
                    contracts, items = catalog.stats()
                    rows = catalog.search(query)
                    table = "".join(
                        "<tr>"
                        f"<td><a href='/contratacao/{int(row['id'])}'>{_cell(row['numero_controle_pncp'])}</a></td>"
                        f"<td>{_cell(row['orgao_razao_social'])}</td><td>{_cell(row['objeto_compra'])}</td>"
                        f"<td>{_cell(row['modalidade_nome'])}</td><td>{_cell(row['valor_total_estimado'])}</td></tr>"
                        for row in rows
                    ) or "<tr><td colspan='5'>Nenhum resultado.</td></tr>"
                    content = _page(
                        "Consulta PNCP — leitura",
                        f"<h1>Consulta PNCP</h1><p class='note'>Acesso somente leitura. {contracts:,} contratações e {items:,} itens no banco.</p>"
                        f"<form><input name='q' value='{html.escape(query)}' placeholder='Objeto, fornecedor, CNPJ ou identificador PNCP'> <button>Pesquisar</button></form>"
                        "<table><thead><tr><th>Identificador PNCP</th><th>Órgão</th><th>Objeto</th><th>Modalidade</th><th>Valor estimado</th></tr></thead>"
                        f"<tbody>{table}</tbody></table>",
                    )
                    self._send(content)
                    return
                if parsed.path.startswith("/contratacao/"):
                    contract_id = int(parsed.path.rsplit("/", 1)[-1])
                    contract, items = catalog.detail(contract_id)
                    fields = "".join(
                        f"<tr><th>{html.escape(key.replace('_', ' ').title())}</th><td>{_cell(value)}</td></tr>"
                        for key, value in contract.items()
                    )
                    item_rows = "".join(
                        f"<tr><td>{_cell(item['numero_item'])}</td><td>{_cell(item['descricao'])}</td>"
                        f"<td>{_cell(item['quantidade'])} {_cell(item['unidade_medida'])}</td><td>{_cell(item['valor_total'])}</td></tr>"
                        for item in items
                    ) or "<tr><td colspan='4'>Itens não sincronizados para esta contratação.</td></tr>"
                    self._send(_page("Detalhe — Consulta PNCP", f"<p><a href='/'>← Voltar</a></p><h1>Detalhe da contratação</h1><table>{fields}</table><h2>Itens</h2><table><thead><tr><th>Nº</th><th>Descrição</th><th>Quantidade</th><th>Valor total</th></tr></thead><tbody>{item_rows}</tbody></table>"))
                    return
                self._send(_page("Não encontrado", "<h1>Página não encontrada</h1>"), HTTPStatus.NOT_FOUND)
            except (LookupError, ValueError):
                self._send(_page("Não encontrado", "<h1>Contratação não encontrada</h1>"), HTTPStatus.NOT_FOUND)
            except sqlite3.Error:
                self._send(_page("Indisponível", "<h1>Banco temporariamente indisponível</h1>"), HTTPStatus.SERVICE_UNAVAILABLE)

    return ViewerHandler


def serve(*, database: Path, port: int, credentials: ViewerCredentials) -> None:
    if not credentials.valid():
        raise ValueError("A senha do visualizador deve ter pelo menos 16 caracteres.")
    catalog = ReadonlyCatalog(database)
    catalog.stats()  # valida o caminho e o modo somente leitura antes de escutar a porta.
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(catalog, credentials))
    print(f"Visualizador somente leitura em http://127.0.0.1:{port}", flush=True)
    print("Use Ctrl+C para encerrar. Não exponha o arquivo SQLite nem use 0.0.0.0.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
