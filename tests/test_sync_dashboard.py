import sqlite3
from datetime import UTC, datetime

from pncp_desktop.sync_dashboard import read_dashboard


def test_global_items_include_unscheduled_and_failed_contracts(tmp_path):
    path = tmp_path / "test.sqlite3"
    with sqlite3.connect(path) as c:
        c.executescript("""
            CREATE TABLE contratacao(id,numero_controle_pncp,data_publicacao_pncp,
              situacao_compra_id,data_encerramento_proposta);
            CREATE TABLE detail_run(id,created_at);
            CREATE INDEX idx_contratacao_publicacao ON contratacao(data_publicacao_pncp);
            CREATE TABLE detail_work_unit(contratacao_id,detail_run_id,resource,status,
              started_at,finished_at);
            CREATE TABLE work_unit(status,data_inicial,data_final,modalidade,page_number,
              started_at,finished_at);
            CREATE TABLE item_contratacao(id);
            CREATE TABLE app_preference(key,value_json);
            INSERT INTO detail_run VALUES ('old','2026-01-01'),('new','2026-08-01');
            INSERT INTO contratacao VALUES
              (1,'one','2026-08-01',1,'2026-12-01'),
              (2,'two','2026-08-02',1,'2026-12-01'),
              (3,'three','2026-08-03',1,'2026-12-01'),
              (4,'closed','2026-08-03',1,'2026-08-04');
            INSERT INTO detail_work_unit VALUES
              (1,'old','ITEMS','FAILED','2026-01-01',NULL),
              (1,'new','ITEMS','SUCCEEDED','2026-08-01','2026-08-01'),
              (2,'new','ITEMS','RETRY_WAIT','2026-08-01',NULL);
            INSERT INTO work_unit VALUES
              ('SUCCEEDED','2026-08-01','2026-08-02',12,1,NULL,'2026-08-02'),
              ('RETRY_WAIT','2026-08-01','2026-08-02',12,2,NULL,NULL);
        """)
    result = read_dashboard(path, datetime(2026, 9, 8, tzinfo=UTC))
    assert result["items"] == dict(
        total=3, done=1, failed=1, attempted=2, pending_since="2026-08-02"
    )
    assert result["pages"] == {"SUCCEEDED": 1, "RETRY_WAIT": 1}
    assert result["records"] == 4
    assert result["scope_end"] is None


def test_panel_counts_failed_visits_without_claiming_completion(tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pncp_desktop.sync_dashboard import SyncDashboard

    app = QApplication.instance() or QApplication([])
    panel = SyncDashboard(lambda: tmp_path / "unused.sqlite3")
    panel.timer.stop()
    panel.render(
        dict(
            records=1000,
            item_records=200,
            pages={"SUCCEEDED": 90, "FAILED": 10},
            current=[],
            last_success=None,
            current_item=[],
            scope_end="2026-08-28",
            cutoff="2025-09-08",
            reference="2026-09-08T15:00:00+00:00",
            items=dict(total=100, done=30, attempted=35, failed=5, pending_since="2026-08-28"),
        )
    )
    assert panel.fields["Contratações: concluídas / faltam"].text() == "30 / 70"
    assert panel.fields["Contratações visitadas"].text().startswith("35 / 100")
    assert panel.fields["Páginas: baixadas / faltam"].text() == "90 / 10"
    assert panel.bars["items"].value() == 300
    assert "29/08/2026" in panel.coverage.text()
    panel.deleteLater()
    app.sendPostedEvents()
