"""Evidências de motivos táticos em variantes legais, sem acesso ao dataset."""

from dataclasses import dataclass

import chess

NOMES = ("", "peão", "cavalo", "bispo", "torre", "dama", "rei")
VALORES = (0, 1, 3, 3, 5, 9, 100)
DESLIZANTES = {chess.BISHOP, chess.ROOK, chess.QUEEN}


@dataclass(frozen=True)
class Passo:
    antes: chess.Board
    lance: chess.Move
    depois: chess.Board

    @property
    def peca(self):
        return self.depois.piece_at(self.lance.to_square)

    @property
    def alvo(self):
        if self.antes.is_en_passant(self.lance):
            return chess.Piece(chess.PAWN, not self.antes.turn)
        return self.antes.piece_at(self.lance.to_square)


@dataclass(frozen=True)
class Evidencia:
    tema: str
    frase: str
    forca: int
    meio_lance: int


def _passos(raiz, linha):
    passos = []
    antes = raiz
    for san in linha[:10]:
        try:
            lance = antes.parse_san(san)
        except (ValueError, TypeError):
            break
        depois = antes.copy(stack=False)
        depois.push(lance)
        passos.append(Passo(antes, lance, depois))
        antes = depois
    return passos


def _nome(peca):
    return NOMES[peca.piece_type]


def _artigo(peca):
    return ("a " if peca.piece_type in (chess.ROOK, chess.QUEEN) else "o ") + _nome(peca)


def _valor(peca):
    return VALORES[peca.piece_type] if peca else 0


def _alinhamentos(tabuleiro, casa):
    """Retorna as duas primeiras peças em cada raio utilizado pelo atacante."""
    peca = tabuleiro.piece_at(casa)
    if not peca or peca.piece_type not in DESLIZANTES:
        return
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
        diagonal = bool(dx and dy)
        if (peca.piece_type == chess.ROOK and diagonal) or (peca.piece_type == chess.BISHOP and not diagonal):
            continue
        x, y = chess.square_file(casa) + dx, chess.square_rank(casa) + dy
        ocupadas = []
        while 0 <= x < 8 and 0 <= y < 8:
            alvo = chess.square(x, y)
            if tabuleiro.piece_at(alvo):
                ocupadas.append(alvo)
                if len(ocupadas) == 2:
                    yield tuple(ocupadas)
                    break
            x, y = x + dx, y + dy


def _troca(tabuleiro, casa, profundidade=0):
    """Maior ganho imediato por capturas legais sucessivas na mesma casa."""
    alvo = tabuleiro.piece_at(casa)
    if not alvo or profundidade == 8:
        return 0
    ganhos = [0]
    for movimento in tabuleiro.generate_legal_captures(to_mask=chess.BB_SQUARES[casa]):
        depois = tabuleiro.copy(stack=False)
        depois.push(movimento)
        promocao = VALORES[movimento.promotion] - VALORES[chess.PAWN] if movimento.promotion else 0
        ganhos.append(_valor(alvo) + promocao - _troca(depois, casa, profundidade + 1))
    return max(ganhos)


def _geometria(ataque, defesa, ganho, indice):
    casa = ataque.lance.to_square
    for frente, fundo in _alinhamentos(ataque.depois, casa):
        primeiro, segundo = (ataque.depois.piece_at(c) for c in (frente, fundo))
        if primeiro.color == ataque.peca.color or segundo.color == ataque.peca.color:
            continue
        if (defesa.lance.from_square == frente and ganho.lance.from_square == casa
                and ganho.lance.to_square == fundo and ganho.alvo == segundo and _valor(primeiro) > _valor(segundo) >= 3):
            yield Evidencia("espeto", f"Na variante, {_artigo(primeiro)} sai da linha de ataque e expõe {_artigo(segundo)} à captura.", 99, indice)
    if ganho.lance.from_square == casa and _valor(ganho.alvo) >= 3:
        alvos = ataque.depois.attacks(casa) & ataque.depois.occupied_co[defesa.antes.turn]
        if ganho.lance.to_square in alvos and any(
            outro != ganho.lance.to_square and (_valor(ataque.depois.piece_at(outro)) == VALORES[chess.KING]
                or (outro == defesa.lance.from_square and _valor(ataque.depois.piece_at(outro)) >= max(3, _valor(ataque.peca))))
            for outro in alvos
        ):
            yield Evidencia("garfo", f"Na variante, {_artigo(ataque.peca)} ataca dois alvos e depois captura {_artigo(ganho.alvo)}.", 88, indice)


def _cravadas(ataque, ganho, indice):
    lado = ataque.antes.turn
    for casa in chess.SquareSet(ataque.depois.occupied_co[lado]):
        peca = ataque.depois.piece_at(casa)
        for frente, fundo in _alinhamentos(ataque.depois, casa):
            primeiro, segundo = (ataque.depois.piece_at(c) for c in (frente, fundo))
            if primeiro.color == lado or segundo.color == lado or not _valor(segundo) > _valor(primeiro) >= 3:
                continue
            nova = casa == ataque.lance.to_square or (frente, fundo) not in _alinhamentos(ataque.antes, casa)
            explora = ganho and ganho.alvo == primeiro and ganho.lance.to_square == frente
            absoluta = segundo.piece_type == chess.KING
            if nova and (absoluta or explora):
                forca = 102 if absoluta else 96
            elif explora:
                forca = 90
            elif absoluta and indice == 0:
                forca = 70
            else:
                continue
            yield Evidencia("cravada", f"Na variante, {_artigo(peca)} crava {_artigo(primeiro)} na linha de {_artigo(segundo)}.", forca, indice)


def _descoberto(ataque, ganho, indice):
    lado = ataque.antes.turn
    origem = ataque.lance.from_square
    for casa in chess.SquareSet(ataque.antes.occupied_co[lado]):
        peca = ataque.antes.piece_at(casa)
        if casa == origem or peca.piece_type not in DESLIZANTES:
            continue
        novos = (ataque.depois.attacks(casa) - ataque.antes.attacks(casa)) & ataque.depois.occupied_co[not lado]
        for alvo in novos:
            if origem not in chess.SquareSet(chess.between(casa, alvo)):
                continue
            vitima = ataque.depois.piece_at(alvo)
            captura_na_linha = (ganho and ganho.lance.from_square == casa and _valor(ganho.alvo) >= 3
                                 and (ganho.lance.to_square == alvo or alvo in chess.SquareSet(chess.between(casa, ganho.lance.to_square))))
            if vitima.piece_type == chess.KING or captura_na_linha:
                yield Evidencia("ataque_descoberto", f"Na variante, {_artigo(ataque.peca)} abre a linha para {_artigo(peca)} atacar {_artigo(vitima)}.", 95, indice)


def _defensores(ataque, defesa, ganho, passos, indice):
    alvo = ganho.lance.to_square
    origem_defesa = defesa.lance.from_square
    if (ganho.alvo and (_valor(ganho.alvo) >= 3 or ataque.depois.is_check()) and alvo != defesa.lance.to_square
            and alvo in defesa.antes.attacks(origem_defesa)
            and alvo not in defesa.depois.attacks(defesa.lance.to_square)):
        forca = 93 if _valor(ganho.alvo) >= 3 else 89
        yield Evidencia("desvio", f"Na variante, {_artigo(defesa.peca)} deixa de defender a peça que acaba sendo capturada.", forca, indice)
    if defesa.lance.to_square != ataque.lance.to_square or defesa.alvo != ataque.peca or _valor(ataque.peca) < 3:
        return
    respostas = passos[indice + 2:indice + 6:2]
    for posterior in respostas:
        capturou_isca = (posterior.lance.to_square == defesa.lance.to_square and posterior.alvo == defesa.peca
                         and _valor(defesa.peca) >= 3)
        rei_exposto = defesa.peca.piece_type == chess.KING and posterior is ganho and ganho.depois.is_check()
        if capturou_isca or rei_exposto:
            efeito = "sofre uma captura posterior" if capturou_isca else "sofre um novo xeque"
            forca = 81 if posterior.depois.is_checkmate() and capturou_isca else 97
            if _valor(ataque.peca) <= _valor(ataque.alvo) and not ataque.depois.is_check():
                forca -= 4
            yield Evidencia("atracao", f"Na variante, a captura oferecida leva {_artigo(defesa.peca)} a uma casa onde {efeito}.", forca, indice)
            break


def _enumerar(raiz, analise):
    passos = _passos(raiz, analise.get("linha_principal", []))
    avaliacao = analise.get("avaliacao", {})
    if avaliacao.get("tipo") == "mate" and avaliacao.get("valor", 0) > 0:
        forca = 105 if avaliacao["valor"] == 1 else 86
        yield Evidencia("mate", "Na posição resultante, o Stockfish encontrou uma sequência forçada de xeque-mate para o lado a jogar.", forca, 0)
    for indice in range(0, min(7, len(passos)), 2):
        ataque = passos[indice]
        ganho = passos[indice + 2] if indice + 2 < len(passos) else None
        yield from _descoberto(ataque, ganho, indice)
        yield from _cravadas(ataque, ganho, indice)
        if ganho:
            defesa = passos[indice + 1]
            yield from _geometria(ataque, defesa, ganho, indice)
            yield from _defensores(ataque, defesa, ganho, passos, indice)
    if passos and _valor(passos[0].alvo) >= 3:
        passo = passos[0]
        if _valor(passo.alvo) - _troca(passo.depois, passo.lance.to_square) >= 2:
            yield Evidencia("peca_pendurada", f"Na variante, a resposta imediata captura {_artigo(passo.alvo)} com ganho na troca dessa casa.", 91, 0)


def candidatos_taticos(raiz, analise):
    """Prioriza evidências com consequência na PV e limita o efeito de lances tardios."""
    ordenados = sorted(_enumerar(raiz, analise), key=lambda e: (-(e.forca - 3 * e.meio_lance), e.meio_lance, e.tema))
    melhores = {}
    for evidencia in ordenados:
        melhores.setdefault(evidencia.tema, evidencia)
    return list(melhores.values())


def justificar_alternativa(raiz, melhor, linha):
    passos = _passos(raiz, linha[:2])
    if not passos or passos[0].lance != raiz.parse_san(melhor):
        return ""
    passo = passos[0]
    if passo.depois.is_checkmate():
        return " e esse lance encerra a partida com mate"
    if passo.alvo:
        return f" e esse lance captura {_artigo(passo.alvo)}"
    if passo.depois.is_check():
        return " e esse lance dá xeque"
    if passo.peca.piece_type == chess.KING and raiz.is_check():
        return " e esse lance tira o rei do xeque"
    if len(passos) == 2 and not passos[1].alvo and not passos[1].depois.is_check():
        return " e, na linha analisada, a resposta imediata do adversário vem sem captura ou xeque"
    return ""
