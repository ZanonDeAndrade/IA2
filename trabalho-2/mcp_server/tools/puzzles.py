"""Consulta ao recorte público Lichess, preparado por data/scripts/download_puzzles.py."""

import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing

from fastmcp.exceptions import ToolError

# As chaves são os temas da interface do agente. Os valores são tags oficiais.
TAGS = {
    "garfo": "fork", "cravada": "pin", "espeto": "skewer",
    "ataque_descoberto": "discoveredAttack", "ataque_duplo": "fork",
    "peca_pendurada": "hangingPiece", "mate": "mate", "sobrecarga": "overloading",
    "desvio": "deflection", "atracao": "attraction",
}
ROTULOS = {
    "fork": "Garfo", "pin": "Cravada", "skewer": "Espeto", "discoveredAttack": "Ataque descoberto",
    "hangingPiece": "Peça pendurada", "mate": "Mate", "deflection": "Desvio", "attraction": "Atração",
    "overloading": "Sobrecarga", "endgame": "Final", "middlegame": "Meio-jogo",
    "opening": "Abertura", "sacrifice": "Sacrifício", "promotion": "Promoção",
    "mateIn1": "Mate em 1", "mateIn2": "Mate em 2", "mateIn3": "Mate em 3",
    "mateIn4": "Mate em 4", "mateIn5": "Mate em 5 ou mais",
}
PADRAO = Path(__file__).resolve().parents[2] / "data" / "puzzles.sqlite"


def buscar_puzzles(temas: list[str], rating_min: int, rating_max: int, quantidade: int = 5) -> list[dict]:
    """Retorna puzzles do recorte por faixa de rating e por qualquer tema solicitado.

    O FEN é a posição para o jogador resolver, depois do lance preparatório.
    """
    if not 0 <= rating_min <= rating_max <= 4000 or not 1 <= quantidade <= 50 or len(temas) > 30:
        raise ValueError("Faixa de rating, temas ou quantidade inválidos.")
    caminho = Path(os.getenv("PUZZLES_DB") or PADRAO).resolve()
    if not caminho.is_file():
        raise ToolError("PUZZLES_BASE_AUSENTE")
    tags = sorted({TAGS.get(tema, tema) for tema in temas})
    consulta = "SELECT p.dados FROM puzzles p WHERE p.rating BETWEEN ? AND ?"
    parametros = [rating_min, rating_max]
    if tags:
        marcadores = ",".join("?" for _ in tags)
        consulta += f" AND EXISTS (SELECT 1 FROM temas t WHERE t.puzzle_id=p.id AND t.tema IN ({marcadores}))"
        parametros.extend(tags)
    consulta += " ORDER BY abs(p.rating - ?), p.id LIMIT ?"
    parametros.extend([(rating_min + rating_max) / 2, quantidade])
    try:
        with closing(sqlite3.connect(caminho.as_uri() + "?mode=ro", uri=True)) as conn:
            return [json.loads(linha[0]) for linha in conn.execute(consulta, parametros)]
    except (sqlite3.Error, ValueError) as erro:
        raise ToolError("PUZZLES_BASE_INVALIDA") from erro
