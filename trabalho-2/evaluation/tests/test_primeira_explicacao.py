"""Testes do pré-teste. A busca MCP real é habilitada separadamente."""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from agent.graph import construir_grafo_explicacao
from agent.mcp import RAIZ, Ferramentas, sessao_mcp
from evaluation import primeira_explicacao as piloto
from evaluation.dataset import carregar_dataset
from knowledge_base import index
from mcp_server.tools.board import validar_lances


class FerramentaFixture:
    def __init__(self, nome, executar):
        self.name = nome
        self.executar = executar

    async def ainvoke(self, chamada):
        retorno = self.executar(**chamada["args"])
        return ToolMessage(content=json.dumps(retorno), tool_call_id=chamada["id"], name=self.name)


@pytest.fixture
def posicao():
    return carregar_dataset()[0]


def test_interrompe_ao_falhar_a_ferramenta_realmente_necessaria(monkeypatch, posicao):
    chamadas = []

    def falha(**_):
        chamadas.append("motor")
        raise NotImplementedError

    @asynccontextmanager
    async def sessao():
        yield [FerramentaFixture("analisar_posicao", falha)]

    def proibido(_):
        pytest.fail("O provedor não deve ser preparado com pré-requisito indisponível.")

    monkeypatch.setattr(piloto, "sessao_mcp", sessao)
    monkeypatch.setattr(piloto, "_config_modelo", proibido)
    saida = asyncio.run(piloto.executar(posicao, argparse.Namespace(executar=True)))
    assert chamadas == ["motor"]
    assert saida["status"] == "bloqueado" and saida["etapa"] == "analisar_posicao"
    assert [r["nome"] for r in saida["ferramentas_preflight"]] == ["analisar_posicao"]


def test_preflight_verifica_antes_depois_e_fonte_sem_llm(monkeypatch, posicao):
    descritas = []

    def descrever(fen):
        descritas.append(fen)
        return {"turno": "white"}

    @asynccontextmanager
    async def sessao():
        yield [
            FerramentaFixture("analisar_posicao", lambda **_: posicao["motor"]),
            FerramentaFixture("descrever_posicao", descrever),
            FerramentaFixture("validar_lances", validar_lances),
            FerramentaFixture("buscar_conceitos", lambda tema, **_: [
                {"id": tema, "texto": "Texto de teste.", "titulo": "Ficha", "arquivo": "ficha.md"},
            ]),
        ]

    def proibido(_):
        pytest.fail("O pré-teste padrão não deve preparar o provedor.")

    monkeypatch.setattr(piloto, "sessao_mcp", sessao)
    monkeypatch.setattr(piloto, "_config_modelo", proibido)
    saida = asyncio.run(piloto.executar(posicao, argparse.Namespace(executar=False)))
    assert saida["status"] == "preflight_ok"
    assert len(descritas) == 2 and descritas[0] == posicao["fen"] and descritas[0] != descritas[1]
    assert saida["fonte_preflight"]["id"] == posicao["tema_esperado"]
    assert "explicacao" not in saida
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert asyncio.run(piloto.executar(posicao, argparse.Namespace(executar=True)))["etapa"] == "llm"


def test_rejeita_variante_com_lance_illegal(posicao):
    motor = {**posicao["motor"], "linha_principal": [posicao["melhor_lance"], "Qz9"]}
    with pytest.raises(ValueError, match="contém lance inválido"):
        piloto._linha_motor(posicao["fen"], motor)


@pytest.mark.skipif(os.getenv("LANCE_TESTE_MCP_RAG") != "1", reason="requer embeddings e MCP real")
def test_rag_real_reconstruido_por_stdio(monkeypatch, tmp_path, posicao):
    monkeypatch.setenv("MCP_URL", "")
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    assert len(index.carregar_trechos(index.PASTA_FICHAS)) == 30
    assert index.indexar() == index.indexar(reconstruir=True) == 30

    async def consultar():
        async with sessao_mcp() as disponiveis:
            cliente = Ferramentas(disponiveis)
            sem_filtro = await cliente.chamar(
                "buscar_conceitos", pergunta="How does a knight fork two pieces at once?",
            )
            assert len(sem_filtro) == 4 and "garfo" in {r["id"] for r in sem_filtro}
            filtrado = await cliente.chamar("buscar_conceitos", pergunta="garfo de cavalo", tema="garfo")
            assert len(filtrado) == 1
            origem = filtrado[0]
            assert (origem["id"], origem["titulo"], origem["tema"], origem["nivel"]) == (
                "garfo", "Garfo", "fork", "iniciante",
            )
            assert origem["arquivo"] == "knowledge_base/garfo.md"
            assert origem["texto"] == index.carregar_trechos(index.PASTA_FICHAS)[origem["trecho_id"]][0]
            por_tag = await cliente.chamar("buscar_conceitos", pergunta="garfo de cavalo", tema="fork")
            assert origem in por_tag and all(ficha["tema"] == "fork" for ficha in por_tag)
            assert await cliente.chamar("buscar_conceitos", pergunta="garfo", tema="tema_sem_ficha") == []

            # Verifica o contrato do contexto real até o prompt. O LLM e a
            # descrição são fixtures somente nesta parte do teste.
            class ModeloFixture:
                async def ainvoke(self, mensagens):
                    dados = json.loads(mensagens[-1].content)
                    arquivo = dados["ficha"]["arquivo"]
                    assert arquivo == f"knowledge_base/{dados['ficha']['id']}.md"
                    texto = dados["ficha"]["texto"]
                    assert texto and RAIZ.joinpath(arquivo).read_text().find(texto) >= 0 and "## Exemplo" not in texto
                    return AIMessage(content=json.dumps({k: v[0] for k, v in dados["frases_permitidas"].items()}))

            ferramentas = Ferramentas([
                *[f for f in disponiveis if f.name != "descrever_posicao"],
                FerramentaFixture("descrever_posicao", lambda fen: {"fen": fen}),
            ])
            estado = await construir_grafo_explicacao(ModeloFixture(), ferramentas).ainvoke({
                "fen": posicao["fen"], "lance_jogado": posicao["lance_jogado"],
                "melhor_lance": posicao["melhor_lance"], "linha_motor": posicao["motor"]["linha_principal"],
            })
            assert estado["validada"] and estado["pronto"] and estado["tentativas"] == 1

    asyncio.run(consultar())
