from datetime import date

from pncp_desktop.exportacao import exportar_contratos_csv
from pncp_desktop.models import ContratoLinha


def test_exporta_csv_compativel_com_excel(tmp_path) -> None:
    contrato = ContratoLinha(
        numero="1/2026",
        orgao="Órgão com acento",
        objeto="Aquisição",
        fornecedor="Fornecedor",
        valor=1234.5,
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fim=date(2026, 12, 31),
        identificador_pncp="controle-1",
    )
    destino = tmp_path / "contratos.csv"

    quantidade = exportar_contratos_csv(destino, [contrato])

    conteudo = destino.read_text(encoding="utf-8-sig")
    assert quantidade == 1
    assert conteudo.startswith("Número;Órgão;Objeto")
    assert "Órgão com acento" in conteudo
    assert "1234,50" in conteudo
    assert destino.read_bytes().startswith(b"\xef\xbb\xbf")
