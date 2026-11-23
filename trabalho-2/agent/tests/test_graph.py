import asyncio
from contextlib import asynccontextmanager
import json

import chess
from langchain_core.messages import AIMessage, ToolMessage
import pytest

from agent import graph
from agent.mcp import Ferramentas
from mcp_server.tools.board import descrever_posicao, validar_lances

FEN = chess.STARTING_FEN
LINHA = ["e4", "e5", "Nf3"]


class ModeloDeTeste:
    def __init__(self, *respostas):
        self.respostas = iter(respostas)
        self.chamadas = []

    def bind_tools(self, ferramentas):
        self.ferramentas = ferramentas
        return self

    async def ainvoke(self, mensagens):
        self.chamadas.append(mensagens)
        resposta = next(self.respostas)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta if isinstance(resposta, AIMessage) else AIMessage(content=resposta)


class FerramentaDeTeste:
    def __init__(self, nome, executar):
        self.name = nome
        self.executar = executar

    async def ainvoke(self, chamada):
        dados = self.executar(**chamada["args"])
        return ToolMessage(
            content=json.dumps(dados), tool_call_id=chamada["id"], name=self.name,
        )


@pytest.fixture
def configurar(monkeypatch):
    def configurar(modelo, *, validar=validar_lances, conceitos=None, descrever=None):
        def motor(fen, **_):
            assert fen == FEN
            return {"linha_principal": LINHA}

        ferramentas = [
            FerramentaDeTeste("descrever_posicao", descrever or (lambda fen: {"vez": chess.Board(fen).turn})),
            FerramentaDeTeste("buscar_conceitos", lambda **_: conceitos or []),
            FerramentaDeTeste("validar_lances", validar),
            FerramentaDeTeste("analisar_posicao", motor),
        ]

        @asynccontextmanager
        async def sessao():
            yield ferramentas

        monkeypatch.setattr(graph, "_modelo", lambda: modelo)
        monkeypatch.setattr(graph, "sessao_mcp", sessao)
    return configurar


def _explicacao(licao):
    return json.dumps({
        "aconteceu": "O lance da partida mudou a posição.",
        "motivo": "A variante analisada não confirma um motivo tático específico para o lance.", "licao": licao,
    })


def test_explicacao_recupera_fatos_e_ficha_e_corrige(configurar):
    ficha = {"id": "outro", "titulo": "Revisão", "arquivo": "knowledge_base/outro.md", "texto": "Conceito."}
    posicoes = []

    def descrever(fen):
        posicoes.append(fen)
        return {"turno": chess.Board(fen).turn}

    modelo = ModeloDeTeste(_explicacao("O motor recomendou d4"), _explicacao("O motor recomendou e4"))
    configurar(modelo, conceitos=[ficha], descrever=descrever)
    resultado = graph.explicar_erro(FEN, "d4", "e4", LINHA)
    depois = chess.Board()
    depois.push_san("d4")
    assert posicoes == [FEN, depois.fen()]
    assert resultado["validada"] and resultado["tentativas"] == 2
    assert resultado["ficha"] == {chave: ficha[chave] for chave in ("id", "titulo", "arquivo")}
    assert "sem suporte" in modelo.chamadas[-1][-1].content
    assert resultado["texto"].count(".") == 4


def test_modo_json_rejeita_frase_factual_fora_do_esquema(monkeypatch):
    monkeypatch.setenv("LLM_JSON_MODE", "1")
    ficha = {"id": "outro", "titulo": "Revisão", "arquivo": "knowledge_base/outro.md", "texto": "Conceito."}
    ferramentas = Ferramentas([
        FerramentaDeTeste("descrever_posicao", descrever_posicao),
        FerramentaDeTeste("buscar_conceitos", lambda **_: [ficha]),
        FerramentaDeTeste("validar_lances", validar_lances),
    ])

    class Modelo:
        async def ainvoke(self, mensagens, **opcoes):
            dados = json.loads(mensagens[-1].content)
            propriedades = opcoes["response_format"]["json_schema"]["schema"]["properties"]
            frases = dados["frases_permitidas"]
            assert dados["tema"] == "Outro"
            assert propriedades["aconteceu"]["enum"] == frases["aconteceu"]
            texto = frases["aconteceu"][0] if dados["erros"] else "A dama das brancas se moveu."
            return AIMessage(content=json.dumps({
                "aconteceu": texto, "motivo": frases["motivo"][0],
                "licao": "Confira as ameaças antes de jogar",
            }))

    estado = asyncio.run(graph.construir_grafo_explicacao(Modelo(), ferramentas).ainvoke({
        "fen": FEN, "lance_jogado": "d4", "melhor_lance": "e4", "linha_motor": LINHA,
    }))
    assert estado["pronto"] and estado["validada"] and estado["tentativas"] == 2
    assert estado["tema"] == "outro" and estado["ficha"]["id"] == "outro"
    assert "peão das brancas" in estado["texto"] and "dama" not in estado["texto"]


def test_garfo_com_xeque_exige_captura_do_outro_alvo_na_variante():
    fen = "5r2/pp3pk1/2p1pRp1/6Qp/2P5/P7/1q1r2PP/5R1K w - - 2 32"
    tabuleiro = chess.Board(fen)
    linha = ["Rxg6+", "fxg6", "Qe7+", "Kh6", "Qxf8+"]
    assert all(e.tema != "garfo" for e in graph.candidatos_taticos(tabuleiro, {"linha_principal": linha[:-1]}))
    assert any(e.tema == "garfo" and "dama" in e.frase and "torre" in e.frase
               for e in graph.candidatos_taticos(tabuleiro, {"linha_principal": linha}))
    assert tabuleiro.fen() == fen


def test_frase_verificada_de_mate_respeita_o_formato_da_explicacao():
    tabuleiro = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
    evidencia = graph.candidatos_taticos(tabuleiro, {"linha_principal": ["Qg7#"], "avaliacao": {"tipo": "mate", "valor": 1}})[0]
    assert evidencia.tema == "mate"
    motivo = evidencia.frase
    assert "xeque-mate" in motivo and graph._AVALIACAO_NUMERICA.search(motivo) is None


def test_chat_rejeita_descricao_que_contradiz_a_vez(monkeypatch):
    monkeypatch.setenv("LLM_JSON_MODE", "1")
    tabuleiro = chess.Board()
    tabuleiro.push_san("e4")
    ferramentas = Ferramentas([FerramentaDeTeste("descrever_posicao", descrever_posicao)])

    class Modelo:
        def bind_tools(self, ferramentas):
            return self

        async def ainvoke(self, mensagens, **opcoes):
            if not opcoes:
                return AIMessage(content="", tool_calls=[
                    {"name": "descrever_posicao", "args": {"fen": tabuleiro.fen()}, "id": "descricao"},
                ])
            permitidas = opcoes["response_format"]["json_schema"]["schema"]["properties"]["resposta"]["enum"]
            assert "É a vez das pretas." in permitidas
            return AIMessage(content='{"resposta":"É a vez das brancas."}')

    estado = asyncio.run(graph.construir_agente_chat(Modelo(), ferramentas).ainvoke({
        "fen": tabuleiro.fen(), "pergunta": "Quem tem a vez?",
    }))
    assert not estado["validada"]
    assert "É a vez das brancas" not in estado["texto"]


def test_tres_tentativas_e_fallback_deterministico(configurar):
    tentativa = _explicacao("O motor recomenda Qz9")
    modelo = ModeloDeTeste(tentativa, tentativa, tentativa)
    configurar(modelo)
    resultado = graph.explicar_erro(FEN, "d4", "e4", LINHA)
    assert resultado["validada"] and resultado["tentativas"] == 3
    assert resultado["tema"] == "outro" and resultado["ficha"] is None
    assert "Qz9" not in resultado["texto"] and "`e4 e5 Nf3`" in resultado["texto"]
    assert len(modelo.chamadas) == 3


def test_resposta_incompleta_e_base_vazia(configurar):
    configurar(ModeloDeTeste("{}", _explicacao("É preciso comparar as opções")))
    resultado = graph.explicar_erro(FEN, "d4", "e4", LINHA)
    assert resultado["validada"] and resultado["tentativas"] == 2 and resultado["ficha"] is None


def test_validacao_indisponivel_bloqueia_ate_fallback(configurar):
    def falha(**_):
        raise RuntimeError("Falha no servidor")

    configurar(None, validar=falha)
    resultado = graph.explicar_erro(FEN, "d4", "e4", LINHA)
    assert not resultado["validada"] and resultado["tentativas"] == 0
    assert resultado["texto"] == graph._SEM_RESPOSTA


def _chamada(nome, argumentos, id_):
    return {"name": nome, "args": argumentos, "id": id_}


def test_chat_usa_fen_atual_e_valida_variante(configurar):
    modelo = ModeloDeTeste(
        AIMessage(content="", tool_calls=[
            _chamada("analisar_posicao", {"fen": "injetado"}, "motor"),
            _chamada("descrever_posicao", {}, "fatos"),
            _chamada("buscar_conceitos", {"pergunta": "garfo"}, "rag"),
        ]),
        "Jogue d4.",
        "O motor recomenda `e4 e5 Nf3`.",
    )
    configurar(modelo)
    resultado = graph.responder_chat(FEN, "Qual o melhor lance?")
    assert resultado["validada"] and "e4 e5 Nf3" in resultado["resposta"]
    assert resultado["ferramentas_usadas"][0]["argumentos"]["fen"] == FEN
    assert {f.name for f in modelo.ferramentas} == graph._CHAT_TOOLS
    assert "sem suporte" in modelo.chamadas[-1][-1].content
    assert any(item["nome"] == "validar_lances" for item in resultado["ferramentas_usadas"])


def test_chat_nao_publica_sem_evidencias(configurar):
    configurar(ModeloDeTeste("Há um mate.", "O rei está exposto.", "Ganhe a dama."))
    resultado = graph.responder_chat(FEN, "E agora?")
    assert not resultado["validada"] and resultado["resposta"] == graph._SEM_RESPOSTA


def test_chat_consulta_posicao_se_o_modelo_responder_so_com_historico(configurar):
    modelo = ModeloDeTeste("Já informei o turno.", "É a vez das brancas.")
    configurar(modelo, descrever=descrever_posicao)
    historico = [{"role": "assistant", "content": "É a vez das pretas."}]
    resultado = graph.responder_chat(FEN, "De quem é a vez?", historico)
    assert resultado["validada"] and resultado["resposta"] == "É a vez das brancas."
    assert resultado["ferramentas_usadas"] == [{"nome": "descrever_posicao", "argumentos": {"fen": FEN}}]
    assert json.loads(modelo.chamadas[0][-1].content)["historico"] == historico
    assert len(modelo.chamadas[0]) == 2


def test_chat_trata_falha_do_modelo(configurar):
    configurar(ModeloDeTeste(RuntimeError("Timeout")))
    assert not graph.responder_chat(FEN, "E agora?")["validada"]
    assert not graph.responder_chat("FEN inválido", "E agora?")["validada"]
    assert not graph.explicar_erro("inválido", "d4", "e4", LINHA)["validada"]


def test_chat_trata_ferramenta_indisponivel(configurar):
    def descrever(**_):
        raise RuntimeError("Falha no servidor")

    modelo = ModeloDeTeste(
        AIMessage(content="", tool_calls=[_chamada("descrever_posicao", {}, "fatos")]),
        "O rei está exposto.", "O rei está exposto.", "O rei está exposto.",
    )
    configurar(modelo, descrever=descrever)
    resultado = graph.responder_chat(FEN, "Como está meu rei?")
    assert not resultado["validada"]
    assert resultado["resposta"] == graph._SEM_RESPOSTA
    assert "indisponível" in modelo.chamadas[1][-1].content


def test_chat_usa_fallback_do_motor_apos_tres_rascunhos(configurar):
    modelo = ModeloDeTeste(
        AIMessage(content="", tool_calls=[_chamada("analisar_posicao", {}, "motor")]),
        "Jogue d4.", "Eu jogaria com o peão do rei.", "A posição tem avaliação +3.5.",
    )
    configurar(modelo)
    resultado = graph.responder_chat(FEN, "Que lance devo jogar?")
    assert resultado["validada"] and resultado["fallback"]
    assert resultado["resposta"] == "O Stockfish indicou a variante `e4 e5 Nf3`."
    assert len(modelo.chamadas) == 4


def test_mcp_real_stdio(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_URL", "")
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "ainda-sem-indice"))
    monkeypatch.setattr(graph, "_modelo", lambda: None)

    async def verificar():
        async with graph.sessao_mcp() as ferramentas:
            assert {f.name for f in ferramentas} == {
                "analisar_partida", "analisar_posicao", "validar_lances", "descrever_posicao",
                "buscar_partidas", "buscar_puzzles", "buscar_conceitos", "jogar_stockfish",
            }
            mcp = graph.Ferramentas(ferramentas)
            assert await mcp.chamar("buscar_conceitos", pergunta="garfo", tema="garfo") == []
            assert (await mcp.validar(FEN, ["e4"]))[0]["san"] == "e4"

    asyncio.run(verificar())
    resultado = graph.explicar_erro(FEN, "d4", "e4", LINHA)
    assert resultado["validada"] and resultado["tentativas"] == 0
