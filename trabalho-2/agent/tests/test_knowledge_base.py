from pathlib import Path
import re

import chess
import pytest
import yaml

PASTA = Path(__file__).resolve().parents[2] / "knowledge_base"
FICHAS = sorted(set(PASTA.glob("*.md")) - {PASTA / "README.md"})


def test_cobertura_da_base():
    assert 28 <= len(FICHAS) <= 32
    assert {
        "garfo", "cravada", "espeto", "ataque_descoberto", "peca_pendurada", "mate",
        "sobrecarga", "desvio", "atracao", "ataque_duplo",
    } <= {caminho.stem for caminho in FICHAS}


@pytest.mark.parametrize("caminho", FICHAS, ids=lambda caminho: caminho.stem)
def test_ficha(caminho):
    abertura, cabecalho, corpo = caminho.read_text(encoding="utf-8").split("---", 2)
    assert not abertura
    dados = yaml.safe_load(cabecalho)
    assert dados["id"] == caminho.stem == dados["tema_pt"]
    assert dados["titulo"] and dados["tema"]
    assert dados["nivel"] in {"iniciante", "intermediario"}
    for secao in ("Definição", "Como reconhecer", "Por que é importante", "Como evitar", "Exemplo", "Referências"):
        assert f"## {secao}\n" in corpo
    assert "https://" in corpo
    if fen := re.search(r"^FEN: `([^`]+)`", corpo, re.MULTILINE):
        tabuleiro = chess.Board(fen[1])
        assert tabuleiro.is_valid()
        if lances := re.search(r"^Lances: `([^`]+)`", corpo, re.MULTILINE):
            for lance in lances[1].split():
                movimento = tabuleiro.parse_san(lance)
                assert tabuleiro.san(movimento) == lance
                tabuleiro.push(movimento)
