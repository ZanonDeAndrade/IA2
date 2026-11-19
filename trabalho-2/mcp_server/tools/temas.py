"""Dicionário de temas da Lichess (inglês -> português).

Usado por `buscar_puzzles` e pelo agente para falar dos temas em português.
A lista fechada de temas do agente (seção 8 da documentação) fica em
`TEMAS_DO_AGENTE`; `tema_do_agente()` converte os temas de um puzzle para ela.
"""

from __future__ import annotations

TEMAS_PT: dict[str, str] = {
    # Táticas
    "fork": "garfo",
    "pin": "cravada",
    "skewer": "espeto",
    "discoveredAttack": "ataque descoberto",
    "discoveredCheck": "xeque descoberto",
    "doubleCheck": "xeque duplo",
    "hangingPiece": "peça pendurada",
    "trappedPiece": "peça presa",
    "deflection": "desvio",
    "attraction": "atração",
    "capturingDefender": "eliminação do defensor",
    "clearance": "liberação",
    "interference": "interferência",
    "intermezzo": "lance intermediário",
    "xRayAttack": "ataque em raio X",
    "sacrifice": "sacrifício",
    "quietMove": "lance silencioso",
    "defensiveMove": "lance defensivo",
    "exposedKing": "rei exposto",
    "kingsideAttack": "ataque na ala do rei",
    "queensideAttack": "ataque na ala da dama",
    "attackingF2F7": "ataque em f2/f7",
    "advancedPawn": "peão avançado",
    "promotion": "promoção",
    "underPromotion": "subpromoção",
    "zugzwang": "zugzwang",
    "castling": "roque",
    "enPassant": "en passant",
    # Mates
    "mate": "mate",
    "mateIn1": "mate em 1",
    "mateIn2": "mate em 2",
    "mateIn3": "mate em 3",
    "mateIn4": "mate em 4",
    "mateIn5": "mate em 5 ou mais",
    "backRankMate": "mate do corredor",
    "smotheredMate": "mate sufocado",
    "anastasiaMate": "mate de Anastásia",
    "arabianMate": "mate árabe",
    "bodenMate": "mate de Boden",
    "doubleBishopMate": "mate dos dois bispos",
    "dovetailMate": "mate da cauda de andorinha",
    "hookMate": "mate do gancho",
    "killBoxMate": "mate da caixa",
    "vukovicMate": "mate de Vukovic",
    "triangleMate": "mate do triângulo",
    "balestraMate": "mate de Balestra",
    "blindSwineMate": "mate dos porcos cegos",
    "cornerMate": "mate do canto",
    "morphysMate": "mate de Morphy",
    "operaMate": "mate da ópera",
    "pillsburysMate": "mate de Pillsbury",
    "swallowstailMate": "mate do rabo de andorinha",
    # Fases
    "opening": "abertura",
    "middlegame": "meio-jogo",
    "endgame": "final",
    "pawnEndgame": "final de peões",
    "rookEndgame": "final de torres",
    "bishopEndgame": "final de bispos",
    "knightEndgame": "final de cavalos",
    "queenEndgame": "final de damas",
    "queenRookEndgame": "final de dama e torre",
    # Objetivo e tamanho
    "advantage": "vantagem",
    "crushing": "vantagem decisiva",
    "equality": "igualdade",
    "oneMove": "um lance",
    "short": "curto",
    "long": "longo",
    "veryLong": "muito longo",
    # Origem
    "master": "partida de mestre",
    "masterVsMaster": "mestre contra mestre",
    "superGM": "partida de super GM",
}

# Inverso, para aceitar o tema em português na busca.
TEMAS_EN: dict[str, str] = {pt: en for en, pt in TEMAS_PT.items()}

# Lista fechada que o agente usa para rotular um erro (documentação, seção 8).
# id (= nome da ficha em knowledge_base/) -> rótulo e tema correspondente da Lichess.
TEMAS_DO_AGENTE: dict[str, dict[str, str]] = {
    "garfo": {"label": "Garfo", "lichess": "fork"},
    "cravada": {"label": "Cravada", "lichess": "pin"},
    "espeto": {"label": "Espeto", "lichess": "skewer"},
    "ataque_descoberto": {"label": "Ataque descoberto", "lichess": "discoveredAttack"},
    "peca_pendurada": {"label": "Peça pendurada", "lichess": "hangingPiece"},
    "mate": {"label": "Mate", "lichess": "mate"},
    "sobrecarga": {"label": "Sobrecarga", "lichess": "capturingDefender"},
    "desvio": {"label": "Desvio", "lichess": "deflection"},
    "atracao": {"label": "Atração", "lichess": "attraction"},
    "outro": {"label": "Outro", "lichess": ""},
}

# Tema da Lichess -> tema da lista do agente. A ordem de prioridade importa:
# um puzzle "fork hangingPiece" é rotulado como garfo.
_PARA_AGENTE: list[tuple[str, str]] = [
    ("fork", "garfo"),
    ("pin", "cravada"),
    ("skewer", "espeto"),
    ("discoveredAttack", "ataque_descoberto"),
    ("discoveredCheck", "ataque_descoberto"),
    ("deflection", "desvio"),
    ("attraction", "atracao"),
    ("capturingDefender", "sobrecarga"),
    ("hangingPiece", "peca_pendurada"),
    ("trappedPiece", "peca_pendurada"),
]

# Temas que descrevem fase, tamanho ou origem, não a tática em si.
TEMAS_NAO_TATICOS = {
    "opening", "middlegame", "endgame", "advantage", "crushing", "equality",
    "oneMove", "short", "long", "veryLong", "master", "masterVsMaster", "superGM",
}


def traduzir(tema: str) -> str:
    """Tema da Lichess em português (devolve o original se não houver tradução)."""
    return TEMAS_PT.get(tema, tema)


def rotulo(tema: str) -> str:
    """Rótulo para a interface: aceita id do agente (peca_pendurada) ou tema da Lichess (fork)."""
    if tema in TEMAS_DO_AGENTE:
        return TEMAS_DO_AGENTE[tema]["label"]
    pt = TEMAS_PT.get(tema, tema)
    return pt[:1].upper() + pt[1:]


def para_lichess(tema: str) -> str:
    """Aceita o tema em inglês (fork), em português (garfo) ou o id do agente
    (peca_pendurada) e devolve o nome da Lichess."""
    tema = tema.strip()
    if tema in TEMAS_PT:
        return tema
    if tema in TEMAS_DO_AGENTE and TEMAS_DO_AGENTE[tema]["lichess"]:
        return TEMAS_DO_AGENTE[tema]["lichess"]
    return TEMAS_EN.get(tema.lower(), tema)


def tema_do_agente(temas_lichess: list[str] | str) -> str:
    """Converte os temas de um puzzle para o id de um tema da lista do agente."""
    if isinstance(temas_lichess, str):
        temas_lichess = temas_lichess.split()
    conjunto = set(temas_lichess)
    if any(t.startswith("mate") or t.endswith("Mate") for t in conjunto):
        return "mate"
    for en, pt in _PARA_AGENTE:
        if en in conjunto:
            return pt
    return "outro"
