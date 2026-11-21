"""Ferramentas do motor: avaliação de posições e partidas com o Stockfish.

O binário é acionado pelo ``python-chess`` via UCI (caminho em ``STOCKFISH_PATH``).
Uma única instância do motor deve ser reaproveitada entre chamadas, com limite
de tempo por posição.
"""

import atexit
import json
from concurrent.futures import Future
import os
from threading import Lock, Thread
from time import time
from shutil import which

from agent.classifier import chance_de_vitoria, classificar_queda
from backend.db import abrir_cache

import chess
import chess.engine

from mcp_server.tools.board import _ler_fen, _notacao
from mcp_server.tools.pgn import ler_partida

# O cliente MCP espera até 20 s. Fila, inicialização, busca e margem UCI
# somam até 18 s, mesmo na primeira análise sem motor reaproveitado.
_TEMPO_FILA = 2.0
_TEMPO_UCI = 3.0
_TEMPO_BUSCA = 10.0
_acesso_motor = Lock()
_motor_ativo: tuple[str, chess.engine.SimpleEngine] | None = None


def _abrir_motor(caminho: str) -> chess.engine.SimpleEngine:
    resultado: Future[chess.engine.SimpleEngine] = Future()

    def iniciar() -> None:
        try:
            resultado.set_result(chess.engine.SimpleEngine.popen_uci(caminho, timeout=_TEMPO_UCI))
        except Exception as erro:
            resultado.set_exception(erro)

    # A thread interna do python-chess herda daemon e permite chegar ao atexit.
    Thread(target=iniciar, name="iniciar-stockfish", daemon=True).start()
    return resultado.result()


def _encerrar_motor(*, aguardar: bool = False) -> None:
    global _motor_ativo
    if _motor_ativo is not None:
        _, motor = _motor_ativo
        _motor_ativo = None
        motor.close()
        if aguardar:
            try:
                motor.returncode.result(timeout=_TEMPO_UCI)
            except TimeoutError:
                pass


atexit.register(_encerrar_motor, aguardar=True)


def _consultar_motor(tabuleiro: chess.Board, profundidade: int, multipv: int) -> list[chess.engine.InfoDict]:
    global _motor_ativo
    caminho = os.getenv("STOCKFISH_PATH")
    if not caminho:
        raise RuntimeError("Configure STOCKFISH_PATH com o executável do Stockfish.")
    if not _acesso_motor.acquire(timeout=_TEMPO_FILA):
        raise TimeoutError("Tempo limite na fila do Stockfish.")
    try:
        if _motor_ativo is not None and (_motor_ativo[0] != caminho or _motor_ativo[1].returncode.done()):
            _encerrar_motor()
        if _motor_ativo is None:
            motor = _abrir_motor(caminho)
            _motor_ativo = (caminho, motor)
            if "stockfish" not in motor.id.get("name", "").lower():
                raise chess.engine.EngineError("O executável UCI não se identificou como Stockfish.")
        else:
            _, motor = _motor_ativo
        return motor.analyse(
            tabuleiro, chess.engine.Limit(depth=profundidade, time=_TEMPO_BUSCA), multipv=multipv,
            game=object(), info=chess.engine.INFO_SCORE | chess.engine.INFO_PV,
        )
    except TimeoutError as erro:
        _encerrar_motor()
        raise TimeoutError("Tempo limite na comunicação UCI com o Stockfish.") from erro
    except (OSError, chess.engine.EngineError) as erro:
        _encerrar_motor()
        raise RuntimeError(f"Falha no Stockfish: {erro}") from erro
    finally:
        _acesso_motor.release()


def _pontuacao(info: chess.engine.InfoDict, turno: chess.Color) -> dict:
    score = info.get("score")
    if score is None:
        raise RuntimeError("O Stockfish não retornou a avaliação da posição.")
    relativo = score.pov(turno)
    mate = relativo.mate()
    if mate is not None:
        return {"tipo": "mate", "valor": mate, "a_favor": relativo > chess.engine.Cp(0)}
    return {"tipo": "cp", "valor": relativo.score()}


def analisar_posicao(fen: str, profundidade: int = 18, multipv: int = 3) -> dict:
    """Avalia uma posição com o Stockfish.

    Args:
        fen: posição em notação FEN.
        profundidade: profundidade máxima da busca (padrão 18). O limite
            de tempo pode encerrar a busca antes da profundidade pedida.
        multipv: quantidade de melhores lances solicitados (padrão 3).

    Returns:
        dict com:
            - ``perspectiva``: lado a jogar, ``white`` ou ``black``;
            - ``avaliacao``: ``tipo`` e ``valor`` em centipeões (``cp``) ou
              distância assinada de mate (``mate``), com ``a_favor`` no mate;
            - ``melhores_lances``: candidatos em ordem MultiPV, com ``san``,
              ``uci``, ``avaliacao`` e ``linha`` em SAN, na mesma perspectiva;
            - ``linha_principal``: sequência de lances (SAN) da variante principal.
        Xeque-mate e afogamento têm avaliação e listas de lances vazias.

    Raises:
        ValueError: FEN ou parâmetros inválidos.
        RuntimeError: motor indisponível ou resposta UCI insuficiente.
        TimeoutError: fila ou comunicação UCI excedeu o limite.
    """
    tabuleiro = _ler_fen(fen)
    if type(profundidade) is not int or profundidade < 1 or type(multipv) is not int or multipv < 1:
        raise ValueError("Profundidade e multipv devem ser inteiros positivos.")
    lances_legais = tabuleiro.legal_moves.count()
    dados = _consultar_motor(tabuleiro, profundidade, max(1, min(multipv, lances_legais)))
    avaliacao = _pontuacao(dados[0] if dados else {}, tabuleiro.turn)
    variantes = []
    if lances_legais:
        for info in dados:
            linha = info.get("pv")
            if not linha:
                raise RuntimeError("O Stockfish não retornou a variante solicitada.")
            posicao = tabuleiro.copy(stack=False)
            linha_san = []
            for lance in linha:
                linha_san.append(posicao.san(lance))
                posicao.push(lance)
            variantes.append({**_notacao(tabuleiro, linha[0]), "avaliacao": _pontuacao(info, tabuleiro.turn),
                              "linha": linha_san})
    return {
        "perspectiva": chess.COLOR_NAMES[tabuleiro.turn],
        "avaliacao": avaliacao,
        "melhores_lances": variantes,
        "linha_principal": variantes[0]["linha"] if variantes else [],
    }


def perfil_analise() -> str:
    """Assinatura do perfil de partida, separada da análise interativa."""
    return f"v1:depth={_profundidade_partida()}:motor={os.getenv('ANALISE_REVISAO_MOTOR', '1')}"


def _profundidade_partida() -> int:
    profundidade = int(os.getenv("ANALISE_PROFUNDIDADE") or 12)
    if not 1 <= profundidade <= 24:
        raise ValueError("ANALISE_PROFUNDIDADE deve estar entre 1 e 24.")
    return profundidade


def normalizar_avaliacao(analise: dict, cor: str) -> dict:
    avaliacao = analise["avaliacao"]
    if analise["perspectiva"] == cor:
        return avaliacao
    invertida = {**avaliacao, "valor": -avaliacao["valor"]}
    if avaliacao["tipo"] == "mate":
        invertida["a_favor"] = not avaliacao["a_favor"]
    return invertida


def _chance(avaliacao: dict) -> float:
    if avaliacao["tipo"] == "mate":
        return chance_de_vitoria(None, mate=1 if avaliacao["a_favor"] else -1)
    return chance_de_vitoria(avaliacao["valor"])


def dados_classificacao(antes: dict, depois: dict, cor: str) -> dict:
    anterior, posterior = (normalizar_avaliacao(a, cor) for a in (antes, depois))
    chance_antes, chance_depois = _chance(anterior), _chance(posterior)
    queda = chance_antes - chance_depois
    return {
        "avaliacao_antes": anterior, "avaliacao_depois": posterior, "perspectiva": cor,
        "cp_antes": anterior["valor"] if anterior["tipo"] == "cp" else None,
        "cp_depois": posterior["valor"] if posterior["tipo"] == "cp" else None,
        "chance_vitoria_antes": chance_antes, "chance_vitoria_depois": chance_depois,
        "queda": queda, "classe": classificar_queda(queda),
    }


def analisar_partida(pgn: str, cor_do_jogador: str, inicio: int = 0, limite: int | None = None) -> list[dict]:
    """Analisa um PGN com o Stockfish na perspectiva de quem fez cada lance.

    A cor é white ou black. Use ambas para a linha completa do tabuleiro.
    inicio e limite recortam os meios-lances do PGN, com início zero.
    As avaliações preservam cp ou mate e a variante recomendada usa SAN.
    """
    if cor_do_jogador not in {"white", "black", "ambas"}:
        raise ValueError("Cor inválida. Use white, black ou ambas.")
    if inicio < 0 or limite is not None and limite < 1:
        raise ValueError("Intervalo de meios-lances inválido.")
    jogo = ler_partida(pgn)
    lances = list(jogo.mainline_moves())
    fim = len(lances) if limite is None else min(inicio + limite, len(lances))
    tabuleiro = jogo.board()
    for lance in lances[:inicio]:
        tabuleiro.push(lance)
    caminho = which(os.getenv("STOCKFISH_PATH") or "")
    motor = os.stat(caminho) if caminho else None
    assinatura = f"posicao:{perfil_analise()}:{caminho}:{motor.st_mtime_ns if motor else 0}:"
    profundidade = _profundidade_partida()
    with abrir_cache() as conn:
        def avaliar(fen: str) -> dict:
            chave = assinatura + fen
            cache = conn.execute("SELECT dados FROM cache_mcp WHERE chave=?", (chave,)).fetchone()
            if cache:
                return json.loads(cache["dados"])
            dados = analisar_posicao(fen, profundidade, 1)
            with conn:
                conn.execute("INSERT OR IGNORE INTO cache_mcp VALUES (?, ?, ?)", (chave, time(), json.dumps(dados)))
            return dados

        resultado = []
        for indice in range(inicio, fim):
            lance = lances[indice]
            cor = chess.COLOR_NAMES[tabuleiro.turn]
            fen_antes = tabuleiro.fen()
            san, uci, numero = tabuleiro.san(lance), tabuleiro.uci(lance), tabuleiro.fullmove_number
            tabuleiro.push(lance)
            if cor_do_jogador != "ambas" and cor != cor_do_jogador:
                continue
            fen_depois = tabuleiro.fen()
            antes, depois = avaliar(fen_antes), avaliar(fen_depois)
            linha = antes["linha_principal"]
            resultado.append({
                "indice": indice + 1, "numero": numero, "cor": cor, "san": san, "uci": uci,
                "fen_antes": fen_antes, "fen_depois": fen_depois, **dados_classificacao(antes, depois, cor),
                "melhor_lance": linha[0], "melhor_lance_uci": antes["melhores_lances"][0]["uci"],
                "linha_motor": linha,
            })
        return resultado
