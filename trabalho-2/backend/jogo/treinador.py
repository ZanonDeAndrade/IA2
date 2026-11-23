"""Treinador em tempo real do modo Jogar contra IA.

O turno da partida nunca espera o LLM. Depois que o turno é confirmado, a
explicação entra em uma fila persistida no SQLite e é processada por um único
trabalhador assíncrono. Cada registro guarda o vínculo completo com o lance
(ID, índice, FENs, jogada, melhor alternativa e classe) para que uma resposta
atrasada nunca seja exibida como se pertencesse a outro lance.

Responsabilidades separadas:
    - Stockfish adversário: ``servico.jogar_ia`` e a ferramenta MCP ``jogar_stockfish``.
    - Stockfish avaliador: ``servico.avaliar`` e as dicas desta camada.
    - Qwen3 treinador: grafos do agente chamados pelo trabalhador da fila.
"""

import asyncio
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
import logging
import os
import re
import sqlite3
from statistics import mean, median
from time import perf_counter, time
from uuid import uuid4

import chess
from fastapi import HTTPException
import httpx

from agent.graph import responder_chat_async
from agent.treinador import (
    ROTULOS, comentar_bom_lance_async, contexto_do_lance, diagnosticar_dica, explicar_conceito_async, ficha_do_tema,
    intencao_historico, lance_informativo, peca_da_pergunta, pergunta_desenvolvimento, pergunta_tatica, resposta_ameaca,
    resposta_desenvolvimento, resposta_historico, resposta_tatica, secao_reconhecer, tema_do_conceito,
    validar_citacoes,
)
from agent.validator import explicacao_padrao, validar_resposta_async
from backend import db, services
from backend.jogo import repositorio, servico
from backend.jogo.modelos import (
    ContextoExplicacao, JogoSalvo, LanceJogo, PerguntaJogo, StatusTreinador,
)
from mcp_server.tools.board import validar_lances as validar_lances_local
from mcp_server.tools.engine import normalizar_avaliacao, perfil_analise
from mcp_server.tools.puzzles import TAGS

LOGGER = logging.getLogger(__name__)
PRAZO_EXPLICACAO = 150
MAX_TENTATIVAS_TAREFA = 2
PRIORIDADE_MANUAL = 100
PRIORIDADES = {"erro_grave": 40, "erro": 30, "imprecisao": 20, "aceitavel": 5}
# Comentários automáticos de lances aceitáveis ficam obsoletos depois de dois lances novos.
LANCES_PARA_SUPERAR = 2
FAIXAS_PUZZLES = {"iniciante": (600, 1300), "intermediario": (1000, 1700),
                  "avancado": (1400, 2100), "mestre": (1800, 2600)}
_SEM_INFORMACAO = "Lance sem informação pedagógica adicional. A classificação já resume a decisão."
LINGUAGEM_POR_NIVEL = {
    "iniciante": "Prefira palavras simples e, entre lições equivalentes, a orientação mais concreta.",
    "intermediario": "Nomeie o padrão de xadrez e prefira uma orientação que se aplique a posições semelhantes.",
    "avancado": "Pode usar vocabulário técnico do xadrez e destacar as condições do padrão.",
    "mestre": "Seja conciso e use termos técnicos precisos ao escolher a lição.",
}


async def _validar_local(fen: str, lances: list[str]) -> list[dict]:
    return validar_lances_local(fen, lances)


# Disponibilidade do LLM -----------------------------------------------------

_status: dict = {"em": 0.0, "dados": None}


def _configuracao_llm() -> tuple[str | None, str, str | None, str | None]:
    provedor = (os.getenv("LLM_PROVIDER") or "openai").lower()
    nome = os.getenv("LLM_MODEL") or None
    chave = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    url = os.getenv("LLM_BASE_URL") or None
    if provedor == "ollama":
        chave = os.getenv("LLM_API_KEY") or "ollama"
        url = url or "http://localhost:11434/v1"
    return nome, provedor, chave, url or "https://api.openai.com/v1"


async def status_llm(*, renovar: bool = False) -> StatusTreinador:
    """Consulta /models com prazo curto e guarda o resultado por 10 s."""
    if not renovar and _status["dados"] is not None and time() - _status["em"] < 10:
        return _status["dados"]
    nome, provedor, chave, url = _configuracao_llm()
    if not nome or provedor not in {"openai", "ollama"} or not chave:
        dados = StatusTreinador(configurado=False, disponivel=False, provedor=provedor, modelo=nome,
                                verificado_em=time(), mensagem="Treinador sem modelo configurado. Configure LLM_MODEL.")
    elif "qwen3" not in nome.casefold():
        dados = StatusTreinador(configurado=True, disponivel=False, provedor=provedor, modelo=nome,
                                verificado_em=time(), mensagem="Configure um modelo Qwen3 para o modo treinador.")
    else:
        try:
            async with httpx.AsyncClient(timeout=3) as cliente:
                resposta = await cliente.get(url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {chave}"})
                resposta.raise_for_status()
                ids = {item.get("id") for item in resposta.json().get("data", []) if isinstance(item, dict)}
            disponivel = not ids or nome in ids
            mensagem = "Treinador disponível." if disponivel else f"O modelo {nome} não está disponível no provedor."
        except (httpx.HTTPError, ValueError, AttributeError):
            disponivel, mensagem = False, "O provedor do modelo não respondeu. A partida segue com o Stockfish."
        dados = StatusTreinador(configurado=True, disponivel=disponivel, provedor=provedor, modelo=nome,
                                verificado_em=time(), mensagem=mensagem)
    _status.update(em=time(), dados=dados)
    return dados


# Fila persistida -------------------------------------------------------------

def _registro(linha: sqlite3.Row) -> dict:
    return {
        "id": linha["id"], "indice": linha["indice"], "status": linha["status"], "tipo": linha["tipo"], "origem": linha["origem"],
        "tentativas": linha["tentativas"], "contexto": json.loads(linha["contexto"]),
        "resultado": json.loads(linha["dados"]) if linha["dados"] else None, "erro": linha["erro"],
        "criado_em": linha["criado_em"], "concluido_em": linha["concluido_em"], "duracao_ms": linha["duracao_ms"],
    }


def listar(jogo_id: str) -> list[dict]:
    with closing(db.conectar()) as conn:
        linhas = conn.execute("SELECT * FROM explicacoes_jogo WHERE jogo_id=? ORDER BY indice", (jogo_id,)).fetchall()
    return [_registro(linha) for linha in linhas]


def _contexto(jogo: JogoSalvo, lance: LanceJogo) -> ContextoExplicacao:
    dados = lance.avaliacao
    return ContextoExplicacao(
        jogo_id=jogo.id, lance_id=lance.id, indice=lance.indice, numero=lance.numero, cor=lance.cor, lance=lance.san,
        uci=lance.uci, fen_antes=lance.fen_antes, fen_depois=lance.fen_depois, melhor_lance=dados.melhor_lance,
        melhor_lance_uci=dados.melhor_lance_uci, classe=dados.classe, queda=dados.queda, versao=jogo.versao,
    )


def _tipo(lance: LanceJogo) -> str:
    dados = lance.avaliacao
    coincide = dados.melhor_lance_uci == lance.uci
    return "comentario" if dados.classe == "aceitavel" or coincide else "explicacao"


def _inserir_tarefa(conn: sqlite3.Connection, jogo: JogoSalvo, lance: LanceJogo, *, origem: str,
                    prioridade: int, contexto: dict, ignorar: str | None = None) -> str:
    id_ = uuid4().hex
    criado_em = db.agora()
    status = "ignorada" if ignorar else "pendente"
    conn.execute("""INSERT INTO explicacoes_jogo(id, jogo_id, indice, lance_id, tipo, origem, prioridade, status,
                    contexto, erro, criado_em, concluido_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (id_, jogo.id, lance.indice, lance.id, _tipo(lance), origem, prioridade, status,
                  json.dumps(contexto, ensure_ascii=False), ignorar, criado_em, criado_em if ignorar else None))
    return id_


def enfileirar(jogo: JogoSalvo, lance: LanceJogo, *, forcar: bool = False) -> dict:
    """Cria ou reaproveita a tarefa do lance. Só um pedido explícito gera de novo um resultado salvo."""
    if lance.autor != "jogador" or lance.avaliacao is None:
        raise HTTPException(409, "Avalie o lance do jogador antes de pedir a explicação.")
    contexto = _contexto(jogo, lance).model_dump() | {"forcar": forcar}
    with closing(db.conectar()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        atual = conn.execute("SELECT * FROM explicacoes_jogo WHERE jogo_id=? AND indice=?",
                             (jogo.id, lance.indice)).fetchone()
        if atual is not None:
            if atual["lance_id"] != lance.id:
                raise HTTPException(409, "O registro do lance não corresponde à partida.")
            ativo = atual["status"] in {"pendente", "em_andamento"}
            reaproveitar = ativo or (atual["status"] == "concluida" and not forcar)
            if reaproveitar:
                if ativo:
                    conn.execute("UPDATE explicacoes_jogo SET prioridade=?, origem='manual' WHERE id=?",
                                 (PRIORIDADE_MANUAL, atual["id"]))
                    atual = conn.execute("SELECT * FROM explicacoes_jogo WHERE id=?", (atual["id"],)).fetchone()
                return _registro(atual)
            conn.execute("""UPDATE explicacoes_jogo SET status='pendente', origem='manual', prioridade=?, tentativas=0,
                            contexto=?, dados=NULL, erro=NULL, iniciado_em=NULL, concluido_em=NULL, duracao_ms=NULL
                            WHERE id=?""", (PRIORIDADE_MANUAL, json.dumps(contexto, ensure_ascii=False), atual["id"]))
            id_ = atual["id"]
        else:
            id_ = _inserir_tarefa(conn, jogo, lance, origem="manual", prioridade=PRIORIDADE_MANUAL, contexto=contexto)
        registro = _registro(conn.execute("SELECT * FROM explicacoes_jogo WHERE id=?", (id_,)).fetchone())
    acordar_fila()
    return registro


def agendar_automatico(conn: sqlite3.Connection, jogo: JogoSalvo) -> None:
    """Grava a tarefa do novo lance na mesma transação que confirma o turno."""
    config = jogo.configuracoes
    if not config.modo_treinador or config.modo_assistencia == "livre":
        return None
    lance = next((l for l in reversed(jogo.lances) if l.autor == "jogador"), None)
    if lance is None or lance.avaliacao is None:
        return None
    ignorar = None
    if lance.avaliacao.classe == "aceitavel":
        if config.modo_assistencia != "intensivo":
            return None
        posicao = lance.fen_antes.split()[:4]
        repetido = any(l.uci == lance.uci and l.fen_antes.split()[:4] == posicao
                       for l in jogo.lances[:lance.indice - 1])
        if repetido or not lance_informativo(lance.fen_antes, lance.san, lance.avaliacao.melhor_lance):
            ignorar = _SEM_INFORMACAO
    _inserir_tarefa(conn, jogo, lance, origem="automatica", prioridade=PRIORIDADES[lance.avaliacao.classe],
                    contexto=_contexto(jogo, lance).model_dump(), ignorar=ignorar)


def cancelar(jogo_id: str, indice: int) -> dict:
    with closing(db.conectar()) as conn, conn:
        atual = conn.execute("SELECT * FROM explicacoes_jogo WHERE jogo_id=? AND indice=?", (jogo_id, indice)).fetchone()
        if atual is None:
            raise HTTPException(404, "Não há explicação solicitada para este lance.")
        if atual["status"] in {"pendente", "em_andamento"}:
            conn.execute("""UPDATE explicacoes_jogo SET status='cancelada', erro='Cancelada pelo jogador.', concluido_em=?
                            WHERE id=?""", (db.agora(), atual["id"]))
    if FILA is not None:
        FILA.cancelar(atual["id"])
    return next(item for item in listar(jogo_id) if item["indice"] == indice)


def resumo_fila() -> dict[str, int]:
    with closing(db.conectar()) as conn:
        linhas = conn.execute("""SELECT status, count(*) AS n FROM explicacoes_jogo
                                 WHERE status IN ('pendente','em_andamento') GROUP BY status""").fetchall()
    return {linha["status"]: linha["n"] for linha in linhas}


async def explicacao_do_motor(contexto: dict) -> dict:
    """Mensagem limitada aos dados do Stockfish, usada quando o LLM está indisponível."""
    linha = contexto["linha_motor"]
    if contexto["tipo"] == "comentario":
        return await comentar_bom_lance_async(contexto["fen_antes"], contexto["lance"], contexto["melhor_lance"],
                                              linha, usar_modelo=False)
    texto = explicacao_padrao(contexto["lance"], contexto["melhor_lance"], linha)
    resultado = await validar_resposta_async(texto, contexto["fen_antes"], linha, validar_lances=_validar_local,
                                             outras_linhas=([contexto["lance"]],))
    return {"tema": "outro", "tema_label": ROTULOS["outro"], "ficha": None, "tentativas": 0,
            "texto": texto if resultado["valida"] else "Não foi possível confirmar a variante do Stockfish.",
            "ferramentas_usadas": ["validar_lances"], "validada": resultado["valida"], "fallback": True}


VERSAO_COMENTARIO = "2"


def perfil_comentario() -> str:
    """Assinatura própria dos comentários: perfil do agente, prompts do treinador e versão da lógica."""
    dados = sha256((VERSAO_COMENTARIO + services.perfil_explicacao()).encode())
    for caminho in sorted((db.RAIZ / "agent" / "prompts" / "treinador").glob("*.md")):
        dados.update(caminho.read_bytes())
    return "treinador:comentario:" + dados.hexdigest()


class FilaTreinador:
    """Um trabalhador por processo da API. O Ollama local atende uma geração por vez."""

    def __init__(self, fila_llm: asyncio.Semaphore):
        self.fila_llm = fila_llm
        self._evento = asyncio.Event()
        self._ciclo: asyncio.Task | None = None
        self._atual: tuple[str, asyncio.Task] | None = None
        self._encerrando = False

    async def iniciar(self) -> None:
        with closing(db.conectar()) as conn, conn:
            # Uma geração interrompida por reinício volta para a fila.
            conn.execute("UPDATE explicacoes_jogo SET status='pendente' WHERE status='em_andamento'")
        self._ciclo = asyncio.create_task(self._executar_ciclo(), name="fila-treinador")

    async def encerrar(self) -> None:
        self._encerrando = True
        if self._ciclo:
            self._ciclo.cancel()
            try:
                await self._ciclo
            except asyncio.CancelledError:
                pass

    def acordar(self) -> None:
        self._evento.set()

    def cancelar(self, id_: str) -> None:
        if self._atual and self._atual[0] == id_:
            self._atual[1].cancel()

    def _proxima(self) -> dict | None:
        with closing(db.conectar()) as conn, conn:
            linha = conn.execute("""SELECT * FROM explicacoes_jogo WHERE status='pendente'
                                    ORDER BY prioridade DESC, criado_em DESC, indice DESC LIMIT 1""").fetchone()
            if linha is None:
                return None
            alterada = conn.execute("""UPDATE explicacoes_jogo SET status='em_andamento', iniciado_em=?,
                                       tentativas=tentativas+1 WHERE id=? AND status='pendente'""",
                                    (db.agora(), linha["id"]))
            if alterada.rowcount != 1:
                return None
            return _registro(conn.execute("SELECT * FROM explicacoes_jogo WHERE id=?", (linha["id"],)).fetchone())

    async def _executar_ciclo(self) -> None:
        while True:
            try:
                tarefa = self._proxima()
            except sqlite3.Error as erro:
                LOGGER.warning("Fila do treinador indisponível (%s)", type(erro).__name__)
                tarefa = None
            if tarefa is None:
                self._evento.clear()
                try:
                    await asyncio.wait_for(self._evento.wait(), timeout=5)
                except TimeoutError:
                    pass
                continue
            execucao = asyncio.create_task(self.processar(tarefa))
            self._atual = (tarefa["id"], execucao)
            try:
                await execucao
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    execucao.cancel()
                    raise
                LOGGER.info("Explicação %s cancelada", tarefa["id"])
            except Exception as erro:
                LOGGER.warning("Falha inesperada na fila do treinador (%s)", type(erro).__name__)
            finally:
                self._atual = None

    async def processar(self, tarefa: dict) -> None:
        contexto = tarefa["contexto"]
        inicio = perf_counter()

        def gravar(status: str, dados: dict | None = None, erro: str | None = None) -> None:
            with closing(db.conectar()) as conn, conn:
                conn.execute("""UPDATE explicacoes_jogo SET status=?, dados=?, erro=?, concluido_em=?, duracao_ms=?
                                WHERE id=? AND status='em_andamento'""",
                             (status, json.dumps(dados, ensure_ascii=False) if dados else None, erro, db.agora(),
                              round((perf_counter() - inicio) * 1000), tarefa["id"]))

        try:
            jogo, _ = repositorio.obter(contexto["jogo_id"])
            lances = jogo.lances
            lance = lances[contexto["indice"] - 1] if contexto["indice"] <= len(lances) else None
            if (lance is None or lance.id != contexto["lance_id"] or lance.fen_antes != contexto["fen_antes"]
                    or lance.fen_depois != contexto["fen_depois"] or lance.avaliacao is None):
                gravar("erro", erro="O lance registrado mudou. A explicação foi descartada.")
                return
            posteriores = sum(1 for l in lances[lance.indice:] if l.autor == "jogador")
            if tarefa["tipo"] == "comentario" and tarefa["origem"] == "automatica" and posteriores >= LANCES_PARA_SUPERAR:
                gravar("ignorada", erro="Comentário superado por lances mais recentes. Peça novamente no histórico.")
                return
            async with asyncio.timeout(PRAZO_EXPLICACAO):
                resultado = await self._gerar(tarefa, lance, jogo.dificuldade)
        except TimeoutError:
            LOGGER.info("Explicação do lance %s excedeu o prazo. Usando apoio do Stockfish.", contexto["indice"])
            resultado = await self._gerar(tarefa, lance, jogo.dificuldade, usar_modelo=False)
        except HTTPException as erro:
            self._reagendar(tarefa, erro.detail, gravar)
            return
        except asyncio.CancelledError:
            if self._encerrando:
                # Encerramento da API: a tarefa volta para a fila no próximo início.
                with closing(db.conectar()) as conn, conn:
                    conn.execute("UPDATE explicacoes_jogo SET status='pendente' WHERE id=? AND status='em_andamento'",
                                 (tarefa["id"],))
            else:
                gravar("cancelada", erro="Cancelada pelo jogador.")
            raise
        except Exception as erro:
            LOGGER.warning("Explicação do jogo falhou (%s)", type(erro).__name__)
            self._reagendar(tarefa, "O treinador não conseguiu concluir a explicação.", gravar)
            return
        if not resultado["validada"]:
            gravar("erro", resultado, "Não foi possível validar uma explicação para este lance.")
            return
        gravar("concluida", resultado)
        LOGGER.info("Explicação do lance %s concluída (%s, %d ms)", contexto["indice"], resultado["fonte"],
                    round((perf_counter() - inicio) * 1000))

    def _reagendar(self, tarefa: dict, mensagem: str, gravar) -> None:
        if tarefa["tentativas"] < MAX_TENTATIVAS_TAREFA:
            with closing(db.conectar()) as conn, conn:
                conn.execute("UPDATE explicacoes_jogo SET status='pendente', erro=? WHERE id=? AND status='em_andamento'",
                             (mensagem, tarefa["id"]))
            self.acordar()
        else:
            gravar("erro", erro=mensagem)

    async def _gerar(self, tarefa: dict, lance: LanceJogo, dificuldade: str, *, usar_modelo: bool = True) -> dict:
        contexto = tarefa["contexto"]
        avaliacao = lance.avaliacao.model_dump()
        forcar = bool(contexto.get("forcar"))
        status = await status_llm() if usar_modelo else None
        dados = {**contexto, "tipo": tarefa["tipo"], "linha_motor": avaliacao["linha_motor"]}
        treino = {"linguagem": LINGUAGEM_POR_NIVEL[dificuldade], "classe": dados["classe"],
                  "lance_jogado": lance.san, "melhor_alternativa": dados["melhor_lance"],
                  "variante_verificada": dados["linha_motor"]}
        cache = False
        if status is None or not status.disponivel:
            resposta = await explicacao_do_motor(dados)
        elif tarefa["tipo"] == "explicacao":
            resposta = await services.explicacao(lance.fen_antes, lance.san, self.fila_llm, analise=avaliacao,
                                                 forcar=forcar, treino=treino)
            cache = bool(resposta.get("cache"))
        else:
            perfil = perfil_comentario() + ":" + sha256(repr((avaliacao, treino)).encode()).hexdigest()
            with closing(db.conectar()) as conn:
                salvo = None if forcar else db.obter_explicacao(conn, lance.fen_antes, lance.san, perfil)
            if salvo is not None:
                resposta, cache = salvo, True
            else:
                async with self.fila_llm:
                    resposta = await comentar_bom_lance_async(lance.fen_antes, lance.san, avaliacao["melhor_lance"],
                                                              avaliacao["linha_motor"], treino=treino)
                if resposta["validada"] and not resposta["fallback"]:
                    with closing(db.conectar()) as conn:
                        db.salvar_explicacao(conn, lance.fen_antes, lance.san, resposta, perfil)
        if not resposta["validada"]:
            resposta = await explicacao_do_motor(dados)
        qwen = status is not None and status.disponivel and resposta["validada"] and not resposta["fallback"]
        return {
            **{campo: resposta[campo] for campo in ("tema", "tema_label", "texto", "ficha", "ferramentas_usadas",
                                                    "tentativas", "validada", "fallback")},
            "fen": lance.fen_antes, "lance_jogado": lance.san, "melhor_lance": avaliacao["melhor_lance"],
            "melhor_lance_uci": avaliacao["melhor_lance_uci"], "classe": avaliacao["classe"],
            "queda": avaliacao["queda"], "cache": cache, "tipo": tarefa["tipo"],
            "fonte": "qwen3" if qwen else "motor", "modelo": status.modelo if qwen else None,
        }


FILA: FilaTreinador | None = None


def acordar_fila() -> None:
    if FILA is not None:
        FILA.acordar()


async def iniciar_fila(fila_llm: asyncio.Semaphore) -> FilaTreinador:
    global FILA
    FILA = FilaTreinador(fila_llm)
    await FILA.iniciar()
    return FILA


async def encerrar_fila() -> None:
    global FILA
    if FILA is not None:
        await FILA.encerrar()
        FILA = None


# Dicas em etapas -------------------------------------------------------------

def _dicas(jogo_id: str, versao: int | None = None) -> list[dict]:
    with closing(db.conectar()) as conn:
        consulta = "SELECT dados FROM dicas_jogo WHERE jogo_id=?" + (" AND versao=?" if versao is not None else "")
        parametros = (jogo_id, versao) if versao is not None else (jogo_id,)
        linhas = conn.execute(consulta + " ORDER BY versao, nivel", parametros).fetchall()
    return [json.loads(linha["dados"]) for linha in linhas]


def _posicao_atual(id_: str, versao: int) -> JogoSalvo:
    jogo, processando = repositorio.obter(id_)
    if not jogo.configuracoes.modo_treinador:
        raise HTTPException(409, "O modo treinador está desativado nesta partida.")
    if processando or jogo.versao != versao:
        raise HTTPException(409, "A posição mudou. Atualize a partida antes de pedir ajuda.")
    if jogo.status != "em_andamento":
        raise HTTPException(409, "A partida já foi encerrada.")
    if chess.COLOR_NAMES[servico.reproduzir(jogo).turn] != jogo.cor_do_jogador:
        raise HTTPException(409, "Aguarde a jogada do Stockfish.")
    return jogo


async def _analise_para_dica(fen: str) -> dict:
    chave = f"dica:{perfil_analise()}:{fen}"
    with closing(db.conectar()) as conn:
        linha = conn.execute("SELECT dados FROM cache_mcp WHERE chave=?", (chave,)).fetchone()
    if linha:
        return json.loads(linha["dados"])
    analise = await servico.mcp_motor("analisar_posicao", fen=fen, profundidade=14, multipv=3)
    with closing(db.conectar()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO cache_mcp VALUES (?, ?, ?)", (chave, time(), json.dumps(analise)))
    return analise


async def dica(id_: str, versao: int, nivel: int) -> dict:
    """Primeiro o objetivo, depois a peça ou casa, e só então o lance do Stockfish."""
    jogo = _posicao_atual(id_, versao)
    anteriores = {item["nivel"]: item for item in _dicas(id_, versao)}
    if nivel in anteriores:
        return anteriores[nivel]
    if nivel > 1 and nivel - 1 not in anteriores:
        raise HTTPException(409, "Peça as dicas anteriores antes desta etapa.")
    inicio = perf_counter()
    try:
        async with asyncio.timeout(repositorio.PRAZO_MOTOR):
            analise = await _analise_para_dica(jogo.fen)
        diagnostico = diagnosticar_dica(jogo.fen, analise)
    except TimeoutError as erro:
        raise HTTPException(504, "O Stockfish excedeu o prazo da dica.") from erro
    except (ValueError, KeyError, TypeError) as erro:
        raise HTTPException(503, "O Stockfish não devolveu uma análise utilizável para a dica.") from erro
    texto = diagnostico["niveis"][nivel]
    if nivel == 3:
        validacao = await validar_resposta_async(texto, jogo.fen, diagnostico["linha"], validar_lances=_validar_local)
        if not validacao["valida"]:
            raise HTTPException(503, "O lance sugerido não passou na validação.")
    ficha = conceito = None
    if nivel == 1 and diagnostico["tema"] != "outro":
        if completa := await ficha_do_tema(diagnostico["tema"]):
            ficha = {campo: completa[campo] for campo in ("id", "titulo", "arquivo")}
            conceito = secao_reconhecer(completa)
    _posicao_atual(id_, versao)
    registro = {
        "jogo_id": id_, "versao": versao, "fen": jogo.fen, "nivel": nivel, "texto": texto,
        "tipo": diagnostico["tipo"], "tema": diagnostico["tema"], "tema_label": diagnostico["tema_label"],
        "casa": diagnostico["casa"] if nivel >= 2 else None, "lance": diagnostico["lance"] if nivel == 3 else None,
        "ficha": ficha, "conceito": conceito, "fonte": "stockfish", "criado_em": db.agora(),
        "duracao_ms": round((perf_counter() - inicio) * 1000),
    }
    with closing(db.conectar()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO dicas_jogo VALUES (?, ?, ?, ?, ?, ?)",
                     (id_, versao, nivel, jogo.fen, json.dumps(registro, ensure_ascii=False), registro["criado_em"]))
    return registro


# Chat contextual ---------------------------------------------------------------

def _tema_validado(jogo_id: str, indice: int) -> str | None:
    item = next((e for e in listar(jogo_id) if e["indice"] == indice), None)
    resultado = (item or {}).get("resultado") or {}
    return resultado.get("tema") if resultado.get("fonte") == "qwen3" else None


async def chat(id_: str, entrada: PerguntaJogo, fila_llm: asyncio.Semaphore) -> dict:
    """Responde sempre sobre a posição confirmada no servidor, nunca sobre um FEN antigo do cliente."""
    jogo, processando = repositorio.obter(id_)
    if not jogo.configuracoes.modo_treinador:
        raise HTTPException(409, "O modo treinador está desativado nesta partida.")
    if processando or entrada.versao != jogo.versao:
        raise HTTPException(409, "A posição mudou enquanto você escrevia. Atualize a partida e pergunte de novo.")
    if entrada.indice is not None:
        selecionado = servico.lance_do_jogador(jogo, entrada.indice)
    else:
        selecionado = next((l for l in reversed(jogo.lances) if l.autor == "jogador"), None)
    if entrada.posicao == "apos_lance" and selecionado is None:
        raise HTTPException(422, "Escolha um lance seu para conversar sobre a posição depois dele.")
    fen = selecionado.fen_depois if entrada.posicao == "apos_lance" else jogo.fen
    inicio = perf_counter()
    base = {"jogo_id": id_, "versao": jogo.versao, "fen": fen, "indice": selecionado.indice if selecionado else None,
            "lance": selecionado.san if selecionado else None, "pergunta": entrada.pergunta}

    def tempo() -> int:
        return round((perf_counter() - inicio) * 1000)

    intencao = intencao_historico(entrada.pergunta)
    if intencao == "situacao":
        async with servico.prazo_motor():
            analise = await _analise_para_dica(fen)
        avaliacao = normalizar_avaliacao(analise, jogo.cor_do_jogador)
        if avaliacao["tipo"] == "mate":
            texto = ("O Stockfish encontrou mate a seu favor na linha analisada."
                     if avaliacao["a_favor"] else "O Stockfish encontrou mate a favor do adversário na linha analisada.")
        else:
            valor = avaliacao["valor"]
            estado = "favorável" if valor >= 50 else "desfavorável" if valor <= -50 else "aproximadamente equilibrada"
            texto = f"O Stockfish considera esta posição {estado} para você ({valor:+d} centipeões da sua perspectiva)."
        return {**base, "resposta": texto, "ferramentas_usadas": [{"nome": "analisar_posicao", "argumentos": {"fen": fen}}],
                "validada": True, "status": "ok", "fallback": False, "fonte": "motor", "duracao_ms": tempo()}
    if intencao:
        lances = jogo.lances[:selecionado.indice] if entrada.posicao == "apos_lance" else jogo.lances
        lances = [lance.model_dump() for lance in lances]
        texto, citacoes = resposta_historico(intencao, lances, jogo.cor_do_jogador,
                                             selecionado.model_dump() if selecionado else None)
        valida = await validar_citacoes(texto, citacoes, _validar_local)
        return {**base, "resposta": texto if valida else "Não foi possível confirmar a resposta no histórico.",
                "ferramentas_usadas": [{"nome": "historico_da_partida", "argumentos": {"intencao": intencao}},
                                       {"nome": "validar_lances", "argumentos": {"citacoes": len(citacoes)}}],
                "validada": valida, "status": "ok" if valida else "indisponivel", "fallback": False,
                "fonte": "historico" if valida else "indisponivel", "duracao_ms": tempo()}
    if (tipo := peca_da_pergunta(entrada.pergunta)) is not None:
        return {**base, "resposta": resposta_ameaca(fen, jogo.cor_do_jogador, tipo),
                "ferramentas_usadas": [{"nome": "regras_do_xadrez", "argumentos": {"peca": chess.piece_name(tipo)}}],
                "validada": True, "status": "ok", "fallback": False, "fonte": "regras", "duracao_ms": tempo()}
    if pergunta_tatica(entrada.pergunta):
        if chess.COLOR_NAMES[chess.Board(fen).turn] != jogo.cor_do_jogador or jogo.status != "em_andamento":
            texto = "Só analiso oportunidades táticas na sua vez, durante a partida."
        else:
            try:
                async with asyncio.timeout(repositorio.PRAZO_MOTOR):
                    texto = resposta_tatica(diagnosticar_dica(fen, await _analise_para_dica(fen)))
            except (TimeoutError, ValueError, KeyError, TypeError) as erro:
                raise HTTPException(503, "O Stockfish não respondeu a tempo.") from erro
        return {**base, "resposta": texto, "ferramentas_usadas": [{"nome": "analisar_posicao", "argumentos": {"fen": fen}}],
                "validada": True, "status": "ok", "fallback": False, "fonte": "motor", "duracao_ms": tempo()}
    if pergunta_desenvolvimento(entrada.pergunta) and not tema_do_conceito(entrada.pergunta):
        return {**base, "resposta": resposta_desenvolvimento(fen, jogo.cor_do_jogador),
                "ferramentas_usadas": [{"nome": "regras_do_xadrez", "argumentos": {"tema": "desenvolvimento"}}],
                "validada": True, "status": "ok", "fallback": False, "fonte": "regras", "duracao_ms": tempo()}
    status = await status_llm()
    if tema := tema_do_conceito(entrada.pergunta):
        if status.disponivel:
            async with asyncio.timeout(PRAZO_EXPLICACAO), fila_llm:
                conceito = await explicar_conceito_async(tema, entrada.pergunta)
        else:
            conceito = await explicar_conceito_async_sem_modelo(tema)
        fonte = "ficha" if conceito["fallback"] else "qwen3" if conceito["validada"] else "indisponivel"
        return {**base, "resposta": conceito["resposta"], "ferramentas_usadas": conceito["ferramentas_usadas"],
                "validada": conceito["validada"], "status": "ok" if conceito["validada"] else "indisponivel",
                "fallback": conceito["fallback"], "fonte": fonte, "duracao_ms": tempo()}
    if not status.disponivel:
        return {**base, "resposta": "O treinador está indisponível no momento. A partida continua com o Stockfish, "
                                    "e as perguntas sobre o histórico seguem disponíveis.",
                "ferramentas_usadas": [], "validada": False, "status": "indisponivel", "fallback": False,
                "fonte": "indisponivel", "duracao_ms": tempo()}
    contexto = {}
    if selecionado is not None and selecionado.avaliacao is not None:
        contexto["lance_selecionado"] = contexto_do_lance(selecionado.model_dump(), fen,
                                                          _tema_validado(id_, selecionado.indice))
    try:
        async with asyncio.timeout(PRAZO_EXPLICACAO), fila_llm:
            resposta = await responder_chat_async(
                fen, entrada.pergunta, [m.model_dump() for m in entrada.historico], **contexto,
                treino={"cor_do_jogador": jogo.cor_do_jogador, "linguagem": LINGUAGEM_POR_NIVEL[jogo.dificuldade]},
            )
    except TimeoutError as erro:
        raise HTTPException(504, "O prazo do chat foi excedido.") from erro
    fonte = "motor" if resposta.get("fallback") else "qwen3" if resposta["validada"] else "indisponivel"
    return {**base, **resposta, "status": "ok" if resposta["validada"] else "indisponivel", "fonte": fonte,
            "duracao_ms": tempo()}


async def explicar_conceito_async_sem_modelo(tema: str) -> dict:
    """Sem LLM, devolve apenas o trecho de definição da ficha, identificado como tal."""
    ficha = await ficha_do_tema(tema)
    if not ficha:
        return {"resposta": "A ficha desse conceito não está disponível no momento.", "validada": False,
                "fallback": False, "ferramentas_usadas": [{"nome": "buscar_conceitos", "argumentos": {"tema": tema}}]}
    trecho = re.search(r"^## Definição\n(.*?)(?=^## |\Z)", ficha["texto"], flags=re.M | re.S)
    definicao = trecho.group(1).strip() if trecho else ""
    return {"resposta": f"Pela ficha {ficha['titulo']}: {definicao}" if definicao else "A ficha não tem definição.",
            "validada": bool(definicao), "fallback": True,
            "ferramentas_usadas": [{"nome": "buscar_conceitos", "argumentos": {"tema": tema}}]}


# Relatório da partida -------------------------------------------------------------

def _fases(avaliados: list[LanceJogo]) -> list[dict]:
    if not avaliados:
        return []
    partes = min(3, len(avaliados))
    tamanho, resto = divmod(len(avaliados), partes)
    fases, inicio = [], 0
    for posicao, nome in enumerate(("inicio", "meio", "fim")[:partes]):
        fim = inicio + tamanho + (1 if posicao < resto else 0)
        grupo = avaliados[inicio:fim]
        classes = Counter(l.avaliacao.classe for l in grupo)
        fases.append({"fase": nome, "primeiro_lance": grupo[0].numero, "ultimo_lance": grupo[-1].numero,
                      "lances": len(grupo), "precisao": round(100 - mean(max(0, l.avaliacao.queda) for l in grupo), 1),
                      "imprecisoes": classes["imprecisao"], "erros": classes["erro"],
                      "erros_graves": classes["erro_grave"]})
        inicio = fim
    return fases


async def relatorio(id_: str) -> dict:
    jogo, _ = repositorio.obter(id_)
    meus = [l for l in jogo.lances if l.autor == "jogador"]
    avaliados = [l for l in meus if l.avaliacao]
    explicacoes = {item["indice"]: item for item in listar(id_)}
    criticos = sorted((l for l in avaliados if l.avaliacao.classe != "aceitavel"),
                      key=lambda l: -l.avaliacao.queda)[:10]
    temas: dict[str, dict] = {}
    for lance in avaliados:
        resultado = (explicacoes.get(lance.indice) or {}).get("resultado") or {}
        if (lance.avaliacao.classe != "aceitavel" and resultado.get("fonte") == "qwen3" and resultado.get("validada")
                and resultado.get("tema") not in (None, "outro")):
            item = temas.setdefault(resultado["tema"], {"tema": resultado["tema"], "tema_label": resultado["tema_label"],
                                                        "ocorrencias": 0, "indices": []})
            item["ocorrencias"] += 1
            item["indices"].append(lance.indice)
    ranking = sorted(temas.values(), key=lambda t: (-t["ocorrencias"], t["tema"]))
    fases = _fases(avaliados)
    classes = Counter(l.avaliacao.classe for l in avaliados)
    dicas = _dicas(id_)
    niveis = Counter(f"nivel_{d['nivel']}" for d in dicas)
    dificuldades, recomendacoes = [], []
    if not avaliados:
        dificuldades.append("Nenhum lance foi avaliado, então não há dados para apontar dificuldades.")
    for tema in ranking[:3]:
        vezes = "lance" if tema["ocorrencias"] == 1 else "lances"
        dificuldades.append(f"Em {tema['ocorrencias']} {vezes}, a explicação validada apontou o tema {tema['tema_label'].lower()}.")
        recomendacoes.append(f"Resolva puzzles de {tema['tema_label'].lower()} para reconhecer esse padrão mais cedo.")
    if classes["erro_grave"]:
        dificuldades.append(f"Houve {classes['erro_grave']} erro(s) grave(s), com grande perda de chance de vitória.")
        recomendacoes.append("Antes de cada lance, faça uma revisão breve de xeques, capturas e ameaças dos dois lados.")
    erros_por_fase = {f["fase"]: f["erros"] + f["erros_graves"] for f in fases}
    if len(fases) == 3 and max(erros_por_fase.values()) >= 2:
        pior = max(fases, key=lambda f: (erros_por_fase[f["fase"]], f["fase"] == "fim"))
        if sorted(erros_por_fase.values())[-1] > sorted(erros_por_fase.values())[-2]:
            nome = {"inicio": "começo", "meio": "meio", "fim": "fim"}[pior["fase"]]
            dificuldades.append(f"Seus erros se concentraram no {nome} da partida.")
            recomendacoes.append(f"Revise os lances críticos do {nome} da partida com o treinador.")
    if niveis["nivel_3"] >= 2:
        recomendacoes.append("Tente resolver a posição com as duas primeiras dicas antes de revelar o lance sugerido.")
    sem_tema = sum(1 for l in avaliados if l.avaliacao.classe in {"erro", "erro_grave", "imprecisao"}
                   and not any(l.indice in t["indices"] for t in ranking))
    if sem_tema:
        dificuldades.append(f"{sem_tema} lance(s) com imprecisão ou erro ainda sem tema tático confirmado. "
                            "Abra as explicações desses lances para entender o que mudou.")
    if avaliados and not (classes["imprecisao"] or classes["erro"] or classes["erro_grave"]):
        dificuldades.append("Nenhum dos seus lances avaliados foi classificado como imprecisão ou erro.")
    if not recomendacoes:
        recomendacoes.append("Continue jogando com o treinador ativo para acumular dados sobre o seu jogo.")
    minimo, maximo = FAIXAS_PUZZLES[jogo.dificuldade]
    tags = list(dict.fromkeys(TAGS[t["tema"]] for t in ranking if t["tema"] in TAGS))[:3]
    puzzles, aviso = [], None
    if avaliados:
        try:
            puzzles = await services.mcp("buscar_puzzles", temas=tags, rating_min=minimo, rating_max=maximo)
            if not puzzles:
                aviso = f"Nenhum puzzle do recorte local corresponde à faixa {minimo}–{maximo}."
        except HTTPException as erro:
            aviso = erro.detail
    status_analise = None
    if jogo.partida_analise_id:
        with closing(db.conectar()) as conn:
            if partida := db.obter_partida(conn, jogo.partida_analise_id):
                status_analise = partida["status_analise"]
    estados = Counter(item["status"] for item in explicacoes.values())
    fontes = Counter((item.get("resultado") or {}).get("fonte") for item in explicacoes.values()
                     if item["status"] == "concluida")
    return {
        "id": jogo.id, "status": jogo.status, "resultado": jogo.resultado, "motivo": jogo.motivo,
        "cor_do_jogador": jogo.cor_do_jogador, "dificuldade": jogo.dificuldade,
        "modo_assistencia": jogo.configuracoes.modo_assistencia, "total_meios_lances": len(jogo.lances),
        "lances_do_jogador": len(meus), "estatisticas": servico.estatisticas(jogo),
        "lances_criticos": [{
            "indice": l.indice, "numero": l.numero, "san": l.san, "classe": l.avaliacao.classe,
            "queda": l.avaliacao.queda, "melhor_lance": l.avaliacao.melhor_lance, "fen_antes": l.fen_antes,
            "explicacao_status": (explicacoes.get(l.indice) or {}).get("status"),
            "tema_label": ((explicacoes.get(l.indice) or {}).get("resultado") or {}).get("tema_label"),
        } for l in criticos],
        "temas": ranking, "dificuldades": dificuldades, "evolucao": fases,
        "dicas_usadas": {"total": len(dicas), "nivel_1": niveis["nivel_1"], "nivel_2": niveis["nivel_2"],
                         "nivel_3": niveis["nivel_3"]},
        "explicacoes": {"qwen3": fontes["qwen3"], "motor": fontes["motor"],
                        "pendentes": estados["pendente"] + estados["em_andamento"],
                        "ignoradas": estados["ignorada"], "falhas": estados["erro"], "canceladas": estados["cancelada"]},
        "recomendacoes": recomendacoes, "puzzles": puzzles, "puzzles_por_tema": bool(tags), "aviso_puzzles": aviso,
        "partida_analise_id": jogo.partida_analise_id, "status_analise": status_analise,
    }


# Métricas de desempenho ---------------------------------------------------------

def _metrica(valores: list[int]) -> dict:
    return {"amostras": len(valores), "media_ms": round(mean(valores), 1) if valores else None,
            "mediana_ms": float(median(valores)) if valores else None, "maximo_ms": max(valores) if valores else None}


def metricas() -> dict:
    adversario, avaliacao = [], []
    with closing(db.conectar()) as conn:
        for linha in conn.execute("SELECT dados FROM jogos"):
            for lance in json.loads(linha["dados"]).get("lances", []):
                tempos = lance.get("tempos") or {}
                if "adversario_ms" in tempos:
                    adversario.append(tempos["adversario_ms"])
                if "avaliacao_ms" in tempos:
                    avaliacao.append(tempos["avaliacao_ms"])
        explicacoes = conn.execute("""SELECT json_extract(dados,'$.fonte') AS fonte, json_extract(dados,'$.cache') AS cache,
                                      duracao_ms FROM explicacoes_jogo WHERE status='concluida'""").fetchall()
        dicas = [json.loads(l["dados"])["duracao_ms"] for l in conn.execute("SELECT dados FROM dicas_jogo")]
    gerados = [linha for linha in explicacoes if not linha["cache"] and linha["duracao_ms"] is not None]
    return {
        "adversario": _metrica(adversario), "avaliacao": _metrica(avaliacao),
        "explicacao_qwen3": _metrica([l["duracao_ms"] for l in gerados if l["fonte"] == "qwen3"]),
        "explicacao_motor": _metrica([l["duracao_ms"] for l in gerados if l["fonte"] == "motor"]),
        "dica": _metrica(dicas),
    }
