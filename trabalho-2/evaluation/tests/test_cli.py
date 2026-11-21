"""Exercita o executor com fixtures em uma pasta temporária."""

from contextlib import asynccontextmanager
import csv
import json
from random import Random
import sys

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from agent import mcp
from evaluation import dataset, report, run_eval
from mcp_server.tools.board import validar_lances


def invocar(monkeypatch, *argumentos):
    monkeypatch.setattr(sys, "argv", ["evaluation.run_eval", *map(str, argumentos)])
    run_eval.main()


def test_padrao_so_valida_e_planeja(tmp_path, monkeypatch, capsys):
    def proibido(*_):
        pytest.fail("Planejar a avaliação não deve preparar um cliente LLM.")

    monkeypatch.setattr(run_eval, "_config_modelo", proibido)
    pasta = tmp_path / "planejamento"
    invocar(monkeypatch, "--resultados", pasta, "--versoes", "A", "B", "C")
    assert f"{len(dataset.carregar_dataset())} posições validadas" in capsys.readouterr().out
    assert not pasta.exists()
    with pytest.raises(SystemExit, match="2"):
        invocar(monkeypatch, "--resultados", pasta, "--limite", "100")
    assert not pasta.exists()


def test_piloto_abc_retomavel_com_grafo_existente(tmp_path, monkeypatch):
    itens = dataset.carregar_dataset()[:3]
    amostra = tmp_path / "piloto.jsonl"
    dataset.escrever_jsonl(amostra, itens)
    por_fen = {x["fen"]: x for x in itens}

    class ModeloFixture:
        chamadas = 0

        async def ainvoke(self, mensagens):
            self.chamadas += 1
            dados = json.loads(mensagens[-1].content)
            if "temas_permitidos" in dados:
                texto = "garfo"
            elif "fatos" in dados:
                texto = json.dumps({
                    "aconteceu": "A jogada mudou a posição",
                    "motivo": "É preciso comparar as alternativas",
                    "licao": "Confira as ameaças antes de jogar",
                }, ensure_ascii=False)
            else:
                caso = por_fen[dados["fen"]]
                texto = json.dumps({
                    "explicacao": "Compare as alternativas.",
                    "melhor_lance": caso["melhor_lance"],
                    "tema": caso["tema_esperado"],
                }, ensure_ascii=False)
            return AIMessage(content=texto)

    class FerramentaFixture:
        def __init__(self, nome, executar):
            self.name, self.executar = nome, executar

        async def ainvoke(self, chamada):
            dados = self.executar(**chamada["args"])
            return ToolMessage(content=json.dumps(dados), tool_call_id=chamada["id"], name=self.name)

    @asynccontextmanager
    async def sessao():
        yield [
            FerramentaFixture("descrever_posicao", lambda fen: {"fen": fen}),
            FerramentaFixture("validar_lances", validar_lances),
            FerramentaFixture("buscar_conceitos", lambda tema, **_: [{
                "id": tema, "titulo": "Fixture", "texto": "Contexto de teste.", "arquivo": "fixture.md",
            }]),
        ]

    modelo = ModeloFixture()
    monkeypatch.setattr(mcp, "sessao_mcp", sessao)
    monkeypatch.setattr(run_eval, "_config_modelo", lambda _: ("fixture", "local", modelo, None, None))
    # A exportação Matplotlib real é coberta por test_report.py.
    monkeypatch.setattr(report, "_grafico", lambda *_: None)
    pasta = tmp_path / "resultados"
    argumentos = ("--resultados", pasta, "--dataset", amostra)
    invocar(monkeypatch, *argumentos, "--limite", "2", "--versoes", "A")
    assert modelo.chamadas == 2
    invocar(monkeypatch, *argumentos, "--limite", "2", "--versoes", "A", "B", "C")
    assert modelo.chamadas == 8

    arquivo = pasta / "checkpoint.jsonl"
    checkpoint = run_eval.ler_checkpoint(arquivo)
    selecionados = Random(dataset.SEMENTE).sample(range(len(itens)), 2)
    assert set(checkpoint) == {(itens[i]["id"], v) for i in selecionados for v in "ABC"}
    assert all(r["status"] == "ok" for r in checkpoint.values())
    assert all(r["validada_agente"] for r in checkpoint.values() if r["versao"] == "C")
    assert all(r["tokens_total"] is None and r["custo_usd"] is None for r in checkpoint.values())
    original = arquivo.read_bytes()
    invocar(monkeypatch, *argumentos, "--somente-relatorio")
    assert arquivo.read_bytes() == original and modelo.chamadas == 8
    with (pasta / "por_posicao.csv").open() as arquivo:
        assert len(list(csv.DictReader(arquivo))) == 6
    with (pasta / "amostra_cega.csv").open() as arquivo:
        assert len(list(csv.DictReader(arquivo))) == 6


def test_escopo_ragas_exige_opcao_explicita(monkeypatch):
    with pytest.raises(SystemExit, match="2"):
        invocar(monkeypatch, "--ragas", "--ragas-model", "fixture")
    with pytest.raises(SystemExit, match="2"):
        invocar(monkeypatch, "--somente-relatorio", "--ragas-completo")
