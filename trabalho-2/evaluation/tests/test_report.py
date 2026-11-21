import csv

import pytest

from evaluation import dataset, metrics, report


def test_relatorio_vazio_e_amostra_cega(tmp_path):
    pytest.importorskip("matplotlib")
    exemplo = dataset.carregar_dataset()[0]
    report.salvar_resultados(tmp_path, [exemplo], [], {"semente_amostra": 10})
    assert "Avaliação incompleta" in (tmp_path / "relatorio.md").read_text()
    assert (tmp_path / "comparacao.png").stat().st_size > 0
    with (tmp_path / "metricas.csv").open() as arquivo:
        assert all(row["invalidos_pct"] == "" for row in csv.DictReader(arquivo))
    linhas = []
    for v in metrics.VERSOES:
        linhas.append({"id": exemplo["id"], "fen": exemplo["fen"], "lance_jogado": exemplo["lance_jogado"],
                       "texto": "Texto da resposta.", "versao": v, "status": "ok", "avaliavel": True,
                       "tem_lance_invalido": False, "melhor_correto": True, "tema_correto": True, "segundos": 1.0})
    report.salvar_resultados(tmp_path, [exemplo], linhas, {"semente_amostra": 10})
    with (tmp_path / "amostra_cega.csv").open() as arquivo:
        amostra = list(csv.DictReader(arquivo))
    assert len(amostra) == 3 and all("versao" not in row for row in amostra)
    notas = tmp_path / "notas.csv"
    report._csv(notas, [{"avaliador": "avaliador-1", "codigo": amostra[0]["codigo"], "nota": 4}],
                ("avaliador", "codigo", "nota"))
    report.salvar_resultados(tmp_path, [exemplo], linhas, {"semente_amostra": 10}, notas)
    with (tmp_path / "metricas.csv").open() as arquivo:
        assert sum(int(row["humana_n"]) for row in csv.DictReader(arquivo)) == 1
