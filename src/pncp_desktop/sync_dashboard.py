"""Painel global: somente contagens persistidas, sem projeção de registros."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from pncp_sync.persistence.detail_repositories import _pncp_timestamp, _recent_active_selection


def read_dashboard(path: Path, reference: datetime | None = None, cancelled=None) -> dict:
    reference = reference or datetime.now(UTC)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as c:
        c.row_factory = sqlite3.Row
        deadline = time.monotonic() + 120
        c.set_progress_handler(
            lambda: int(time.monotonic() > deadline or bool(cancelled and cancelled())), 10000
        )
        c.create_function("pncp_timestamp", 1, _pncp_timestamp)
        c.execute("BEGIN")  # Todas as contagens pertencem ao mesmo snapshot.
        predicate, bounds = _recent_active_selection(reference)
        eligible = dict(
            c.execute(
                f"SELECT id,data_publicacao_pncp FROM contratacao "
                f"INDEXED BY idx_contratacao_publicacao WHERE {predicate}",
                bounds,
            )
        )
        states = {}
        for row in c.execute("""
            SELECT w.contratacao_id,w.detail_run_id,w.status,w.started_at,w.finished_at
            FROM detail_work_unit w JOIN detail_run r ON r.id=w.detail_run_id
            WHERE w.resource='ITEMS' ORDER BY r.created_at DESC,r.id DESC
        """):
            identifier, run_id, status, started, finished = row
            if identifier not in eligible:
                continue
            state = states.setdefault(identifier, [run_id, True, False, False])
            if state[0] != run_id:
                continue
            state[1] = state[1] and status == "SUCCEEDED"
            state[2] = state[2] or status in ("FAILED", "RETRY_WAIT", "PARTIAL")
            state[3] = state[3] or bool(started or finished)
        pending = [
            day
            for identifier, day in eligible.items()
            if identifier not in states or not states[identifier][1]
        ]
        result = {
            "items": {
                "total": len(eligible),
                "done": sum(s[1] for s in states.values()),
                "failed": sum(s[2] for s in states.values()),
                "attempted": sum(s[3] for s in states.values()),
                "pending_since": min(pending) if pending else None,
            }
        }
        result["records"] = c.execute("SELECT COUNT(*) FROM contratacao").fetchone()[0]
        result["item_records"] = c.execute("SELECT COUNT(*) FROM item_contratacao").fetchone()[0]
        result["pages"] = dict(c.execute("SELECT status,COUNT(*) FROM work_unit GROUP BY status"))
        result["current"] = [
            dict(r)
            for r in c.execute("""
            SELECT data_inicial,data_final,modalidade,page_number FROM work_unit
            WHERE status='RUNNING' ORDER BY started_at DESC LIMIT 8
        """)
        ]
        result["current_item"] = [
            r[0]
            for r in c.execute("""
            SELECT DISTINCT p.numero_controle_pncp FROM detail_work_unit w
            JOIN contratacao p ON p.id=w.contratacao_id WHERE w.status='RUNNING'
        """)
        ]
        result["last_success"] = c.execute(
            "SELECT MAX(finished_at) FROM work_unit WHERE status='SUCCEEDED'"
        ).fetchone()[0]
        row = c.execute(
            "SELECT value_json FROM app_preference WHERE key='sync.full_session.v1'"
        ).fetchone()
        result["scope_end"] = json.loads(row[0]).get("scope_end") if row else None
        result["reference"] = reference.isoformat()
        result["cutoff"] = bounds[0]
        return result


class DashboardReader(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            self.ready.emit(read_dashboard(self.path, cancelled=self.isInterruptionRequested))
        except Exception as exc:
            self.failed.emit(f"Não foi possível atualizar os contadores: {exc}")


class SyncDashboard(QFrame):
    def __init__(self, path_provider, parent=None):
        super().__init__(parent)
        self.path_provider = path_provider
        self.reader = None
        root = QVBoxLayout(self)
        self.status = QLabel("Lendo o banco…")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        columns = QGridLayout()
        root.addLayout(columns)
        self.fields = {}
        self.bars = {}
        for col, (key, title, labels) in enumerate(
            (
                (
                    "main",
                    "Contratações",
                    (
                        "Registros no banco",
                        "Páginas: baixadas / faltam",
                        "Páginas com falha ou retry",
                        "Lote em download",
                        "Última página salva",
                    ),
                ),
                (
                    "items",
                    "Itens de licitações vigentes — últimos 365 dias",
                    (
                        "Itens no banco",
                        "Contratações: concluídas / faltam",
                        "Contratações visitadas",
                        "Contratações com falhas",
                        "Contratação em download",
                    ),
                ),
            )
        ):
            card = QFrame(objectName="cartao")
            layout = QVBoxLayout(card)
            heading = QLabel(title)
            heading.setStyleSheet("font-size: 15px; font-weight: 700;")
            heading.setWordWrap(True)
            layout.addWidget(heading)
            for label in labels:
                text = QLabel(label)
                text.setObjectName("muted")
                value = QLabel("Lendo…")
                value.setWordWrap(True)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value.setStyleSheet("font-size: 14px; font-weight: 600;")
                layout.addWidget(text)
                layout.addWidget(value)
                self.fields[label] = value
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(0)
            self.bars[key] = bar
            layout.addWidget(bar)
            layout.addStretch()
            columns.addWidget(card, 0, col)
            columns.setColumnStretch(col, 1)
        self.coverage = QLabel("")
        self.coverage.setWordWrap(True)
        root.addWidget(self.coverage)
        self.refresh_button = QPushButton("Atualizar contadores")
        self.refresh_button.clicked.connect(self.refresh)
        root.addWidget(self.refresh_button)
        self.timer = QTimer(self)
        self.timer.setInterval(120000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        if self.reader is not None and self.reader.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.reader = DashboardReader(self.path_provider(), self)
        self.reader.ready.connect(self.render)
        self.reader.failed.connect(self.status.setText)
        self.reader.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self.reader.finished.connect(self.reader.deleteLater)
        self.reader.finished.connect(self._finished)
        self.reader.start()

    def _finished(self):
        self.reader = None

    def render(self, data):
        def n(value):
            return f"{value:,}".replace(",", ".")

        fields = self.fields
        pages = data["pages"]
        done = pages.get("SUCCEEDED", 0)
        total = sum(pages.values())
        fields["Registros no banco"].setText(n(data["records"]))
        fields["Páginas: baixadas / faltam"].setText(f"{n(done)} / {n(total - done)}")
        fields["Páginas com falha ou retry"].setText(
            n(pages.get("FAILED", 0) + pages.get("RETRY_WAIT", 0) + pages.get("PARTIAL", 0))
        )
        current = data["current"]

        def fmt(value):
            return datetime.fromisoformat(value).strftime("%d/%m/%Y")

        fields["Lote em download"].setText(
            "\n".join(
                dict.fromkeys(
                    f"{fmt(r['data_inicial'])} a {fmt(r['data_final'])}"
                    f" • modalidade {r['modalidade']}"
                    for r in current
                )
            )
            or "Sem página em execução neste instante"
        )
        last = data["last_success"]
        fields["Última página salva"].setText(
            datetime.fromisoformat(last).astimezone().strftime("%d/%m/%Y %H:%M:%S")
            if last
            else "Nenhuma"
        )
        items = data["items"]
        fields["Itens no banco"].setText(n(data["item_records"]))
        fields["Contratações: concluídas / faltam"].setText(
            f"{n(items['done'])} / {n(items['total'] - items['done'])}"
        )
        fields["Contratações visitadas"].setText(
            f"{n(items['attempted'])} / {n(items['total'])} elegíveis no banco"
        )
        fields["Contratações com falhas"].setText(n(items["failed"]))
        fields["Contratação em download"].setText(
            "\n".join(data["current_item"]) or "Sem coleta de itens neste instante"
        )
        for key, value, count in (("main", done, total), ("items", items["done"], items["total"])):
            self.bars[key].setValue(round(value / count * 1000) if count else 0)
            self.bars[key].setFormat(
                f"{value / count:.1%} concluídas" if count else "Nenhuma planejada"
            )
        end = data["scope_end"]
        coverage = (
            f"Itens: elegíveis conhecidos desde {fmt(data['cutoff'])}, ainda abertos hoje. "
            "Falhas estão incluídas em ‘faltam’."
        )
        if items.get("pending_since"):
            coverage += f" Itens pendentes em publicações desde {fmt(items['pending_since'])}."
        if end:
            after = (datetime.fromisoformat(end) + timedelta(days=1)).strftime("%d/%m/%Y")
            coverage += (
                f" Histórico planejado até {fmt(end)}; conferir atualização a partir de {after}."
                " As pendências anteriores continuam nos contadores."
            )
        self.coverage.setText(coverage)
        self.status.setText(
            "Contadores globais do banco • atualizado às "
            + datetime.fromisoformat(data["reference"]).astimezone().strftime("%H:%M:%S")
            + " • atualização a cada 2 min • páginas conhecidas, sem projeção"
        )
