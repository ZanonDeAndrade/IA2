"""Testes de infraestrutura. Respostas de teste são descartadas no tmp_path."""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import json

import chess
from langchain_core.messages import AIMessage, ToolMessage
import pytest

from agent import mcp
from evaluation import dataset, metrics, run_eval
from mcp_server.tools.board import validar_lances


@pytest.fixture
def exemplo():
    return dataset.carregar_dataset()[0]


def test_dataset_publico_rastreavel():
    itens = dataset.carregar_dataset()
    info = json.loads((dataset.PASTA / "dataset.meta.json").read_text())
    assert 70 <= len(itens) <= 100
    publicados = [item for item in itens if item["origem"]["tipo"] == "lichess"]
    assert Counter(i["tema_esperado"] for i in publicados) == dict(dataset.ESTRATOS.values())
    assert all(i["origem"]["partida_url"].startswith("https://lichess.org/") for i in publicados)
    assert info["dataset_sha256"] == dataset.hash_arquivo(dataset.PASTA / "dataset.jsonl")
    assert info["semente"] == dataset.SEMENTE


def test_dataset_rejeita_duplicata_e_ref_invalida(exemplo, tmp_path):
    arquivo = tmp_path / "duplicado.jsonl"
    dataset.escrever_jsonl(arquivo, [exemplo, exemplo])
    with pytest.raises(ValueError, match="duplicado"):
        dataset.carregar_dataset(arquivo)
    item = {**exemplo, "lance_jogado": "Qz9"}
    dataset.escrever_jsonl(arquivo, [item])
    with pytest.raises(ValueError, match="Registro 1"):
        dataset.carregar_dataset(arquivo)


def test_preparo_confere_jogada_versus_resposta_do_puzzle(exemplo):
    origem = exemplo["origem"]
    board, jogado, fonte = dataset._puzzle({
        "FEN": exemplo["fen"], "Moves": " ".join(origem["moves_uci"]),
        "PuzzleId": origem["id"], "Rating": origem["rating"],
        "Themes": " ".join(origem["temas_lichess"]), "GameUrl": origem["partida_url"],
    })
    assert board.san(jogado) == exemplo["lance_jogado"]
    assert fonte["resposta_do_puzzle_uci"] != jogado.uci()
    board.push(jogado)
    assert board.parse_uci(fonte["resposta_do_puzzle_uci"]) in board.legal_moves


def test_metrica_legalidade_independente_de_recomendacao(exemplo):
    fen = chess.STARTING_FEN
    ocorrencias = metrics.checar_lances(fen, "1. e4 e5 2. Nf3")
    assert len(ocorrencias) == 3 and all(l["legal"] for l in ocorrencias)
    assert [l["legal"] for l in metrics.checar_lances(fen, "e4 Qz9 Nf3")] == [True, False, None]
    diferente = metrics.medir(exemplo, exemplo["lance_jogado"], exemplo["lance_jogado"], "outro")
    assert not diferente["tem_lance_invalido"] and not diferente["melhor_correto"]
    normal = metrics.medir(exemplo, "", chess.Board(exemplo["fen"]).parse_san(exemplo["melhor_lance"]).uci(),
                           exemplo["tema_esperado"])
    assert normal["melhor_correto"] and normal["tema_correto"]


class ModeloTeste:
    def __init__(self, *respostas, usage=None):
        self.respostas = iter(respostas)
        self.usage = usage
        self.mensagens = []

    async def ainvoke(self, mensagens):
        self.mensagens.append(mensagens)
        resposta = next(self.respostas)
        if isinstance(resposta, Exception):
            raise resposta
        return AIMessage(content=resposta, usage_metadata=self.usage)


def test_a_b_separam_entradas_e_nao_corrigem(exemplo):
    resposta = json.dumps({"explicacao": "Considere Qz9.", "melhor_lance": "Qz9", "tema": "garfo"})
    tokens = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    for v in ("A", "B"):
        modelo = ModeloTeste(resposta, usage=tokens)
        resultado = asyncio.run(run_eval.rodar_versao(exemplo, v, modelo, 2, (1, 3)))
        assert resultado["status"] == "ok" and resultado["tem_lance_invalido"]
        assert resultado["validada_agente"] is None and resultado["tokens_total"] == 120
        assert resultado["custo_usd"] == pytest.approx(0.00016)
        assert resultado["ragas_status"] == "inaplicavel_sem_rag"
        assert len(modelo.mensagens) == 1
        entrada = json.loads(modelo.mensagens[0][1].content)
        esperado = {"fen", "lance_jogado"} if v == "A" else {
            "fen", "lance_jogado", "avaliacao", "melhor_lance", "linha_motor",
        }
        assert set(entrada) == esperado


def test_consumo_desconhecido_e_status(exemplo):
    modelo = ModeloTeste("Resposta sem JSON.")
    resultado = asyncio.run(run_eval.rodar_versao(exemplo, "A", modelo, 2, (1, 3)))
    assert resultado["status"] == "incompleta" and resultado["avaliavel"]
    assert resultado["custo_usd"] is None and resultado["tokens_total"] is None
    erro = asyncio.run(run_eval.rodar_versao(exemplo, "B", ModeloTeste(RuntimeError("segredo")), 2))
    assert erro["status"] == "erro" and "segredo" not in str(erro)
    agregado = metrics.calcular_metricas([resultado, erro], 3)
    assert agregado["explicacoes"] == 0 and agregado["falhas"] == 1 and agregado["incompletas"] == 1
    assert agregado["invalidos_pct"] is None and agregado["melhor_pct"] is None
    assert agregado["tokens_total"] is None
    assert metrics.calcular_metricas([erro], 1)["invalidos_pct"] is None


def test_timeout_e_checkpoint_persiste_casos_anteriores(exemplo, tmp_path):
    class ModeloLento:
        async def ainvoke(self, mensagens):
            await asyncio.sleep(2)

    linha = asyncio.run(run_eval.rodar_versao(exemplo, "A", ModeloLento(), 0.01))
    assert linha["erros"] == ["TimeoutError"]
    arquivo = tmp_path / "checkpoint.jsonl"
    run_eval.checkpoint(arquivo, linha)
    with arquivo.open("ab") as saida:
        saida.write(b'{"id":')
    chave = exemplo["id"], "A"
    assert run_eval.ler_checkpoint(arquivo)[chave] == linha
    run_eval.checkpoint(arquivo, {**linha, "status": "incompleta"})
    assert run_eval.ler_checkpoint(arquivo)[chave]["status"] == "incompleta"
    assert len(arquivo.read_text().splitlines()) == 2


def test_c_executa_grafo_e_preserva_contexto_recuperado(exemplo, monkeypatch):
    class FerramentaTeste:
        def __init__(self, nome, funcao):
            self.name, self.funcao = nome, funcao

        async def ainvoke(self, entrada):
            return ToolMessage(content=json.dumps(self.funcao(**entrada["args"])),
                               tool_call_id=entrada["id"], name=self.name)

    tema = "outro"
    ficha = {"id": tema, "titulo": "Ficha", "arquivo": "ficha.md", "texto": "Contexto entregue."}

    @asynccontextmanager
    async def sessao():
        yield [
            FerramentaTeste("descrever_posicao", lambda fen: {"tabuleiro": True}),
            FerramentaTeste("validar_lances", validar_lances),
            FerramentaTeste("buscar_conceitos", lambda **_: [ficha]),
        ]

    monkeypatch.setattr(mcp, "sessao_mcp", sessao)
    bruto = json.dumps({"aconteceu": "O lance da partida mudou a posição.",
                        "motivo": "A variante analisada não confirma um motivo tático específico para o lance.",
                        "licao": "Confira as ameaças antes de jogar"}, ensure_ascii=False)
    invalido = bruto.replace("Confira as ameaças antes de jogar", "Jogue Qz9")
    resultado = asyncio.run(run_eval.rodar_versao(exemplo, "C", ModeloTeste(invalido, bruto), 5))
    assert resultado["status"] == "ok" and resultado["validada_agente"]
    assert resultado["contextos_rag"] == [ficha["texto"]] and resultado["ragas_status"] == "pendente"
    assert resultado["melhor_correto"] and resultado["tema"] == "outro"
    assert resultado["rascunhos_invalidos"] == 1 and resultado["rascunhos_n"] == 2
    assert not resultado["tem_lance_invalido"] and resultado["tentativas"] == 2

    fallback = asyncio.run(run_eval.rodar_versao(exemplo, "C", ModeloTeste("{}", "{}", "{}"), 5))
    assert fallback["status"] == "incompleta" and fallback["fallback"] and fallback["validada_agente"]
    assert fallback["contextos_rag"] == []


def test_piloto_interrompe_se_ficha_sumir_depois_da_classificacao(exemplo, monkeypatch):
    from langchain_core.tools import StructuredTool

    def descrever(fen: str) -> dict:
        return {"fen": fen}

    def buscar(pergunta: str, k: int, tema: str) -> list:
        return []

    @asynccontextmanager
    async def sessao():
        yield [StructuredTool.from_function(funcao, name=nome, description=nome) for nome, funcao in (
            ("descrever_posicao", descrever), ("buscar_conceitos", buscar),
        )]

    monkeypatch.setattr(mcp, "sessao_mcp", sessao)
    modelo = ModeloTeste()
    resultado = asyncio.run(run_eval.rodar_versao(exemplo, "C", modelo, 5, exigir_mcp=True))
    assert resultado["bloqueio_mcp"] == "buscar_conceitos" and resultado["chamadas_llm"] == 0
    assert not resultado["avaliavel"] and not resultado["fallback"]
    assert [chamada["nome"] for chamada in resultado["ferramentas_usadas"]] == [
        "descrever_posicao", "descrever_posicao", "buscar_conceitos",
    ]


def test_importador_pgn_resolve_indice_e_perspectiva(tmp_path):
    arquivo = tmp_path / "partidas.pgn"
    arquivo.write_text('[Event "Fixture"]\n[WhiteElo "1234"]\n[BlackElo "1400"]\n\n1. e4 e5 *\n')
    manifesto = tmp_path / "partidas.jsonl"
    dataset.escrever_jsonl(manifesto, [{
        "pgn": arquivo.name, "partida": 1, "meio_lance": 2, "id_partida": "fixture",
        "url": "https://example.invalid/fixture", "rotulo_por": "fixture", "tema_esperado": "garfo",
    }])
    tabuleiro, lance, tema, origem = next(dataset._partidas(manifesto))
    assert tabuleiro.turn == chess.BLACK and tabuleiro.san(lance) == "e5"
    assert tema == "garfo" and origem["rating"] == 1400 and origem["meio_lance"] == 2
