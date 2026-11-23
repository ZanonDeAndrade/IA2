"""Treinador do modo Jogar contra IA: comentários, dicas e respostas sobre a partida.

Reaproveita o adaptador de LLM, o validador, as fichas RAG e as evidências
táticas do agente. Os grafos usados pelo experimento A/B/C continuam
intactos: este módulo apenas os importa.

Responsabilidades:
    - ``comentar_bom_lance_async``: comenta um lance aceitável. O LLM escolhe
      entre fatos calculados com ``python-chess`` e redige a lição com base
      na ficha recuperada. O validador confere qualquer lance citado.
    - ``diagnosticar_dica``: dicas em três níveis construídas somente com a
      análise do Stockfish e as regras do xadrez. O LLM não participa, para
      não inventar ameaças ou combinações.
    - ``responder_sobre_partida``: respostas verificáveis sobre o histórico
      (maior erro, melhor alternativa, perda de material, situação).
"""

from functools import lru_cache
import json
import logging
from pathlib import Path
import re
from typing import TypedDict
import unicodedata

import chess
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph

from agent.classifier import chance_de_vitoria
from agent.graph import (
    TEMAS, _AVALIACAO_NUMERICA, _contexto, _invocar, _licoes_da_ficha, _modelo, _prompt, _texto_conceitual,
)
from agent.mcp import Ferramentas, sessao_mcp
from agent.taticas import NOMES, VALORES, _troca, candidatos_taticos, justificar_alternativa
from agent.validator import extrair_lances, ler_fen, validar_resposta_async

LOGGER = logging.getLogger(__name__)
MAX_TENTATIVAS = 3
ROTULOS = {**TEMAS, "roque": "Roque", "promocao": "Promoção"}
CLASSES = {"aceitavel": "aceitável", "imprecisao": "imprecisão", "erro": "erro", "erro_grave": "erro grave"}
_CENTRO = (chess.D4, chess.E4, chess.D5, chess.E5)
_FEMININO = {chess.ROOK, chess.QUEEN}
FORCA_MINIMA_DICA = 85
FATO_GERAL = "Segundo o Stockfish, o lance preservou suas chances na partida."


def _o(tipo: int) -> str:
    return "a" if tipo in _FEMININO else "o"


def _nome(tipo: int) -> str:
    return f"{_o(tipo)} {NOMES[tipo]}"


def _material(tabuleiro: chess.Board, cor: chess.Color) -> int:
    return sum(VALORES[peca.piece_type] for peca in tabuleiro.piece_map().values()
               if peca.color == cor and peca.piece_type != chess.KING)


def _controle_centro(tabuleiro: chess.Board, cor: chess.Color) -> int:
    return sum(len(tabuleiro.attackers(cor, casa)) + (tabuleiro.color_at(casa) == cor) for casa in _CENTRO)


def fatos_do_lance(fen: str, san: str, melhor_lance: str | None = None) -> list[dict]:
    """Fatos objetivos do lance jogado, na voz do treinador, sem coordenadas."""
    antes = ler_fen(fen)
    lance = antes.parse_san(san)
    cor = antes.turn
    peca = antes.piece_at(lance.from_square)
    depois = antes.copy(stack=False)
    depois.push(lance)
    fatos = []

    def fato(tema: str, frase: str) -> None:
        fatos.append({"tema": tema, "frase": frase})

    if depois.is_checkmate():
        fato("mate", "O lance aplica xeque-mate e encerra a partida.")
    if antes.is_castling(lance):
        fato("roque", "Você fez o roque, levando o rei para uma posição mais protegida e aproximando a torre do jogo.")
    if lance.promotion:
        fato("promocao", f"Você promoveu um peão a {NOMES[lance.promotion]}.")
    capturada = chess.PAWN if antes.is_en_passant(lance) else antes.piece_type_at(lance.to_square)
    if capturada:
        saldo = VALORES[capturada] - _troca(depois, lance.to_square)
        complemento = " e ganhou material na troca dessa casa" if saldo > 0 and not depois.is_checkmate() else ""
        adversario = "adversária" if capturada in _FEMININO else "adversário"
        fato("outro", f"Você capturou {_nome(capturada)} {adversario}{complemento}.")
    if depois.is_check() and not depois.is_checkmate():
        fato("outro", "O lance dá xeque e obriga o adversário a responder à ameaça ao rei.")
    linha_inicial = 0 if cor == chess.WHITE else 7
    if (peca.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(lance.from_square) == linha_inicial
            and antes.fullmove_number <= 15):
        fato("outro", f"Você desenvolveu {_nome(peca.piece_type)}, colocando mais uma peça em jogo.")
    if antes.fullmove_number <= 20 and _controle_centro(depois, cor) > _controle_centro(antes, cor):
        fato("outro", "O lance aumentou o seu controle sobre as casas centrais.")
    if (peca.piece_type != chess.KING and antes.is_attacked_by(not cor, lance.from_square)
            and not depois.is_attacked_by(not cor, lance.to_square)):
        fato("outro", "A peça movida saiu de uma casa onde estava sob ataque e foi para uma casa segura.")
    if melhor_lance:
        try:
            if antes.parse_san(melhor_lance) == lance:
                fato("coincide", "O lance coincide com a primeira escolha do Stockfish para a posição.")
        except ValueError:
            pass
    return fatos


def lance_informativo(fen: str, san: str, melhor_lance: str | None = None) -> bool:
    """Indica se há um fato pedagógico além da avaliação e da coincidência com o motor."""
    return any(fato["tema"] != "coincide" for fato in fatos_do_lance(fen, san, melhor_lance))


class EstadoComentario(TypedDict, total=False):
    treino: dict
    fen: str
    lance_jogado: str
    melhor_lance: str
    linha_motor: list[str]
    fatos: list[dict]
    tema: str
    ficha: dict | None
    escolhas: dict[str, list[str]]
    alternativa: str
    texto: str
    tentativas: int
    erros: list[str]
    pronto: bool
    validada: bool


def _ler_json(texto: str) -> dict:
    bruto = texto.strip()
    if bruto.startswith(("```json\n", "```\n")) and bruto.endswith("```"):
        bruto = bruto.split("\n", 1)[1][:-3].strip()
    dados = json.loads(bruto)
    if not isinstance(dados, dict):
        raise ValueError("Resposta sem objeto JSON.")
    return dados


def _uma_frase(frase) -> str:
    if not isinstance(frase, str) or not frase.strip() or re.search(r"[.!?]\s+\S|[\r\n]", frase.strip()):
        raise ValueError("É esperada uma frase por campo.")
    return frase.strip().rstrip(".!?") + "."


async def _ficha(ferramentas: Ferramentas, tema: str) -> dict | None:
    try:
        trechos = await ferramentas.chamar("buscar_conceitos", pergunta=ROTULOS.get(tema, tema), tema=tema, k=4)
        ficha = next((t for t in trechos if isinstance(t, dict) and t.get("id") == tema and all(
            isinstance(t.get(c), str) and t[c] for c in ("titulo", "arquivo", "texto"))), None)
    except (RuntimeError, TypeError, AttributeError):
        LOGGER.info("Ficha conceitual indisponível para o tema %s", tema)
        return None
    if ficha and (conceitual := _texto_conceitual(ficha["texto"])):
        return {**ficha, "texto": conceitual}
    return None


def construir_grafo_comentario(modelo=None, ferramentas: Ferramentas | None = None):
    """preparar → gerar → validar (até três tentativas) → fallback determinístico."""
    ferramentas = ferramentas if ferramentas is not None else Ferramentas([])

    async def preparar(estado: EstadoComentario) -> dict:
        fatos = fatos_do_lance(estado["fen"], estado["lance_jogado"], estado.get("melhor_lance"))
        tema = next((f["tema"] for f in fatos if f["tema"] not in {"outro", "coincide"}), "outro")
        frases = [f["frase"] for f in fatos] + [FATO_GERAL]
        alternativa = ""
        tabuleiro = ler_fen(estado["fen"])
        if tabuleiro.parse_san(estado["melhor_lance"]) != tabuleiro.parse_san(estado["lance_jogado"]):
            alternativa = (f"O Stockfish indicava `{estado['melhor_lance']}` como primeira opção, "
                           "mas a diferença para o seu lance foi pequena.")
        base = {"fatos": fatos, "tema": tema, "alternativa": alternativa, "escolhas": {"beneficio": frases}}
        if modelo is None:
            return {**base, "pronto": False}
        # A ficha "outro" orienta a revisão de erros. Num bom lance sem tema, a lição é geral.
        ficha = await _ficha(ferramentas, tema) if tema != "outro" else None
        if licoes := _licoes_da_ficha(ficha):
            base["escolhas"]["licao"] = licoes
        return {**base, "ficha": ficha, "pronto": True}

    async def gerar(estado: EstadoComentario) -> dict:
        instrucoes = _prompt("sistema") + "\n" + _prompt("treinador/comentario")
        if estado.get("erros"):
            instrucoes += "\n" + _prompt("correcao")
        dados = {"tema": ROTULOS.get(estado["tema"], "Outro"), "ficha": estado.get("ficha"),
                 "frases_permitidas": estado["escolhas"], "erros": estado.get("erros", [])}
        if treino := estado.get("treino"):
            dados["treino"] = treino
        try:
            resposta = await _invocar(modelo, [
                SystemMessage(content=instrucoes),
                _contexto(dados),
            ], campos=("beneficio", "licao"), escolhas=estado["escolhas"])
            texto = resposta.text.strip()
        except Exception as erro:
            LOGGER.warning("Geração do comentário falhou (%s)", type(erro).__name__)
            texto = ""
        return {"texto": texto, "tentativas": estado.get("tentativas", 0) + 1}

    async def validar(estado: EstadoComentario) -> dict:
        try:
            partes = _ler_json(estado["texto"])
            if any(partes.get(campo) not in opcoes for campo, opcoes in estado["escolhas"].items()):
                return {"validada": False, "erros": ["Use as frases permitidas para descrever os fatos."]}
            texto = " ".join(_uma_frase(partes[campo]) for campo in ("beneficio", "licao"))
        except (ValueError, KeyError, TypeError):
            return {"validada": False, "erros": ["Preencha os dois campos com uma frase cada."]}
        if "licao" not in estado["escolhas"] and extrair_lances(partes["licao"]):
            return {"validada": False, "erros": ["Na lição, retire lances e coordenadas."]}
        if _AVALIACAO_NUMERICA.search(texto):
            return {"validada": False, "erros": ["Omita avaliações numéricas da redação."]}
        completo = f"{texto} {estado['alternativa']}".strip()
        resultado = await validar_resposta_async(
            completo, estado["fen"], estado["linha_motor"], validar_lances=ferramentas.validar,
            outras_linhas=([estado["lance_jogado"]],),
        )
        if not resultado["valida"]:
            return {"validada": False, "erros": resultado["erros"]}
        return {"validada": True, "texto": completo, "erros": []}

    async def fallback(estado: EstadoComentario) -> dict:
        texto = f"{estado['escolhas']['beneficio'][0]} {estado['alternativa']}".strip()
        resultado = await validar_resposta_async(
            texto, estado["fen"], estado["linha_motor"], validar_lances=ferramentas.validar,
            outras_linhas=([estado["lance_jogado"]],),
        )
        return {"texto": texto if resultado["valida"] else "", "validada": resultado["valida"], "pronto": False}

    async def apos_preparar(estado: EstadoComentario) -> str:
        return "gerar" if estado["pronto"] else "fallback"

    async def apos_validar(estado: EstadoComentario) -> str:
        if estado["validada"]:
            return END
        return "gerar" if estado["tentativas"] < MAX_TENTATIVAS else "fallback"

    grafo = StateGraph(EstadoComentario)
    for no in (preparar, gerar, validar, fallback):
        grafo.add_node(no.__name__, no)
    grafo.add_edge(START, "preparar")
    grafo.add_conditional_edges("preparar", apos_preparar, ["gerar", "fallback"])
    grafo.add_edge("gerar", "validar")
    grafo.add_conditional_edges("validar", apos_validar, [END, "gerar", "fallback"])
    grafo.add_edge("fallback", END)
    return grafo.compile()


def _resultado_comentario(estado: EstadoComentario, ferramentas: Ferramentas) -> dict:
    tema = estado.get("tema", "outro") if estado.get("pronto") else "outro"
    ficha = estado.get("ficha") if estado.get("pronto") else None
    return {
        "tema": tema, "tema_label": ROTULOS.get(tema, "Outro"),
        "texto": estado.get("texto") or "Não foi possível confirmar um comentário para este lance.",
        "ficha": {c: ficha[c] for c in ("id", "titulo", "arquivo")} if ficha else None,
        "ferramentas_usadas": list(dict.fromkeys(item["nome"] for item in ferramentas.usadas)),
        "tentativas": estado.get("tentativas", 0), "validada": bool(estado.get("validada")),
        "fallback": bool(estado.get("validada") and not estado.get("pronto")),
    }


class _ValidadorLocal(Ferramentas):
    """Mesmas regras de validar_lances, sem abrir uma sessão MCP quando o LLM está fora do ar."""

    async def validar(self, fen: str, lances: list[str]) -> list[dict]:
        from mcp_server.tools.board import validar_lances

        self.usadas.append({"nome": "validar_lances", "argumentos": {"fen": fen, "lances": lances}})
        return validar_lances(fen, lances)


async def comentar_bom_lance_async(fen: str, lance_jogado: str, melhor_lance: str, linha_motor: list[str],
                                   *, usar_modelo: bool = True, treino: dict | None = None) -> dict:
    """Comenta um lance aceitável. ``usar_modelo=False`` produz apenas o apoio determinístico."""
    ferramentas = Ferramentas([])
    if not usar_modelo:
        ferramentas = _ValidadorLocal([])
        try:
            resultado = await construir_grafo_comentario(None, ferramentas).ainvoke({
                "fen": fen, "lance_jogado": lance_jogado, "melhor_lance": melhor_lance, "linha_motor": linha_motor,
            })
        except Exception as erro:
            LOGGER.warning("Comentário determinístico indisponível (%s)", type(erro).__name__)
            resultado = {}
        return _resultado_comentario(resultado, ferramentas)
    try:
        tabuleiro = ler_fen(fen)
        jogado = tabuleiro.san(tabuleiro.parse_san(lance_jogado))
        melhor = tabuleiro.san(tabuleiro.parse_san(melhor_lance))
        if not linha_motor or tabuleiro.parse_san(linha_motor[0]) != tabuleiro.parse_san(melhor):
            raise ValueError("Melhor lance diverge da variante.")
        async with sessao_mcp() as disponiveis:
            ferramentas = Ferramentas(disponiveis)
            resultado = await construir_grafo_comentario(_modelo() if usar_modelo else None, ferramentas).ainvoke({
                "fen": fen, "lance_jogado": jogado, "melhor_lance": melhor, "linha_motor": linha_motor,
                **({"treino": treino} if treino else {}),
            })
        return _resultado_comentario(resultado, ferramentas)
    except Exception as erro:
        LOGGER.warning("Comentário indisponível (%s)", type(erro).__name__)
        return _resultado_comentario({}, ferramentas)


# Dicas -----------------------------------------------------------------------

def _situacao(analise: dict) -> str:
    avaliacao = analise.get("avaliacao") or {}
    if avaliacao.get("tipo") == "mate":
        chance = 100.0 if avaliacao.get("a_favor") else 0.0
    elif isinstance(avaliacao.get("valor"), int):
        chance = chance_de_vitoria(avaliacao["valor"])
    else:
        return ""
    estado = "favorável" if chance >= 60 else "difícil" if chance <= 40 else "equilibrada"
    return f" Pela avaliação do Stockfish, sua posição está {estado}."


def _peca_ameacada(tabuleiro: chess.Board) -> int | None:
    """Casa da peça própria mais valiosa que o adversário ganharia na troca."""
    if tabuleiro.is_check():
        return None
    vez_do_adversario = tabuleiro.copy(stack=False)
    vez_do_adversario.push(chess.Move.null())
    candidatas = []
    for casa, peca in tabuleiro.piece_map().items():
        if peca.color != tabuleiro.turn or peca.piece_type in (chess.KING, chess.PAWN):
            continue
        if tabuleiro.is_attacked_by(not tabuleiro.turn, casa) and _troca(vez_do_adversario, casa) >= 2:
            candidatas.append((VALORES[peca.piece_type], casa))
    return max(candidatas)[1] if candidatas else None


def diagnosticar_dica(fen: str, analise: dict) -> dict:
    """Prepara as três etapas da dica a partir da análise do Stockfish na posição atual."""
    tabuleiro = ler_fen(fen)
    variantes = analise.get("melhores_lances") or []
    linha = analise.get("linha_principal") or []
    if not variantes or not linha:
        raise ValueError("A posição não tem lances para sugerir.")
    melhor = tabuleiro.parse_san(variantes[0]["san"])
    san = tabuleiro.san(melhor)
    peca = tabuleiro.piece_type_at(melhor.from_square)
    depois = tabuleiro.copy(stack=False)
    depois.push(melhor)
    alvo = chess.PAWN if tabuleiro.is_en_passant(melhor) else tabuleiro.piece_type_at(melhor.to_square)
    avaliacao = analise.get("avaliacao") or {}
    # Na dica, só evidências fortes e próximas: um alarme falso estragaria o treino.
    evidencias = [e for e in candidatos_taticos(tabuleiro, analise)
                  if e.tema in TEMAS and e.tema != "outro" and e.forca >= FORCA_MINIMA_DICA and e.meio_lance <= 2]
    ameacada = _peca_ameacada(tabuleiro)
    tema = "outro"
    if tabuleiro.is_check():
        tipo = "defesa_do_rei"
        objetivo = ("Seu rei está em xeque. O primeiro objetivo é sair do xeque com segurança: "
                    "compare fugir com o rei, bloquear a linha e capturar a peça atacante.")
    elif avaliacao.get("tipo") == "mate" and avaliacao.get("a_favor"):
        tipo, tema = "mate", "mate"
        objetivo = ("O Stockfish encontrou uma sequência forçada de xeque-mate a seu favor. "
                    "Procure lances que deem xeque e tirem casas do rei adversário.")
    elif evidencias:
        tipo, tema = "tatica", evidencias[0].tema
        objetivo = (f"Existe uma oportunidade tática nesta posição, ligada ao tema {TEMAS[tema].lower()}. "
                    "Procure primeiro os lances forçantes: xeques, capturas e ameaças.")
    elif ameacada is not None:
        tipo = "defesa"
        objetivo = ("Uma das suas peças está em perigo: o adversário ameaça ganhar material. "
                    "Antes de qualquer plano, cuide da segurança dela.")
    elif alvo and VALORES[alvo] - _troca(depois, melhor.to_square) >= 2:
        tipo, tema = "material", "peca_pendurada"
        objetivo = "Há material adversário que pode ser capturado com vantagem. Procure peças adversárias mal defendidas."
    elif tabuleiro.fullmove_number <= 12 and any(
            tabuleiro.piece_type_at(casa) in (chess.KNIGHT, chess.BISHOP) and tabuleiro.color_at(casa) == tabuleiro.turn
            for casa in chess.SquareSet(chess.BB_RANK_1 if tabuleiro.turn else chess.BB_RANK_8)):
        tipo = "desenvolvimento"
        objetivo = ("Não há uma tática imediata. Na abertura, priorize desenvolver as peças menores, "
                    "disputar o centro e preparar o roque.")
    else:
        tipo = "plano"
        objetivo = ("O Stockfish não aponta uma tática forçada. Procure melhorar a peça menos ativa "
                    "e mantenha o seu rei protegido.")
    objetivo += _situacao(analise)

    origem = chess.square_name(melhor.from_square)
    if tipo == "defesa":
        tipo_ameacada = tabuleiro.piece_type_at(ameacada)
        pista = (f"Observe {_nome(tipo_ameacada)} na casa {chess.square_name(ameacada)}: "
                 f"{'ela' if tipo_ameacada in _FEMININO else 'ele'} está sob ataque.")
        if melhor.from_square != ameacada:
            pista += f" O lance sugerido pelo Stockfish envolve {_nome(peca)} na casa {origem}."
        casa = chess.square_name(ameacada)
    else:
        pista = f"Concentre-se n{_o(peca)} {NOMES[peca]} na casa {origem}."
        if depois.is_checkmate():
            pista += " Com ela você pode encerrar a partida." if peca in _FEMININO else " Com ele você pode encerrar a partida."
        elif alvo:
            pista += " Existe um alvo adversário ao alcance dessa peça."
        elif depois.is_check():
            pista += " Essa peça pode dar xeque."
        casa = origem
    revelacao = f"O Stockfish sugere `{san}`{justificar_alternativa(tabuleiro, san, linha)}."
    return {"tipo": tipo, "tema": tema, "tema_label": ROTULOS.get(tema, "Outro"),
            "niveis": {1: objetivo, 2: pista, 3: revelacao}, "casa": casa,
            "lance": {"san": san, "uci": melhor.uci()}, "linha": linha}


def secao_reconhecer(ficha: dict | None) -> str | None:
    if not ficha:
        return None
    trecho = re.search(r"^## Como reconhecer\n(.*?)(?=^## |\Z)", ficha.get("texto", ""), flags=re.M | re.S)
    if not trecho or not trecho.group(1).strip():
        return None
    return re.split(r"(?<=[.!?])\s+|\n", trecho.group(1).strip(), maxsplit=1)[0]


async def ficha_do_tema(tema: str) -> dict | None:
    """Recupera a ficha de um tema pelo MCP, sem LLM."""
    try:
        async with sessao_mcp() as disponiveis:
            return await _ficha(Ferramentas(disponiveis), tema)
    except Exception as erro:
        LOGGER.info("Busca de ficha indisponível (%s)", type(erro).__name__)
        return None


# Perguntas sobre o histórico da partida -------------------------------------

_MAIOR_ERRO = re.compile(r"maior erro|pior (?:lance|jogada|movimento)|erro mais grave", re.I)
_ALTERNATIVA = re.compile(
    r"melhor alternativa|deveria ter (?:jogado|feito)|devia ter jogado|era melhor jogar|alternativa melhor", re.I)
_MATERIAL = re.compile(r"\bperdi\b|perda de material|perdendo material", re.I)
_SITUACAO_PARTIDA = re.compile(
    r"posi[cç][aã]o (?:é |está |esta )?favor[aá]vel|estou (?:ganhando|perdendo|melhor|pior|bem)"
    r"|quem est[aá] (?:melhor|ganhando)|tenho vantagem|minha posi[cç][aã]o (?:é|está) (?:boa|ruim)", re.I)


def intencao_historico(pergunta: str) -> str | None:
    for nome, padrao in (("maior_erro", _MAIOR_ERRO), ("alternativa", _ALTERNATIVA),
                         ("material", _MATERIAL), ("situacao", _SITUACAO_PARTIDA)):
        if padrao.search(pergunta):
            return nome
    return None


def _rotulo(lance: dict) -> str:
    return f"{lance['numero']}{'.' if lance['cor'] == 'white' else '...'} {lance['san']}"


def resposta_historico(intencao: str, lances: list[dict], cor: str, selecionado: dict | None) -> tuple[str, list]:
    """Monta a resposta e as citações (FEN, lance) que o validador precisa confirmar."""
    meus = [l for l in lances if l["cor"] == cor and l.get("avaliacao")]
    citacoes = []
    if intencao == "maior_erro":
        ruins = [l for l in meus if l["avaliacao"]["classe"] != "aceitavel"]
        if not ruins:
            return ("Até agora, nenhum dos seus lances avaliados foi classificado como imprecisão ou erro.", [])
        pior = max(ruins, key=lambda l: l["avaliacao"]["queda"])
        dados = pior["avaliacao"]
        citacoes += [(pior["fen_antes"], pior["san"]), (pior["fen_antes"], dados["melhor_lance"])]
        return (f"Seu maior erro até agora foi `{pior['san']}` no lance {pior['numero']}, classificado como "
                f"{CLASSES[dados['classe']]}. O Stockfish preferia `{dados['melhor_lance']}`.", citacoes)
    if intencao == "alternativa":
        if selecionado and not selecionado.get("avaliacao"):
            return ("O lance selecionado ainda não foi avaliado pelo Stockfish.", [])
        alvo = selecionado or (meus[-1] if meus else None)
        if not alvo:
            return ("Ainda não há um lance seu avaliado para comparar com o Stockfish.", [])
        dados = alvo["avaliacao"]
        citacoes.append((alvo["fen_antes"], alvo["san"]))
        tabuleiro = ler_fen(alvo["fen_antes"])
        if tabuleiro.parse_san(dados["melhor_lance"]) == tabuleiro.parse_san(alvo["san"]):
            return (f"Seu lance `{alvo['san']}` já era a primeira escolha do Stockfish.", citacoes)
        citacoes.append((alvo["fen_antes"], dados["melhor_lance"]))
        justificativa = justificar_alternativa(tabuleiro, dados["melhor_lance"], dados["linha_motor"])
        return (f"No lance {alvo['numero']}, em vez de `{alvo['san']}`, o Stockfish indicava "
                f"`{dados['melhor_lance']}`{justificativa}.", citacoes)
    if intencao == "material":
        lado = chess.WHITE if cor == "white" else chess.BLACK
        perdas = []
        for posicao, lance in enumerate(lances):
            if lance["cor"] == cor:
                continue
            antes, depois = ler_fen(lance["fen_antes"]), ler_fen(lance["fen_depois"])
            perda = _material(antes, lado) - _material(depois, lado)
            if perda > 0:
                perdas.append((perda, posicao, lance, antes.piece_type_at(chess.parse_square(lance["uci"][2:4]))))
        if not perdas:
            return ("Você não perdeu material para o Stockfish até agora.", [])
        _, posicao, lance, tipo = max(perdas, key=lambda p: (p[0], p[1]))
        citacoes.append((lance["fen_antes"], lance["san"]))
        nome = _nome(tipo) if tipo else "material"
        texto = f"Você perdeu {nome} quando o Stockfish jogou `{lance['san']}` no lance {lance['numero']}."
        anterior = lances[posicao - 1] if posicao else None
        if anterior and anterior["cor"] == cor and (dados := anterior.get("avaliacao")) and dados["classe"] != "aceitavel":
            citacoes += [(anterior["fen_antes"], anterior["san"]), (anterior["fen_antes"], dados["melhor_lance"])]
            texto += (f" Antes disso, seu lance `{anterior['san']}` foi classificado como {CLASSES[dados['classe']]}, "
                      f"e o Stockfish preferia `{dados['melhor_lance']}`.")
        return texto, citacoes
    if intencao == "situacao":
        if not meus:
            return ("Ainda não há um lance seu avaliado pelo Stockfish nesta partida.", [])
        ultimo = meus[-1]
        chance = ultimo["avaliacao"]["chance_vitoria_depois"]
        estado = "favorável" if chance >= 60 else "difícil" if chance <= 40 else "equilibrada"
        lado = chess.WHITE if cor == "white" else chess.BLACK
        atual = ler_fen(lances[-1]["fen_depois"])
        saldo = _material(atual, lado) - _material(atual, not lado)
        material = "à frente" if saldo > 0 else "atrás" if saldo < 0 else "igual ao adversário"
        citacoes.append((ultimo["fen_antes"], ultimo["san"]))
        return (f"Pela avaliação do Stockfish depois do seu lance `{ultimo['san']}`, sua posição estava {estado}. "
                f"No material, você está {material}.", citacoes)
    raise ValueError(f"Intenção desconhecida: {intencao}")


async def validar_citacoes(texto: str, citacoes: list[tuple[str, str]], validar_lances) -> bool:
    """Confere cada lance citado no FEN em que foi jogado ou recomendado."""
    if _AVALIACAO_NUMERICA.search(texto):
        return False
    for fen, lance in citacoes:
        resultado = await validar_resposta_async(f"`{lance}`", fen, [lance], validar_lances=validar_lances)
        if not resultado["valida"]:
            return False
    return True


def contexto_do_lance(lance: dict, fen_atual: str, tema: str | None = None) -> dict:
    """Formato aceito pelo chat existente para o lance selecionado."""
    dados = lance.get("avaliacao") or {}
    contexto = {"jogada_da_partida": lance["san"], "classe": dados.get("classe"),
                "momento": "depois" if fen_atual == lance["fen_depois"] else "posicao_atual_apos_resposta_da_ia",
                "fen_apos_lance": lance["fen_depois"]}
    if tema and tema != "outro":
        contexto.update(tema=tema, tema_label=ROTULOS.get(tema, tema))
    return contexto


# Conceitos e peças ameaçadas -------------------------------------------------

_PASTA_FICHAS = Path(__file__).resolve().parents[1] / "knowledge_base"
_PERGUNTA_CONCEITO = re.compile(
    r"o que (?:significa|e|quer dizer|seria)|\bexpliq|\bdefin|como funciona|o que (?:eh|é) (?:um|uma|o|a)\b", re.I)
_PECAS = {"dama": chess.QUEEN, "rainha": chess.QUEEN, "rei": chess.KING, "torre": chess.ROOK,
          "bispo": chess.BISHOP, "cavalo": chess.KNIGHT}
_AMEACA_PECA = re.compile(r"\b(?:minha|meu|minhas|meus)\s+(dama|rainha|rei|torre|bispo|cavalo)s?\b"
                          r".*(?:amea[cç]|atacad|sob ataque|em perigo|pendurad|segur)", re.I)


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def catalogo_fichas() -> dict[str, str]:
    """Identificador e título das 30 fichas, lidos do cabeçalho de cada arquivo."""
    catalogo = {}
    for caminho in sorted(_PASTA_FICHAS.glob("*.md")):
        if caminho.name == "README.md":
            continue
        cabecalho = caminho.read_text(encoding="utf-8").split("---")[1]
        dados = dict(re.findall(r"^(id|titulo):\s*(.+)$", cabecalho, flags=re.M))
        if "id" in dados and "titulo" in dados:
            catalogo[dados["id"].strip()] = dados["titulo"].strip()
    return catalogo


def tema_do_conceito(pergunta: str) -> str | None:
    """Tema da ficha quando a pergunta pede o significado de um conceito conhecido."""
    texto = _normalizar(pergunta)
    if not _PERGUNTA_CONCEITO.search(texto):
        return None
    candidatos = []
    for tema, titulo in catalogo_fichas().items():
        if tema == "outro":
            continue
        for nome in {_normalizar(titulo), tema.replace("_", " ")}:
            if re.search(rf"\b{re.escape(nome)}\b", texto):
                candidatos.append((len(nome), tema))
    return max(candidatos)[1] if candidatos else None


def _secao(ficha: dict, nome: str) -> str:
    trecho = re.search(rf"^## {nome}\n(.*?)(?=^## |\Z)", ficha.get("texto", ""), flags=re.M | re.S)
    return trecho.group(1).strip() if trecho else ""


async def explicar_conceito_async(tema: str, pergunta: str) -> dict:
    """RAG sem posição: o Qwen3 explica a ficha recuperada, sem citar lances ou casas."""
    ferramentas = Ferramentas([])
    try:
        async with sessao_mcp() as disponiveis:
            ferramentas = Ferramentas(disponiveis)
            ficha = await _ficha(ferramentas, tema)
            if not ficha:
                return {"resposta": "A ficha desse conceito não está disponível no momento.", "validada": False,
                        "fallback": False, "ferramentas_usadas": ferramentas.usadas, "ficha": None}
            definicao = _secao(ficha, "Definição")
            modelo = _modelo()
            erros: list[str] = []
            for _ in range(2 if modelo is not None else 0):
                try:
                    instrucoes = _prompt("sistema") + "\n" + _prompt("treinador/conceito")
                    if erros:
                        instrucoes += "\n" + _prompt("correcao") + " " + " ".join(erros)
                    resposta = await _invocar(modelo, [SystemMessage(content=instrucoes), _contexto({
                        "pergunta": pergunta, "ficha": {"titulo": ficha["titulo"], "definicao": definicao,
                                                        "como_reconhecer": _secao(ficha, "Como reconhecer"),
                                                        "como_evitar": _secao(ficha, "Como evitar")}})],
                        campos=("resposta",))
                    texto = _ler_json(resposta.text)["resposta"].strip()
                except Exception as erro:
                    LOGGER.warning("Explicação de conceito falhou (%s)", type(erro).__name__)
                    break
                frases = [f for f in re.split(r"(?<=[.!?])\s+", texto) if f]
                erros = []
                if not texto or len(texto) > 600 or len(frases) > 3:
                    erros.append("Use no máximo três frases curtas.")
                if extrair_lances(texto):
                    erros.append("Retire lances e coordenadas; explique o conceito em palavras.")
                if _AVALIACAO_NUMERICA.search(texto):
                    erros.append("Omita avaliações numéricas.")
                if not erros:
                    return {"resposta": texto, "validada": True, "fallback": False,
                            "ferramentas_usadas": ferramentas.usadas, "ficha": ficha}
            if definicao:
                return {"resposta": f"Pela ficha {ficha['titulo']}: {definicao}", "validada": True, "fallback": True,
                        "ferramentas_usadas": ferramentas.usadas, "ficha": ficha}
    except Exception as erro:
        LOGGER.warning("Conceito indisponível (%s)", type(erro).__name__)
    return {"resposta": "Não foi possível confirmar uma explicação para esse conceito.", "validada": False,
            "fallback": False, "ferramentas_usadas": ferramentas.usadas, "ficha": None}


def peca_da_pergunta(pergunta: str) -> int | None:
    encontrada = _AMEACA_PECA.search(pergunta)
    return _PECAS[encontrada.group(1).casefold()] if encontrada else None


def resposta_ameaca(fen: str, cor: str, tipo: int) -> str:
    """Ataques e defesas geométricos da peça do jogador, como em descrever_posicao."""
    tabuleiro = ler_fen(fen)
    lado = chess.WHITE if cor == "white" else chess.BLACK
    artigo = "Sua" if tipo in _FEMININO else "Seu"
    casas = list(tabuleiro.pieces(tipo, lado))
    if not casas:
        return f"Você não tem {NOMES[tipo]} no tabuleiro nesta posição."
    frases = []
    for casa in casas:
        nome = f"{artigo} {NOMES[tipo]} na casa {chess.square_name(casa)}"
        atacantes = tabuleiro.attackers(not lado, casa)
        if not atacantes:
            frases.append(f"{nome} não está sob ataque nesta posição.")
            continue
        quem = " e ".join(sorted({_nome(tabuleiro.piece_type_at(a)) for a in atacantes}))
        if tipo == chess.KING:
            frases.append(f"{nome} está em xeque, atacado por {quem}.")
        else:
            defesa = "tem defesa" if tabuleiro.attackers(lado, casa) else "está sem defesa"
            frases.append(f"{nome} está sob ataque de {quem} e {defesa}.")
    return " ".join(frases)


_TATICA = re.compile(r"oportunidade t[aá]tica|alguma t[aá]tica|existe (?:uma )?t[aá]tica|tem (?:alguma )?t[aá]tica"
                     r"|lance forte|combina[cç][aã]o", re.I)
_DESENVOLVIMENTO = re.compile(r"desenvolv", re.I)


def pergunta_tatica(pergunta: str) -> bool:
    return bool(_TATICA.search(pergunta))


def pergunta_desenvolvimento(pergunta: str) -> bool:
    return bool(_DESENVOLVIMENTO.search(pergunta))


def resposta_tatica(diagnostico: dict) -> str:
    """Resume o diagnóstico da dica sem revelar o lance."""
    objetivo = diagnostico["niveis"][1]
    if diagnostico["tipo"] in {"tatica", "mate", "material"}:
        return f"Sim. {objetivo} Peça uma dica se quiser uma pista sobre a peça."
    if diagnostico["tipo"] in {"defesa", "defesa_do_rei"}:
        return f"Antes de atacar, há um problema defensivo. {objetivo}"
    return f"O Stockfish não aponta uma tática forçada a seu favor agora. {objetivo}"


def resposta_desenvolvimento(fen: str, cor: str) -> str:
    """Peças menores ainda nas casas iniciais, roque e centro, calculados no tabuleiro."""
    tabuleiro = ler_fen(fen)
    lado = chess.WHITE if cor == "white" else chess.BLACK
    iniciais = ({chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT, chess.C1: chess.BISHOP, chess.F1: chess.BISHOP}
                if lado == chess.WHITE else
                {chess.B8: chess.KNIGHT, chess.G8: chess.KNIGHT, chess.C8: chess.BISHOP, chess.F8: chess.BISHOP})
    paradas = [f"{_nome(tipo)} na casa {chess.square_name(casa)}" for casa, tipo in iniciais.items()
               if tabuleiro.piece_type_at(casa) == tipo and tabuleiro.color_at(casa) == lado]
    frases = []
    if paradas:
        frases.append("Ainda estão na casa inicial: " + ", ".join(paradas) + ".")
    else:
        frases.append("Suas peças menores já saíram das casas iniciais.")
    rei = tabuleiro.king(lado)
    rocou = chess.square_file(rei) in (2, 6) and chess.square_rank(rei) == (0 if lado == chess.WHITE else 7)
    if rocou:
        frases.append("Seu rei já está em uma casa típica de roque.")
    elif tabuleiro.has_castling_rights(lado):
        frases.append("Você ainda tem direito ao roque, que pode proteger o rei e ativar uma torre.")
    else:
        frases.append("Você não tem mais o direito de rocar, então proteja o rei com as peças próximas.")
    frases.append("Desenvolva cada peça para uma casa ativa, de preferência mirando o centro, sem mover a mesma peça "
                  "várias vezes sem necessidade.")
    return " ".join(frases)
