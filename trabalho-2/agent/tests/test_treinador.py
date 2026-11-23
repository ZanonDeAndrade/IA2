"""Treinador do modo jogo: comentários, dicas, histórico e conceitos, sem rede."""

import asyncio
from contextlib import asynccontextmanager
import json
import os

import chess
from langchain_core.messages import AIMessage, ToolMessage
import pytest

from agent import graph, treinador
from agent.mcp import Ferramentas
from agent.validator import extrair_lances
from mcp_server.tools.board import validar_lances

ABERTURA_ITALIANA = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
MATE_PASTOR = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"


class Modelo:
    def __init__(self, *respostas):
        self.respostas = iter(respostas)
        self.contextos = []

    async def ainvoke(self, mensagens, **_):
        self.contextos.append(json.loads(mensagens[-1].content))
        resposta = next(self.respostas)
        if callable(resposta):
            resposta = resposta(self.contextos[-1])
        return AIMessage(content=resposta)


class Ferramenta:
    def __init__(self, nome, executar):
        self.name, self.executar = nome, executar

    async def ainvoke(self, chamada):
        return ToolMessage(content=json.dumps(self.executar(**chamada["args"])), tool_call_id=chamada["id"], name=self.name)


FICHA_ROQUE = {"id": "roque", "titulo": "Roque", "arquivo": "knowledge_base/roque.md", "tema": "castling",
               "texto": "## Definição\nRei e torre.\n\n## Como reconhecer\nVeja se o rei pode rocar.\n\n"
                        "## Como evitar\nPlaneje o desenvolvimento antes do roque.\n\n## Exemplo\nLances: `O-O`"}


@pytest.fixture
def mcp_fixture(monkeypatch):
    buscas = []

    def conceitos(pergunta, k=4, tema=None):
        buscas.append(tema)
        return [FICHA_ROQUE] if tema == "roque" else []

    ferramentas = [Ferramenta("buscar_conceitos", conceitos), Ferramenta("validar_lances", validar_lances)]

    @asynccontextmanager
    async def sessao():
        yield ferramentas

    monkeypatch.setattr(treinador, "sessao_mcp", sessao)
    return buscas


def test_fatos_do_lance_sao_verificaveis_e_sem_coordenadas():
    fatos = {f["frase"] for f in treinador.fatos_do_lance(chess.STARTING_FEN, "Nf3", "e4")}
    assert "Você desenvolveu o cavalo, colocando mais uma peça em jogo." in fatos
    assert "O lance aumentou o seu controle sobre as casas centrais." in fatos
    roque = treinador.fatos_do_lance(ABERTURA_ITALIANA, "O-O", "O-O")
    assert [f["tema"] for f in roque][0] == "roque" and roque[-1]["frase"].startswith("O lance coincide")
    mate = treinador.fatos_do_lance(MATE_PASTOR, "Qxf7#")
    assert mate[0]["tema"] == "mate" and any("capturou o peão" in f["frase"] for f in mate)
    assert not treinador.lance_informativo(chess.STARTING_FEN, "a3", "e4")
    assert not treinador.lance_informativo(chess.STARTING_FEN, "a3", "a3")
    for fen, san in ((chess.STARTING_FEN, "Nf3"), (ABERTURA_ITALIANA, "O-O"), (MATE_PASTOR, "Qxf7#")):
        assert all(not extrair_lances(f["frase"]) for f in treinador.fatos_do_lance(fen, san))


def test_bom_lance_com_ficha_do_tema_e_validacao(mcp_fixture, monkeypatch):
    def escolher(dados):
        return json.dumps({"beneficio": dados["frases_permitidas"]["beneficio"][0],
                           "licao": dados["frases_permitidas"]["licao"][0]})

    modelo = Modelo('{"beneficio": "Você ganhou a partida.", "licao": "x"}', escolher)
    monkeypatch.setattr(treinador, "_modelo", lambda: modelo)
    resultado = asyncio.run(treinador.comentar_bom_lance_async(ABERTURA_ITALIANA, "O-O", "d3", ["d3", "d6"]))
    assert resultado["validada"] and not resultado["fallback"] and resultado["tentativas"] == 2
    assert resultado["tema"] == "roque" and resultado["ficha"]["id"] == "roque" and mcp_fixture == ["roque"]
    assert resultado["texto"].startswith("Você fez o roque")
    assert "`d3` como primeira opção" in resultado["texto"]
    assert "Use as frases permitidas" in modelo.contextos[1]["erros"][0]


def test_bom_lance_sem_tema_nao_forca_ficha(mcp_fixture, monkeypatch):
    def escolher(dados):
        assert "licao" not in dados["frases_permitidas"] and dados["ficha"] is None
        return json.dumps({"beneficio": dados["frases_permitidas"]["beneficio"][0],
                           "licao": "Continue desenvolvendo as peças antes de atacar."})

    monkeypatch.setattr(treinador, "_modelo", lambda: Modelo(escolher))
    resultado = asyncio.run(treinador.comentar_bom_lance_async(chess.STARTING_FEN, "Nf3", "e4", ["e4", "e5"]))
    assert resultado["validada"] and resultado["tema"] == "outro" and resultado["ficha"] is None
    assert mcp_fixture == []


def test_bom_lance_rejeita_coordenadas_e_cai_no_fallback(mcp_fixture, monkeypatch):
    invalida = json.dumps({"beneficio": "O lance aumentou o seu controle sobre as casas centrais.",
                           "licao": "Depois jogue e5 para ganhar espaço."})
    monkeypatch.setattr(treinador, "_modelo", lambda: Modelo(invalida, invalida, invalida))
    resultado = asyncio.run(treinador.comentar_bom_lance_async(chess.STARTING_FEN, "Nf3", "e4", ["e4", "e5"]))
    assert resultado["validada"] and resultado["fallback"] and resultado["tentativas"] == 3
    assert resultado["texto"].startswith("Você desenvolveu o cavalo") and "e5" not in resultado["texto"]


def test_modelo_indisponivel_gera_apoio_local_sem_mcp(monkeypatch):
    @asynccontextmanager
    async def sem_mcp():
        raise AssertionError("O apoio determinístico não deve abrir sessão MCP.")
        yield

    monkeypatch.setattr(treinador, "sessao_mcp", sem_mcp)
    resultado = asyncio.run(treinador.comentar_bom_lance_async(chess.STARTING_FEN, "Nf3", "e4", ["e4"], usar_modelo=False))
    assert resultado["validada"] and resultado["fallback"] and resultado["ferramentas_usadas"] == ["validar_lances"]


def _analise(fen, lance, linha=None, avaliacao=None):
    tabuleiro = chess.Board(fen)
    movimento = tabuleiro.parse_san(lance)
    return {"perspectiva": chess.COLOR_NAMES[tabuleiro.turn], "avaliacao": avaliacao or {"tipo": "cp", "valor": 20},
            "melhores_lances": [{"san": tabuleiro.san(movimento), "uci": movimento.uci()}],
            "linha_principal": linha or [lance]}


def test_dicas_em_etapas_so_revelam_o_lance_no_fim():
    analise = _analise(MATE_PASTOR, "Qxf7#", avaliacao={"tipo": "mate", "valor": 1, "a_favor": True})
    dica = treinador.diagnosticar_dica(MATE_PASTOR, analise)
    assert dica["tipo"] == "mate" and dica["tema"] == "mate"
    assert "Qxf7" not in dica["niveis"][1] + dica["niveis"][2] and "dama na casa h5" in dica["niveis"][2]
    assert dica["niveis"][3].startswith("O Stockfish sugere `Qxf7#`") and dica["lance"]["uci"] == "h5f7"
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
    quieta = treinador.diagnosticar_dica(fen, _analise(fen, "Nc6", ["Nc6", "Bb5", "a6"]))
    assert quieta["tipo"] == "desenvolvimento" and quieta["tema"] == "outro"


def test_dica_aponta_peca_ameacada():
    # Capturar um peão defendido pela dama não é ganho de material.
    defendido = "rnbqkbnr/ppp2ppp/8/3pp3/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq - 0 3"
    assert treinador.diagnosticar_dica(defendido, _analise(defendido, "exd5", ["exd5", "Qxd5"]))["tipo"] != "material"
    livre = "rnbqkb1r/pppppppp/8/8/3n4/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 3"
    dica = treinador.diagnosticar_dica(livre, _analise(livre, "Nxd4", ["Nxd4"]))
    assert dica["tema"] == "peca_pendurada" and "alvo adversário" in dica["niveis"][2]
    pendurada = "rnbqkbnr/pppp1ppp/8/4p3/3N4/8/PPPPPPPP/RNBQKB1R w KQkq - 0 3"
    dica = treinador.diagnosticar_dica(pendurada, _analise(pendurada, "Nf3", ["Nf3"]))
    assert dica["tipo"] == "defesa" and "cavalo na casa d4" in dica["niveis"][2]


def _lance(fen, san, cor, numero, classe="aceitavel", melhor=None, queda=0.0, chance=50.0):
    tabuleiro = chess.Board(fen)
    movimento = tabuleiro.parse_san(san)
    depois = tabuleiro.copy()
    depois.push(movimento)
    dados = {"classe": classe, "queda": queda, "melhor_lance": melhor or san, "linha_motor": [melhor or san],
             "chance_vitoria_depois": chance}
    return {"san": san, "uci": movimento.uci(), "cor": cor, "numero": numero, "fen_antes": fen,
            "fen_depois": depois.fen(), "avaliacao": dados if cor == "white" else None}


def test_respostas_do_historico_citam_o_lance_correto():
    b = chess.Board()
    lances = []
    for san, classe, melhor, queda in (("e4", "aceitavel", None, 1), ("e5", None, None, 0), ("Qh5", "imprecisao", "Nf3", 12),
                                        ("Nc6", None, None, 0), ("Bc4", "aceitavel", None, 3), ("Nf6", None, None, 0),
                                        ("Qxf7#", "aceitavel", None, 0)):
        cor = "white" if b.turn else "black"
        lances.append(_lance(b.fen(), san, cor, b.fullmove_number, classe or "aceitavel", melhor, queda,
                             chance=100.0 if san.endswith("#") else 55.0))
        b.push_san(san)
    texto, citacoes = treinador.resposta_historico("maior_erro", lances, "white", None)
    assert "`Qh5` no lance 2" in texto and "`Nf3`" in texto
    assert asyncio.run(treinador.validar_citacoes(texto, citacoes, _validar))
    texto, _ = treinador.resposta_historico("alternativa", lances, "white", lances[2])
    assert "em vez de `Qh5`" in texto and "`Nf3`" in texto
    texto, _ = treinador.resposta_historico("material", lances, "white", None)
    assert texto == "Você não perdeu material para o Stockfish até agora."
    texto, _ = treinador.resposta_historico("situacao", lances, "white", None)
    assert "favorável" in texto and "à frente" in texto
    assert not asyncio.run(treinador.validar_citacoes("`Qz9`", [(chess.STARTING_FEN, "Qz9")], _validar))


async def _validar(fen, lances):
    return validar_lances(fen, lances)


def test_intencoes_conceitos_e_pecas_ameacadas():
    assert treinador.intencao_historico("Qual foi meu maior erro até agora?") == "maior_erro"
    assert treinador.intencao_historico("Qual é a melhor alternativa?") == "alternativa"
    assert treinador.intencao_historico("Por que perdi material?") == "material"
    assert treinador.intencao_historico("Estou em uma posição favorável?") == "situacao"
    assert treinador.intencao_historico("Por que meu último movimento foi ruim?") is None
    assert len(treinador.catalogo_fichas()) == 30
    assert treinador.tema_do_conceito("O que significa cravada?") == "cravada"
    assert treinador.tema_do_conceito("O que é xeque duplo?") == "xeque_duplo"
    assert treinador.tema_do_conceito("Minha dama está ameaçada?") is None
    assert treinador.peca_da_pergunta("Minha dama está ameaçada?") == chess.QUEEN
    fen = "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    assert "não está sob ataque" in treinador.resposta_ameaca(fen, "white", chess.QUEEN)
    assert "sob ataque de o cavalo" in treinador.resposta_ameaca(fen, "black", chess.QUEEN)
    assert treinador.resposta_ameaca(fen, "white", chess.KING).endswith("não está sob ataque nesta posição.")
    assert "o cavalo na casa b1" in treinador.resposta_desenvolvimento(chess.STARTING_FEN, "white")


def test_conceito_com_rag_e_validacao(monkeypatch):
    ficha = {"id": "cravada", "titulo": "Cravada", "arquivo": "knowledge_base/cravada.md",
             "texto": "## Definição\nUma peça não pode sair da linha.\n\n## Como reconhecer\nProcure linhas.\n"}

    @asynccontextmanager
    async def sessao():
        yield [Ferramenta("buscar_conceitos", lambda **_: [ficha])]

    monkeypatch.setattr(treinador, "sessao_mcp", sessao)
    modelo = Modelo(json.dumps({"resposta": "Na cravada, Bb5 prende o cavalo."}),
                    json.dumps({"resposta": "Na cravada, uma peça fica presa à linha de outra mais valiosa."}))
    monkeypatch.setattr(treinador, "_modelo", lambda: modelo)
    resultado = asyncio.run(treinador.explicar_conceito_async("cravada", "O que significa cravada?"))
    assert resultado["validada"] and not resultado["fallback"] and "presa" in resultado["resposta"]
    assert modelo.contextos[0]["ficha"]["definicao"] == "Uma peça não pode sair da linha."
    monkeypatch.setattr(treinador, "_modelo", lambda: None)
    resultado = asyncio.run(treinador.explicar_conceito_async("cravada", "O que significa cravada?"))
    assert resultado["fallback"] and resultado["resposta"].startswith("Pela ficha Cravada")


def test_grafos_do_experimento_permanecem_intactos():
    """O modo jogo usa prompts próprios fora da assinatura do perfil de explicação."""
    pasta = graph.Path(graph.__file__).resolve().parent / "prompts"
    assert sorted(p.name for p in pasta.glob("*.md")) == [
        "README.md", "chat.md", "correcao.md", "explicacao.md", "sistema.md", "tema.md"]
    assert (pasta / "treinador" / "comentario.md").is_file()
    assert graph.TEMAS["outro"] == "Outro" and graph.MAX_TENTATIVAS == 3


@pytest.mark.skipif(not os.getenv("LANCE_TESTE_LLM_REAL"), reason="requer LLM real configurado (Ollama)")
def test_llm_real_comenta_bom_lance():
    from dotenv import load_dotenv

    load_dotenv(graph.RAIZ / ".env")
    resultado = asyncio.run(treinador.comentar_bom_lance_async(ABERTURA_ITALIANA, "O-O", "O-O", ["O-O", "d6"]))
    assert resultado["validada"] and not resultado["fallback"], resultado
    assert resultado["texto"].startswith("Você fez o roque")
    assert isinstance(Ferramentas([]).usadas, list)
