"""Medição offline, comum às três versões e separada do validador do agente."""

from collections import Counter
from statistics import fmean

from agent.validator import agrupar_variantes, ler_fen
from evaluation.dataset import lance_legal

VERSOES = ("A", "B", "C")
METAS = {
    "invalidos_pct": (0.0, "max"), "melhor_pct": (95.0, "min"),
    "tema_pct": (60.0, "min"), "humana_media": (4.0, "min"), "ragas_media": (0.8, "min"),
}


def checar_lances(fen: str, texto: str) -> list[dict]:
    resultado = []
    for variante in agrupar_variantes(texto):
        tabuleiro = ler_fen(fen)
        bloqueada = False
        for lance in variante:
            if bloqueada:
                resultado.append({"lance": lance, "legal": None})
                continue
            try:
                movimento = lance_legal(tabuleiro, lance.replace("×", "x"))
            except ValueError:
                resultado.append({"lance": lance, "legal": False, "fen": tabuleiro.fen()})
                bloqueada = True
                continue
            resultado.append({"lance": lance, "legal": True, "san": tabuleiro.san(movimento),
                              "fen": tabuleiro.fen()})
            tabuleiro.push(movimento)
    return resultado


def medir(item: dict, texto: str, recomendado: str | None, tema: str | None) -> dict:
    tabuleiro = ler_fen(item["fen"])
    lances = checar_lances(item["fen"], texto)
    melhor_correto = False
    if recomendado:
        try:
            lance = lance_legal(tabuleiro, recomendado)
            melhor_correto = lance == lance_legal(tabuleiro, item["melhor_lance"])
            lances.append({"lance": recomendado, "legal": True, "san": tabuleiro.san(lance),
                           "fen": tabuleiro.fen(), "papel": "recomendacao"})
        except ValueError:
            lances.append({"lance": recomendado, "legal": False, "fen": tabuleiro.fen(),
                           "papel": "recomendacao"})
    return {"lances_citados": lances, "tem_lance_invalido": any(l["legal"] is False for l in lances),
            "melhor_correto": melhor_correto, "tema_correto": tema == item["tema_esperado"]}


def calcular_metricas(linhas: list[dict], total: int, humanas: list[float] = ()) -> dict:
    com_texto = [linha for linha in linhas if linha["status"] == "ok" and linha.get("avaliavel")]
    numeros = Counter(linha["status"] for linha in linhas)
    rascunhos = [linha["rascunhos_invalidos"] for linha in linhas if linha.get("rascunhos_n")]
    tokens = [linha["tokens_total"] for linha in linhas if linha.get("tokens_total") is not None]
    custos = [linha["custo_usd"] for linha in linhas if linha.get("custo_usd") is not None]
    tempos = [linha["segundos"] for linha in com_texto]
    notas_ragas = [linha["ragas"] for linha in com_texto if linha.get("ragas") is not None]

    def taxa(campo):
        return 100 * fmean(bool(linha[campo]) for linha in com_texto) if com_texto else None

    return {
        "previstas": total, "executadas": len(linhas), "explicacoes": len(com_texto),
        "completas": numeros["ok"], "incompletas": numeros["incompleta"], "falhas": numeros["erro"],
        "fallbacks": sum(bool(linha.get("fallback")) for linha in linhas),
        "invalidos_pct": taxa("tem_lance_invalido"), "melhor_pct": taxa("melhor_correto"),
        "tema_pct": taxa("tema_correto"), "tempo_media_s": fmean(tempos) if tempos else None,
        "tempo_s_n": len(tempos), "tokens_total": sum(tokens) if tokens else None, "tokens_n": len(tokens),
        "custo_total_usd": sum(custos) if custos else None, "custo_n": len(custos),
        "ragas_media": fmean(notas_ragas) if notas_ragas else None, "ragas_n": len(notas_ragas),
        "humana_media": fmean(humanas) if humanas else None, "humana_n": len(humanas),
        "rascunhos_invalidos": sum(rascunhos) if rascunhos else None,
        "rascunhos_n": sum(linha.get("rascunhos_n", 0) for linha in linhas),
    }
