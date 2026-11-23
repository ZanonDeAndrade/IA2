"""Fila do treinador, dicas, chat e relatório do modo Jogar contra IA.

O motor é substituído por respostas controladas para fixar classificações. As
rotas HTTP, o SQLite, o trabalhador da fila e o validador são os reais.
"""

import asyncio
from contextlib import closing
from io import StringIO
from threading import Event
import time

import chess
import chess.pgn
from fastapi.testclient import TestClient
import pytest

from agent.classifier import chance_de_vitoria
from backend import db, services
from backend.jogo import treinador
from backend.jogo.modelos import StatusTreinador
from backend.main import app

BASE = "/api/jogo"
COMENTARIO_REAL = treinador.comentar_bom_lance_async
PUZZLE = {"id": "00test", "fen": chess.STARTING_FEN, "fen_origem": chess.STARTING_FEN, "lance_preparatorio": "e2e4",
          "solucao": ["e7e5"], "rating": 900, "temas": ["fork"], "temas_label": ["Garfo"],
          "url": "https://lichess.org/training/00test"}


class Motor:
    """Respostas determinísticas no formato das ferramentas MCP."""

    def __init__(self):
        self.classes: dict[str, str] = {}
        self.chamadas: list[str] = []

    async def __call__(self, nome, **argumentos):
        self.chamadas.append(nome)
        if nome == "jogar_stockfish":
            tabuleiro = chess.Board()
            for uci in argumentos["lances"]:
                tabuleiro.push_uci(uci)
            lance = min(tabuleiro.legal_moves, key=lambda m: m.uci())
            return {"uci": lance.uci(), "motor": "Stockfish de teste", "opcoes_uci": {}}
        if nome == "analisar_partida":
            jogo = chess.pgn.read_game(StringIO(argumentos["pgn"]))
            lances = list(jogo.mainline_moves())
            tabuleiro = jogo.board()
            for lance in lances[:argumentos["inicio"]]:
                tabuleiro.push(lance)
            lance = lances[argumentos["inicio"]]
            classe = self.classes.get(lance.uci(), "aceitavel")
            alternativas = sorted((m for m in tabuleiro.legal_moves if m != lance), key=lambda m: m.uci())
            melhor = lance if classe == "aceitavel" else alternativas[0]
            queda = {"aceitavel": 2.0, "imprecisao": 12.0, "erro": 22.0, "erro_grave": 40.0}[classe]
            cor = chess.COLOR_NAMES[tabuleiro.turn]
            antes = tabuleiro.fen()
            melhor_san, san, numero = tabuleiro.san(melhor), tabuleiro.san(lance), tabuleiro.fullmove_number
            tabuleiro.push(lance)
            chance = chance_de_vitoria(20)
            return [{
                "indice": argumentos["inicio"] + 1, "numero": numero, "cor": cor, "san": san, "uci": lance.uci(),
                "fen_antes": antes, "fen_depois": tabuleiro.fen(), "perspectiva": cor,
                "avaliacao_antes": {"tipo": "cp", "valor": 20}, "avaliacao_depois": {"tipo": "cp", "valor": -100},
                "cp_antes": 20, "cp_depois": -100, "chance_vitoria_antes": chance,
                "chance_vitoria_depois": chance - queda, "queda": queda, "classe": classe,
                "melhor_lance": melhor_san, "melhor_lance_uci": melhor.uci(), "linha_motor": [melhor_san],
            }]
        if nome == "analisar_posicao":
            tabuleiro = chess.Board(argumentos["fen"])
            lance = min(tabuleiro.legal_moves, key=lambda m: (not tabuleiro.is_capture(m), m.uci()))
            san = tabuleiro.san(lance)
            return {"perspectiva": chess.COLOR_NAMES[tabuleiro.turn], "avaliacao": {"tipo": "cp", "valor": 30},
                    "melhores_lances": [{"san": san, "uci": lance.uci(), "avaliacao": {"tipo": "cp", "valor": 30},
                                         "linha": [san]}], "linha_principal": [san]}
        if nome == "buscar_puzzles":
            return [PUZZLE]
        raise AssertionError(nome)


class Gerador:
    """Substitui o LLM no trabalhador. Pode segurar uma geração para simular atraso."""

    def __init__(self):
        self.chamadas: list[tuple[str, str, bool]] = []
        self.segurar: set[str] = set()
        self.liberar = Event()
        self.tema = "garfo"

    async def explicacao(self, fen, jogado, fila, *, analise=None, forcar=False, treino=None):
        if treino:
            assert treino["classe"] == analise["classe"] and treino["variante_verificada"] == analise["linha_motor"]
        self.chamadas.append((fen, jogado, forcar))
        while jogado in self.segurar and not self.liberar.is_set():
            await asyncio.sleep(0.02)
        return {"tema": self.tema, "tema_label": "Garfo", "texto": f"Explicação de {jogado} na posição {fen}.",
                "ficha": {"id": "garfo", "titulo": "Garfo", "arquivo": "knowledge_base/garfo.md"},
                "ferramentas_usadas": ["descrever_posicao", "buscar_conceitos", "validar_lances"], "tentativas": 1,
                "validada": True, "fallback": False, "cache": False}

    async def comentario(self, fen, jogado, melhor, linha, *, usar_modelo=True, treino=None):
        if not usar_modelo:
            # Sem LLM, o caminho real é local e determinístico.
            return await COMENTARIO_REAL(fen, jogado, melhor, linha, usar_modelo=False)
        self.chamadas.append((fen, jogado, False))
        return {"tema": "outro", "tema_label": "Outro", "texto": f"Comentário de {jogado}.", "ficha": None,
                "ferramentas_usadas": ["validar_lances"], "tentativas": 1, "validada": True, "fallback": False}


def _status(disponivel: bool):
    async def status(*, renovar=False):
        return StatusTreinador(configurado=True, disponivel=disponivel, provedor="ollama", modelo="qwen3:1.7b",
                               verificado_em=time.time(), mensagem="ok" if disponivel else "fora do ar")
    return status


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "treinador.sqlite"))
    monkeypatch.setenv("MCP_URL", "")
    monkeypatch.setenv("MCP_HEALTH_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    motor, gerador = Motor(), Gerador()
    monkeypatch.setattr(services, "mcp", motor)
    monkeypatch.setattr(services, "explicacao", gerador.explicacao)
    monkeypatch.setattr(treinador, "comentar_bom_lance_async", gerador.comentario)
    monkeypatch.setattr(treinador, "status_llm", _status(True))

    async def revisao(tarefa_id, partida, assinatura, fila):
        # Mesma informação que a análise completa produziria a partir das avaliações do jogo.
        jogo = next(j for j in _jogos() if j["partida_analise_id"] == partida["id"])
        lances = [l["avaliacao"] for l in jogo["lances"] if l["avaliacao"]]
        with closing(db.conectar()) as conn:
            db.salvar_analise(conn, partida["id"], lances, assinatura, tarefa_id)

    monkeypatch.setattr(services, "analisar_em_segundo_plano", revisao)
    with TestClient(app) as cliente:
        yield cliente, motor, gerador
    gerador.liberar.set()


def _jogos():
    import json

    with closing(db.conectar()) as conn:
        return [json.loads(l["dados"]) for l in conn.execute("SELECT dados FROM jogos")]


def iniciar(cliente, *, sessao=None, **config):
    headers = {"X-Sessao-Jogo": sessao} if sessao else {}
    r = cliente.post(BASE + "/iniciar", headers=headers,
                     json={"cor_do_jogador": "white", "dificuldade": "iniciante", **config})
    assert r.status_code == 201, r.text
    return r.json()


def mover(cliente, jogo, uci):
    r = cliente.post(f"{BASE}/{jogo['id']}/mover", json={"lance": uci, "versao": jogo["versao"]})
    assert r.status_code == 200, r.text
    return r.json()


def painel(cliente, jogo):
    return cliente.get(f"{BASE}/{jogo['id']}/treinador").json()


def aguardar(cliente, jogo, condicao, prazo=10):
    fim = time.time() + prazo
    while time.time() < fim:
        dados = painel(cliente, jogo)
        if condicao(dados):
            return dados
        time.sleep(0.05)
    raise AssertionError(f"Condição não atingida: {painel(cliente, jogo)}")


def por_indice(dados):
    return {item["indice"]: item for item in dados["explicacoes"]}


def ociosa(dados):
    return all(item["status"] not in {"pendente", "em_andamento"} for item in dados["explicacoes"])


def test_classificacao_antes_e_explicacao_vinculada_ao_lance(ambiente):
    cliente, motor, gerador = ambiente
    motor.classes["d2d4"] = "erro"
    gerador.segurar.add("d4")
    jogo = iniciar(cliente, modo_assistencia="treinador")
    jogo = mover(cliente, jogo, "e2e4")
    assert jogo["lances"][0]["avaliacao"]["classe"] == "aceitavel" and painel(cliente, jogo)["explicacoes"] == []
    jogo = mover(cliente, jogo, "d2d4")
    lance = jogo["lances"][2]
    # A classificação chega com o turno, enquanto a explicação ainda está retida na fila.
    assert lance["avaliacao"]["classe"] == "erro" and jogo["lances"][3]["autor"] == "ia"
    item = por_indice(painel(cliente, jogo))[3]
    assert item["status"] in {"pendente", "em_andamento"} and item["resultado"] is None
    gerador.liberar.set()
    item = por_indice(aguardar(cliente, jogo, ociosa))[3]
    contexto = item["contexto"]
    assert item["status"] == "concluida" and item["tipo"] == "explicacao" and item["resultado"]["fonte"] == "qwen3"
    assert contexto["lance_id"] == lance["id"] == f"{jogo['id']}:3" and contexto["fen_antes"] == lance["fen_antes"]
    assert contexto["fen_depois"] == lance["fen_depois"] and contexto["lance"] == "d4" and contexto["classe"] == "erro"
    assert contexto["melhor_lance"] == lance["avaliacao"]["melhor_lance"] == item["resultado"]["melhor_lance"]
    assert item["resultado"]["texto"] == f"Explicação de d4 na posição {lance['fen_antes']}."
    assert item["duracao_ms"] is not None and lance["tempos"]["avaliacao_ms"] >= 0
    assert jogo["lances"][3]["tempos"]["adversario_ms"] >= 0


def test_respostas_atrasadas_e_lances_consecutivos(ambiente):
    cliente, motor, gerador = ambiente
    motor.classes.update({"a2a3": "imprecisao", "b2b4": "erro", "h2h4": "erro_grave"})
    gerador.segurar.add("a3")
    jogo = iniciar(cliente, modo_assistencia="treinador")
    jogo = mover(cliente, jogo, "a2a3")
    aguardar(cliente, jogo, lambda d: por_indice(d)[1]["status"] == "em_andamento")
    jogo = mover(cliente, jogo, "b2b4")
    jogo = mover(cliente, jogo, "h2h4")
    estados = por_indice(painel(cliente, jogo))
    assert estados[1]["status"] == "em_andamento" and estados[3]["status"] == estados[5]["status"] == "pendente"
    gerador.liberar.set()
    dados = por_indice(aguardar(cliente, jogo, ociosa))
    # Depois da geração atrasada, a fila atende o erro grave mais recente antes do erro.
    assert [jogado for _, jogado, _ in gerador.chamadas] == ["a3", "h4", "b4"]
    for indice, san in ((1, "a3"), (3, "b4"), (5, "h4")):
        lance = jogo["lances"][indice - 1]
        item = dados[indice]
        assert item["contexto"]["lance"] == san and item["contexto"]["fen_antes"] == lance["fen_antes"]
        assert item["resultado"]["texto"] == f"Explicação de {san} na posição {lance['fen_antes']}."


def test_modos_livre_intensivo_e_troca_durante_a_partida(ambiente):
    cliente, motor, gerador = ambiente
    jogo = iniciar(cliente, modo_assistencia="livre")
    assert jogo["configuracoes"]["frequencia_explicacoes"] == "sob_demanda"
    jogo = mover(cliente, jogo, "e2e4")
    assert painel(cliente, jogo)["explicacoes"] == []
    r = cliente.post(f"{BASE}/{jogo['id']}/configuracoes", json={"versao": 0, "modo_assistencia": "intensivo"})
    assert r.status_code == 409
    r = cliente.post(f"{BASE}/{jogo['id']}/configuracoes", json={"versao": jogo["versao"], "modo_assistencia": "intensivo"})
    jogo = r.json()
    assert r.status_code == 200 and jogo["configuracoes"]["modo_assistencia"] == "intensivo"
    jogo = mover(cliente, jogo, "g1f3")
    jogo = mover(cliente, jogo, "a2a3")
    dados = por_indice(aguardar(cliente, jogo, ociosa))
    assert 1 not in dados and dados[3]["tipo"] == "comentario" and dados[3]["status"] == "concluida"
    assert dados[3]["resultado"]["texto"] == "Comentário de Nf3."
    assert dados[5]["status"] == "ignorada" and "sem informação pedagógica" in dados[5]["erro"]
    r = cliente.post(f"{BASE}/{jogo['id']}/explicacoes/5", json={"forcar": True})
    assert r.status_code == 202 and r.json()["origem"] == "manual"
    assert por_indice(aguardar(cliente, jogo, ociosa))[5]["status"] == "concluida"
    r = cliente.post(f"{BASE}/{jogo['id']}/configuracoes", json={"versao": jogo["versao"], "modo_assistencia": "treinador"})
    jogo = mover(cliente, r.json(), "b2b3")
    assert 7 not in por_indice(painel(cliente, jogo))
    assert cliente.post(f"{BASE}/{jogo['id']}/explicacoes/2").status_code == 422


def test_modo_intensivo_ignora_repeticao_com_contadores_fen_diferentes(ambiente, monkeypatch):
    cliente, motor, _ = ambiente

    async def mcp(nome, **argumentos):
        if nome == "jogar_stockfish":
            lances = argumentos["lances"]
            uci = "g8f6" if len(lances) % 4 == 1 else "f6g8"
            return {"uci": uci, "motor": "Stockfish de teste", "opcoes_uci": {}}
        return await motor(nome, **argumentos)

    monkeypatch.setattr(services, "mcp", mcp)
    jogo = iniciar(cliente, modo_assistencia="intensivo")
    for uci in ("g1f3", "f3g1", "g1f3"):
        jogo = mover(cliente, jogo, uci)
    primeiro, repetido = jogo["lances"][0], jogo["lances"][4]
    assert primeiro["fen_antes"] != repetido["fen_antes"]
    assert primeiro["fen_antes"].split()[:4] == repetido["fen_antes"].split()[:4]
    assert por_indice(painel(cliente, jogo))[5]["status"] == "ignorada"


def test_falha_ao_gravar_tarefa_reverte_o_turno(ambiente, monkeypatch):
    cliente, motor, _ = ambiente
    motor.classes["e2e4"] = "erro"
    jogo = iniciar(cliente, modo_assistencia="treinador")
    rota = f"{BASE}/{jogo['id']}"
    agendar = treinador.agendar_automatico

    def falhar_apos_agendar(conn, estado):
        agendar(conn, estado)
        raise RuntimeError("interrupção simulada antes do commit")

    with monkeypatch.context() as contexto:
        contexto.setattr(treinador, "agendar_automatico", falhar_apos_agendar)
        with pytest.raises(RuntimeError, match="interrupção simulada"):
            mover(cliente, jogo, "e2e4")
    assert cliente.get(rota).json() == jogo
    assert painel(cliente, jogo)["explicacoes"] == []
    jogo = mover(cliente, jogo, "e2e4")
    assert [item["indice"] for item in painel(cliente, jogo)["explicacoes"]] == [1]


def test_cache_persistencia_e_reinicio(ambiente, monkeypatch):
    cliente, motor, gerador = ambiente
    motor.classes["d2d4"] = "erro"
    jogo = mover(cliente, iniciar(cliente, modo_assistencia="livre"), "d2d4")
    rota = f"{BASE}/{jogo['id']}/explicacoes/1"
    primeira = cliente.post(rota).json()
    aguardar(cliente, jogo, ociosa)
    assert cliente.post(rota).json()["id"] == primeira["id"]
    assert len(gerador.chamadas) == 1 and gerador.chamadas[0][2] is False
    cliente.post(rota, json={"forcar": True})
    aguardar(cliente, jogo, ociosa)
    assert len(gerador.chamadas) == 2 and gerador.chamadas[1][2] is True
    salvo = por_indice(painel(cliente, jogo))[1]
    with closing(db.conectar()) as conn, conn:
        # Simula uma geração interrompida por queda do processo.
        conn.execute("UPDATE explicacoes_jogo SET status='em_andamento' WHERE id=?", (salvo["id"],))
    with TestClient(app) as reiniciada:
        dados = por_indice(aguardar(reiniciada, jogo, ociosa))
        assert dados[1]["status"] == "concluida" and dados[1]["contexto"] == salvo["contexto"]
    assert len(gerador.chamadas) == 3


def test_cancelamento_descarta_resultado(ambiente):
    cliente, motor, gerador = ambiente
    motor.classes["d2d4"] = "erro_grave"
    gerador.segurar.add("d4")
    jogo = mover(cliente, iniciar(cliente, modo_assistencia="treinador"), "d2d4")
    aguardar(cliente, jogo, lambda d: por_indice(d)[1]["status"] == "em_andamento")
    r = cliente.post(f"{BASE}/{jogo['id']}/explicacoes/1/cancelar")
    assert r.status_code == 200
    gerador.liberar.set()
    item = por_indice(aguardar(cliente, jogo, ociosa))[1]
    assert item["status"] == "cancelada" and item["resultado"] is None


def test_modelo_indisponivel_mantem_jogo_e_identifica_o_apoio(ambiente, monkeypatch):
    cliente, motor, gerador = ambiente
    monkeypatch.setattr(treinador, "status_llm", _status(False))
    motor.classes["d2d4"] = "erro"
    jogo = iniciar(cliente, modo_assistencia="intensivo")
    jogo = mover(cliente, jogo, "d2d4")
    jogo = mover(cliente, jogo, "g1f3")
    dados = por_indice(aguardar(cliente, jogo, ociosa))
    assert gerador.chamadas == []
    explicacao, comentario = dados[1]["resultado"], dados[3]["resultado"]
    assert explicacao["fonte"] == comentario["fonte"] == "motor" and explicacao["fallback"] and explicacao["validada"]
    assert explicacao["modelo"] is None and f"`{jogo['lances'][0]['avaliacao']['melhor_lance']}`" in explicacao["texto"]
    assert comentario["texto"].startswith("Você desenvolveu o cavalo")
    assert painel(cliente, jogo)["treinador"]["disponivel"] is False
    r = cliente.post(f"{BASE}/{jogo['id']}/chat", json={"pergunta": "Como está a estrutura de peões?", "versao": jogo["versao"]})
    assert r.status_code == 200 and r.json()["status"] == "indisponivel" and r.json()["fonte"] == "indisponivel"
    r = cliente.post(f"{BASE}/{jogo['id']}/chat", json={"pergunta": "Qual foi meu maior erro até agora?", "versao": jogo["versao"]})
    assert r.json()["validada"] and r.json()["fonte"] == "historico" and "`d4`" in r.json()["resposta"]


def test_dicas_em_etapas_e_mudanca_de_posicao(ambiente):
    cliente, motor, gerador = ambiente
    jogo = mover(cliente, iniciar(cliente, modo_assistencia="livre"), "e2e4")
    rota = f"{BASE}/{jogo['id']}/dica"
    assert cliente.post(rota, json={"versao": jogo["versao"], "nivel": 2}).status_code == 409
    assert cliente.post(rota, json={"versao": 0, "nivel": 1}).status_code == 409
    niveis = [cliente.post(rota, json={"versao": jogo["versao"], "nivel": n}).json() for n in (1, 2, 3)]
    assert [d["nivel"] for d in niveis] == [1, 2, 3] and all(d["fen"] == jogo["fen"] for d in niveis)
    assert niveis[0]["lance"] is None and niveis[1]["lance"] is None and niveis[1]["casa"]
    assert niveis[2]["lance"]["san"] in niveis[2]["texto"]
    repetida = cliente.post(rota, json={"versao": jogo["versao"], "nivel": 1}).json()
    assert repetida == niveis[0] and motor.chamadas.count("analisar_posicao") == 1
    jogo = mover(cliente, jogo, "g1f3")
    dados = painel(cliente, jogo)
    assert {d["versao"] for d in dados["dicas"]} == {jogo["versao"] - 1}
    assert cliente.post(rota, json={"versao": jogo["versao"], "nivel": 1}).json()["fen"] == jogo["fen"]


def test_chat_usa_posicao_do_servidor_e_lance_selecionado(ambiente, monkeypatch):
    cliente, motor, gerador = ambiente
    motor.classes["d2d4"] = "erro"
    recebido = {}

    async def chat(fen, pergunta, historico=None, *, lance_selecionado=None, treino=None):
        recebido.update(fen=fen, pergunta=pergunta, lance=lance_selecionado, historico=historico, treino=treino)
        return {"resposta": "Resposta validada.", "ferramentas_usadas": [{"nome": "descrever_posicao", "argumentos": {}}],
                "validada": True, "fallback": False}

    monkeypatch.setattr(treinador, "responder_chat_async", chat)
    jogo = mover(cliente, mover(cliente, iniciar(cliente, modo_assistencia="livre"), "e2e4"), "d2d4")
    rota = f"{BASE}/{jogo['id']}/chat"
    assert cliente.post(rota, json={"pergunta": "Por que meu último movimento foi ruim?", "versao": 1}).status_code == 409
    r = cliente.post(rota, json={"pergunta": "Por que meu último movimento foi ruim?", "versao": jogo["versao"],
                                 "historico": [{"role": "user", "content": "Oi"}]}).json()
    assert r["fonte"] == "qwen3" and r["fen"] == jogo["fen"] == recebido["fen"] and r["indice"] == 3
    assert recebido["lance"]["jogada_da_partida"] == "d4" and recebido["lance"]["classe"] == "erro"
    assert recebido["lance"]["fen_apos_lance"] == jogo["lances"][2]["fen_depois"]
    assert recebido["treino"]["cor_do_jogador"] == "white"
    r = cliente.post(rota, json={"pergunta": "Qual é a melhor alternativa?", "versao": jogo["versao"], "indice": 1}).json()
    assert r["fonte"] == "historico" and "`e4` já era a primeira escolha" in r["resposta"]
    r = cliente.post(rota, json={"pergunta": "Minha dama está ameaçada?", "versao": jogo["versao"]}).json()
    assert r["fonte"] == "regras" and r["resposta"].startswith("Sua dama na casa d1")
    assert cliente.post(rota, json={"pergunta": "x", "versao": jogo["versao"], "indice": 2}).status_code == 422

    depois_de_e4 = {"versao": jogo["versao"], "indice": 1, "posicao": "apos_lance"}
    r = cliente.post(rota, json={**depois_de_e4, "pergunta": "Qual foi meu maior erro até agora?"}).json()
    assert r["fen"] == jogo["lances"][0]["fen_depois"] and "nenhum" in r["resposta"]
    r = cliente.post(rota, json={**depois_de_e4, "pergunta": "Estou em uma posição favorável?"}).json()
    assert r["fonte"] == "motor" and r["ferramentas_usadas"][0]["argumentos"]["fen"] == jogo["lances"][0]["fen_depois"]


def test_relatorio_e_integracao_com_meu_progresso(ambiente):
    cliente, motor, gerador = ambiente
    motor.classes.update({"d2d4": "erro", "h2h4": "erro_grave"})
    jogo = iniciar(cliente, modo_assistencia="treinador", sessao="a" * 64, usuario="treino-relatorio")
    for uci in ("e2e4", "d2d4", "h2h4"):
        jogo = mover(cliente, jogo, uci)
    aguardar(cliente, jogo, ociosa)
    cliente.post(f"{BASE}/{jogo['id']}/dica", json={"versao": jogo["versao"], "nivel": 1})
    jogo = cliente.post(f"{BASE}/{jogo['id']}/desistir", json={"versao": jogo["versao"]}).json()
    rel = cliente.get(f"{BASE}/{jogo['id']}/relatorio").json()
    assert rel["resultado"] == "0-1" and rel["estatisticas"]["erros"] == 1 and rel["estatisticas"]["erros_graves"] == 1
    assert [l["san"] for l in rel["lances_criticos"]] == ["h4", "d4"]
    assert rel["temas"] == [{"tema": "garfo", "tema_label": "Garfo", "ocorrencias": 2, "indices": [3, 5]}]
    assert rel["dicas_usadas"]["nivel_1"] == 1 and rel["explicacoes"]["qwen3"] == 2
    assert rel["puzzles"][0]["id"] == "00test" and rel["puzzles_por_tema"]
    assert sum(f["lances"] for f in rel["evolucao"]) == 3 and rel["status_analise"] == "concluida"
    progresso = cliente.get(f"/api/relatorio/{jogo['usuario']}").json()
    assert progresso["partidas_analisadas"] == 1 and progresso["temas_fracos"][0]["tema"] == "fork"
    assert progresso["temas_fracos"][0]["erros"] == 2 and progresso["erros_sem_tema"] == 0
    assert cliente.get("/api/relatorio/outro-jogador").json()["partidas_analisadas"] == 0
    assert cliente.get("/api/relatorio/treino-relatorio").json()["partidas_analisadas"] == 0
    metricas = cliente.get("/api/treinador/metricas").json()
    assert metricas["adversario"]["amostras"] == 3 and metricas["avaliacao"]["amostras"] == 3
    assert metricas["explicacao_qwen3"]["amostras"] == 2 and metricas["dica"]["amostras"] == 1
