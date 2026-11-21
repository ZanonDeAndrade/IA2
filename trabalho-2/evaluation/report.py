"""Exporta resultados, amostra cega, gráfico e relatório de cobertura."""

from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
from random import Random

from evaluation.metrics import METAS, VERSOES, calcular_metricas

_METRICAS = (
    ("invalidos_pct", "Lances inválidos (%)"), ("melhor_pct", "Acerto do melhor lance (%)"),
    ("tema_pct", "Acerto do tema (%)"), ("humana_media", "Qualidade humana (1–5)"),
    ("ragas_media", "Fidelidade RAGAS (0–1)"), ("tempo_media_s", "Tempo por explicação (s)"),
)
_COLUNAS = (
    "id", "versao", "status", "origem", "fen", "lance_jogado", "melhor_referencia", "tema_esperado",
    "texto", "resposta_bruta", "recomendado", "tema", "lances_citados", "tem_lance_invalido",
    "melhor_correto", "tema_correto", "validada_agente", "tentativas", "fallback",
    "ferramentas_usadas", "contextos_rag", "ragas_status", "ragas", "segundos",
    "tokens_entrada", "tokens_saida", "tokens_total", "custo_usd", "chamadas_llm",
    "chamadas_com_tokens", "erros", "rascunhos_n", "rascunhos_invalidos",
)


def _csv(caminho: Path, linhas, campos) -> None:
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=campos)
        writer.writeheader()
        for linha in linhas:
            writer.writerow({
                k: json.dumps(linha[k], ensure_ascii=False) if isinstance(linha.get(k), (dict, list))
                else linha.get(k) for k in campos
            })


def _amostra(pasta: Path, pareados: list[str], por_versao: dict, semente: int, avaliacoes: Path | None) -> dict:
    rng = Random(semente)
    ids = rng.sample(pareados, min(30, len(pareados)))
    pares = [(id_, versao) for id_ in ids for versao in VERSOES]
    rng.shuffle(pares)
    chave = {}
    for id_, versao in pares:
        codigo = "R" + sha256(f"{semente}:{id_}:{versao}".encode()).hexdigest()[:12]
        chave[codigo] = {"codigo": codigo, "id": id_, "versao": versao}
    _notas(avaliacoes, chave)
    _csv(pasta / "gabarito_privado.csv", chave.values(), ("codigo", "id", "versao"))
    formulario = []
    for codigo, item in chave.items():
        linha = por_versao[item["versao"]][item["id"]]
        formulario.append({
            "codigo": codigo, "fen": linha["fen"], "lance_jogado": linha["lance_jogado"],
            "explicacao": linha["texto"],
        })
    _csv(pasta / "amostra_cega.csv", formulario, ("codigo", "fen", "lance_jogado", "explicacao"))
    formulario_notas = pasta / "formulario_humano.csv"
    if avaliacoes is None or avaliacoes.resolve() != formulario_notas.resolve():
        _csv(formulario_notas, (
            {"avaliador": f"avaliador-{i}", "codigo": codigo} for i in range(1, 4) for codigo in chave
        ), ("avaliador", "codigo", "nota", "comentario"))
    return chave


def _notas(caminho: Path | None, chave: dict) -> dict[str, list[float]]:
    notas = {versao: [] for versao in VERSOES}
    if caminho is None:
        return notas
    vistos = set()
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            if not linha["nota"].strip():
                continue
            codigo, pessoa, nota = linha["codigo"], linha["avaliador"].strip(), int(linha["nota"])
            if codigo not in chave or pessoa not in {"avaliador-1", "avaliador-2", "avaliador-3"}:
                raise ValueError("Avaliação contém código ou avaliador desconhecido.")
            if (pessoa, codigo) in vistos or not 1 <= nota <= 5:
                raise ValueError("Nota duplicada ou fora do intervalo 1–5.")
            vistos.add((pessoa, codigo))
            notas[chave[codigo]["versao"]].append(float(nota))
    return notas


def _grafico(pasta: Path, metricas: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, eixos = plt.subplots(2, 3, figsize=(10, 5.5), layout="constrained")
    cores = {"A": "#64748b", "B": "#2563eb", "C": "#15803d"}
    for eixo, (campo, titulo) in zip(eixos.flat, _METRICAS):
        eixo.set_title(titulo)
        eixo.set_xticks(range(3), VERSOES)
        observadas = []
        for i, versao in enumerate(VERSOES):
            valor = metricas[versao][campo]
            if valor is not None:
                observadas.append(valor)
                eixo.bar(i, valor, color=cores[versao], width=0.58)
                eixo.annotate(f"{valor:.2f}", (i, valor), xytext=(0, 3), textcoords="offset points",
                              ha="center", fontsize=8)
        if not observadas:
            eixo.text(0.5, 0.5, "Sem observações", transform=eixo.transAxes, ha="center", va="center")
            eixo.set_yticks([])
        elif campo.endswith("_pct"):
            eixo.set_ylim(0, 112)
        elif campo == "humana_media":
            eixo.set_ylim(0, 5.6)
        elif campo == "ragas_media":
            eixo.set_ylim(0, 1.12)
        else:
            eixo.set_ylim(0, max(0.01, max(observadas) * 1.2))
        eixo.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Lance a Lance — avaliação A × B × C")
    fig.savefig(pasta / "comparacao.png", dpi=140)
    plt.close(fig)


def _ranking(metricas: dict, campo: str, maior=False) -> str:
    valores = {v: metricas[v][campo] for v in VERSOES}
    if any(valor is None for valor in valores.values()):
        return "Dados pareados insuficientes."
    destaque = (max if maior else min)(valores.values())
    return " / ".join(v for v, valor in valores.items() if valor == destaque) + f" ({destaque:.3f})."


def salvar_resultados(
    pasta: Path, dataset: list[dict], resultados: list[dict], config: dict,
    avaliacoes: Path | None = None,
) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    por_versao = {v: {r["id"]: r for r in resultados if r["versao"] == v} for v in VERSOES}
    # A comparação pareada usa somente posições com três respostas completas.
    pareados = sorted(set.intersection(*(
        {id_ for id_, r in dados.items() if r["status"] == "ok"} for dados in por_versao.values()
    )))
    chave = _amostra(pasta, pareados, por_versao, config["semente_amostra"], avaliacoes)
    humanas = _notas(avaliacoes, chave)
    metricas = {
        v: calcular_metricas(list(dados.values()), len(dataset), humanas[v])
        for v, dados in por_versao.items()
    }
    pareadas = {
        v: calcular_metricas([dados[id_] for id_ in pareados], len(pareados))
        for v, dados in por_versao.items()
    }
    _csv(pasta / "por_posicao.csv", resultados, _COLUNAS)
    _csv(pasta / "metricas.csv", ({"versao": v, **m} for v, m in metricas.items()),
         ("versao", *metricas["A"]))
    _grafico(pasta, metricas)
    origens = Counter(d["origem"]["tipo"] for d in dataset)
    completo = origens["lichess"] == 70 and origens["partida"] == 30 and len(pareados) == 100
    a, b, c = (pareadas[v] for v in VERSOES)
    modelo = config.get("modelo") or "indisponível"
    texto = [
        "# Avaliação Lance a Lance", "",
        f"**{'Cobertura A/B/C completa' if completo else 'Avaliação incompleta'}**.",
        f"Dataset com {len(dataset)}/100 posições, {origens['lichess']} da Lichess "
        f"e {origens['partida']} de partidas do grupo. {len(pareados)} tríades completas.",
        f"Modelo configurado: {modelo}. Semente da amostra cega: {config['semente_amostra']}.",
        "", "![Gráfico comparativo](comparacao.png)", "",
    ]
    motivo = config.get("preflight", {})
    if motivo:
        texto += ["## Disponibilidade", ""] + [f"- {v}: {status}" for v, status in motivo.items()] + [""]
    texto += ["## Leitura dos dados", ""]
    for v, m in metricas.items():
        texto.append(f"- {v}: {m['executadas']}/{m['previstas']} posições tentadas, "
                     f"{m['completas']} completas, {m['incompletas']} incompletas, "
                     f"{m['falhas']} falhas e {m['fallbacks']} fallbacks com texto.")
    texto += ["", "As comparações abaixo usam apenas posições com respostas completas nas três versões.", ""]
    texto.append(f"1. Menor taxa de lances inválidos: {_ranking(pareadas, 'invalidos_pct')}")
    if pareados:
        texto.append(f"2. B versus A com Stockfish: {b['invalidos_pct'] - a['invalidos_pct']:+.2f} pp "
                     f"em lances inválidos, {b['melhor_pct'] - a['melhor_pct']:+.2f} pp em melhor lance "
                     f"e {b['tema_pct'] - a['tema_pct']:+.2f} pp em tema, em {len(pareados)} posições.")
    else:
        texto.append("2. Efeito do Stockfish no prompt: dados pareados insuficientes.")
    mc = metricas["C"]
    texto += [
        f"3. RAG: {mc['ragas_n']} escores de fidelidade"
        + (f" (média {mc['ragas_media']:.3f})." if mc["ragas_n"] else ".")
        + " A e B são inaplicáveis. O desenho A/B/C combina RAG, ferramentas e validação em C.",
        f"4. Validador: {mc['rascunhos_invalidos'] if mc['rascunhos_n'] else 'n/d'} rascunhos com "
        f"lances inválidos em {mc['rascunhos_n']} rascunhos inspecionados. "
        + (f"Taxa final de C: {mc['invalidos_pct']:.2f}% em {mc['explicacoes']} explicações."
           if mc["explicacoes"] else "Sem explicações publicadas pela versão C."),
        "5. Maior custo estimado: " + (_ranking(pareadas, "custo_total_usd", maior=True)
             if pareados and all(m["custo_n"] == len(pareados) for m in (a, b, c))
             else "Cobertura de preços e tokens insuficiente nas tríades."),
        f"6. Maior tempo médio: {_ranking(pareadas, 'tempo_media_s', maior=True)}",
        "7. Limitações: ratings de puzzle e de jogador têm origens distintas, os rótulos públicos são "
        "multitema e a extração cobre citações em notação de xadrez. A alternativa de C é inserida "
        "pelo grafo a partir do motor. O estudo compara sistemas completos e não isola o efeito causal do RAG.",
        "8. Metas documentais de C:", "",
    ]
    elegiveis_ragas = sum(r["status"] == "ok" and bool(r.get("contextos_rag")) for r in por_versao["C"].values())
    for campo, (alvo, direcao) in METAS.items():
        valor = mc[campo]
        cobertura = (mc["humana_n"] == 90 if campo == "humana_media"
                     else mc["ragas_n"] == elegiveis_ragas > 0 if campo == "ragas_media" else mc["completas"] == 100)
        atingiu = valor is not None and (valor <= alvo if direcao == "max" else valor >= alvo)
        status = ("atingida" if atingiu else "não atingida") if completo and cobertura else "pendente"
        texto.append(f"- {campo}: {status}. Valor observado: {valor if valor is not None else 'n/d'}. Meta: {alvo}.")
    texto += ["", "## Exemplos lado a lado", ""]
    if not pareados:
        texto.append("Nenhuma tríade de respostas disponível.")
    for id_ in pareados[:3]:
        texto += [f"### {id_}", ""]
        for v in VERSOES:
            resposta = por_versao[v][id_]["texto"]
            texto += [f"**{v}**", "", *[f"> {linha}" for linha in resposta.splitlines()], ""]
    (pasta / "relatorio.md").write_text("\n".join(texto) + "\n", encoding="utf-8")
