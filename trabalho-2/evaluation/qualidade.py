"""Auditoria C pareada, com divisão congelada e contextos de fidelidade separados."""

import argparse
import asyncio
from collections import Counter, defaultdict
import csv
from hashlib import sha256
from importlib.metadata import version
import json
from math import isfinite
from pathlib import Path
from statistics import fmean

import chess

from agent.mcp import Ferramentas, sessao_mcp
from evaluation.dataset import carregar_dataset
from evaluation.metrics import calcular_metricas
from evaluation.run_eval import PERGUNTA
from knowledge_base.index import carregar_trechos

PASTA = Path(__file__).parent
HISTORICO = PASTA / "results/qwen3-c-final/checkpoint.jsonl"
SEMENTE = "lance-a-lance-temas-20261121-v1"
LOCAL = "http://127.0.0.1:11435/v1"
MODELO = "qwen3:1.7b"
REVISAO = "8f68893c685c"


def _gravar(caminho, valor):
    with caminho.open("x", encoding="utf-8") as arquivo:
        json.dump(valor, arquivo, ensure_ascii=False, indent=2)
        arquivo.write("\n")


def _respostas(caminho):
    respostas = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        registro = json.loads(linha)
        if registro["versao"] == "C":
            respostas[registro["id"]] = registro
    return respostas


def _ordem(id_):
    return sha256(f"{SEMENTE}:{id_}".encode()).digest()


def dividir(dataset):
    grupos = defaultdict(list)
    for item in dataset:
        grupos[item["tema_esperado"]].append(item["id"])
    divisao = {"desenvolvimento": [], "validacao": [], "ragas_validacao": []}
    for ids in grupos.values():
        ordenados = sorted(ids, key=_ordem)
        total_validacao = len(ids) * 4 // 9
        divisao["validacao"].extend(ordenados[:total_validacao])
        divisao["desenvolvimento"].extend(ordenados[total_validacao:])
        if total_validacao:
            divisao["ragas_validacao"].append(ordenados[0])
    return {"semente": SEMENTE, **divisao}


def _jsonl(caminho, registros):
    with caminho.open("x", encoding="utf-8") as f:
        for registro in registros:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _resumo_mcp(descricao):
    return {k: descricao[k] for k in (
        "lado_a_jogar", "pecas", "pecas_atacadas", "pecas_cravadas", "xeques_possiveis", "em_xeque", "xeque_mate",
    )}


def _trilha(tabuleiro, linha):
    nomes = ("", "peão", "cavalo", "bispo", "torre", "dama", "rei")
    fatos = []
    for san in linha[:8]:
        movimento = tabuleiro.parse_san(san)
        peca = tabuleiro.piece_at(movimento.from_square)
        nome = nomes[peca.piece_type]
        lado = "brancas" if tabuleiro.turn else "pretas"
        captura = tabuleiro.piece_at(movimento.to_square)
        tipo = f" captura {nomes[captura.piece_type]}" if captura else " captura peão en passant" if tabuleiro.is_en_passant(movimento) else ""
        tabuleiro.push(movimento)
        efeito = " e dá xeque-mate" if tabuleiro.is_checkmate() else " e dá xeque" if tabuleiro.is_check() else ""
        fatos.append(f"{lado} jogam {san} com {nome}{tipo}{efeito}")
    return fatos


def _contexto_tabuleiro(item, analise):
    raiz = chess.Board(item["fen"])
    realizado = _trilha(raiz, [item["lance_jogado"]])[0]
    depois = _trilha(raiz, analise["linha_principal"])
    alternativa = _trilha(chess.Board(item["fen"]), item["motor"]["linha_principal"])
    avaliacao = analise["avaliacao"]
    mate = (" O motor constatou mate forçado para o lado a jogar após o erro."
            if avaliacao["tipo"] == "mate" and avaliacao["valor"] > 0 else "")
    return (f"Lance realizado: {realizado}. Variante principal após o erro: {'; '.join(depois)}. "
            f"Melhor alternativa na posição inicial segundo Stockfish: {item['melhor_lance']}. "
            f"Variante da melhor alternativa: {'; '.join(alternativa)}.{mate}")


async def preparar(pasta):
    dataset = carregar_dataset()
    respostas = _respostas(HISTORICO)
    if set(respostas) != {d["id"] for d in dataset} or any(
        (r["fen"], r["lance_jogado"]) != (d["fen"], d["lance_jogado"])
        for d in dataset for r in [respostas[d["id"]]]
    ):
        raise ValueError("A linha de base diverge do dataset íntegro.")
    divisao = dividir(dataset)
    pasta.mkdir(parents=True, exist_ok=True)
    _gravar(pasta / "divisao.json", {**divisao, "dataset_sha256": sha256((PASTA / "dataset.jsonl").read_bytes()).hexdigest(),
                                   "checkpoint_base_sha256": sha256(HISTORICO.read_bytes()).hexdigest()})
    for grupo in ("desenvolvimento", "validacao"):
        _jsonl(pasta / f"{grupo}.jsonl", (d for d in dataset if d["id"] in divisao[grupo]))
    async with sessao_mcp() as disponiveis:
        ferramentas = Ferramentas(disponiveis)
        with (pasta / "auditoria_base.jsonl").open("x", encoding="utf-8") as arquivo:
            for item in dataset:
                tabuleiro = chess.Board(item["fen"])
                tabuleiro.push_san(item["lance_jogado"])
                descricoes = [await ferramentas.chamar("descrever_posicao", fen=fen) for fen in (item["fen"], tabuleiro.fen())]
                analise = await ferramentas.chamar("analisar_posicao", fen=tabuleiro.fen(), profundidade=16, multipv=1)
                r = respostas[item["id"]]
                d = {"id": item["id"], "tema_esperado": item["tema_esperado"], "tema_anterior": r["tema"],
                     "fen": item["fen"], "jogado": item["lance_jogado"], "melhor": item["melhor_lance"],
                     "descricao_antes": _resumo_mcp(descricoes[0]), "descricao_depois": _resumo_mcp(descricoes[1]),
                     "linha_apos_erro": analise["linha_principal"], "avaliacao_apos_erro": analise["avaliacao"],
                     "contexto_tabuleiro": _contexto_tabuleiro(item, analise), "ficha": r["fonte_rag"],
                     "trecho": r["contextos_rag"], "explicacao": r["texto"]}
                arquivo.write(json.dumps(d, ensure_ascii=False) + "\n")
                arquivo.flush()
        cards = []
        for texto, meta in carregar_trechos(Path("knowledge_base")).values():
            termo = meta["titulo"]
            filtrado = await ferramentas.chamar("buscar_conceitos", pergunta=termo, tema=meta["tema_pt"], k=4)
            livre = await ferramentas.chamar("buscar_conceitos", pergunta=termo, k=4)
            cards.append({**meta, "secoes": [l[3:] for l in texto.splitlines() if l.startswith("## ")],
                          "filtrado": [d["id"] for d in filtrado], "livre": [d["id"] for d in livre]})
        _gravar(pasta / "auditoria_fichas.json", cards)


def comparar(pasta, checkpoint):
    divisao = json.loads((pasta / "divisao.json").read_text(encoding="utf-8"))
    conjuntos = {k: divisao[k] for k in ("desenvolvimento", "validacao")}
    conjuntos["total"] = conjuntos["desenvolvimento"] + conjuntos["validacao"]
    fontes = {"nova": _respostas(checkpoint)} if checkpoint else {"base": _respostas(HISTORICO)}
    for nome, respostas in fontes.items():
        grupos = {k: [respostas[i] for i in ids if i in respostas] for k, ids in conjuntos.items()}
        _gravar(pasta / f"metricas_{nome}.json", {k: calcular_metricas(valores, len(conjuntos[k])) for k, valores in grupos.items()})
        for grupo, registros in grupos.items():
            colunas = sorted({r.get("tema") or "sem_tema" for r in registros} | {r["tema_esperado"] for r in registros})
            ocorrencias = Counter((r["tema_esperado"], r.get("tema") or "sem_tema") for r in registros)
            with (pasta / f"matriz_{nome}_{grupo}.csv").open("x", encoding="utf-8", newline="") as arquivo:
                csv_ = csv.writer(arquivo, lineterminator="\n")
                csv_.writerow(["esperado / previsto", *colunas])
                for esperado in sorted({r["tema_esperado"] for r in registros}):
                    csv_.writerow([esperado, *(ocorrencias[esperado, previsto] for previsto in colunas)])


def diagnosticar(pasta, checkpoint):
    """Compara a solução pública somente na auditoria, depois das inferências."""
    from agent.taticas import candidatos_taticos

    dados = {d["id"]: d for d in carregar_dataset()}
    saidas = _respostas(checkpoint)
    divisao = json.loads((pasta / "divisao.json").read_text())
    registros = []
    for linha in (pasta / "auditoria_base.jsonl").read_text().splitlines():
        auditoria = json.loads(linha)
        id_ = auditoria["id"]
        item, resposta = dados[id_], saidas[id_]
        esperado = item["tema_esperado"]
        tabuleiro = chess.Board(item["fen"])
        tabuleiro.push_san(item["lance_jogado"])
        copia = tabuleiro.copy(stack=False)
        solucao = []
        for uci in item["origem"].get("moves_uci", [])[1:]:
            jogada = copia.parse_uci(uci)
            solucao.append(copia.san(jogada))
            copia.push(jogada)
        analise = {"linha_principal": solucao, "avaliacao": {"tipo": "mate", "valor": (len(solucao) + 1) // 2}
                   if solucao and copia.is_checkmate() and copia.turn != tabuleiro.turn else {}}
        temas_solucao = [e.tema for e in candidatos_taticos(tabuleiro, analise)]
        temas_pv = [e["tema"] for e in resposta.get("evidencias_taticas", [])]
        if resposta.get("tema") == esperado:
            diagnostico = "acerto"
        elif esperado in temas_pv:
            diagnostico = "evidencias concorrentes na PV"
        elif esperado in temas_solucao:
            diagnostico = "motivo detectado apenas na solução pública"
        else:
            diagnostico = "motivo de referência sem evidência nas regras atuais"
        registros.append({"id": id_, "grupo": "validacao" if id_ in divisao["validacao"] else "desenvolvimento",
                          "esperado": esperado, "anterior": auditoria["tema_anterior"], "novo": resposta.get("tema"),
                          "pv": " ".join(auditoria["linha_apos_erro"][:10]), "solucao_publica": " ".join(solucao),
                          "evidencias_pv": ", ".join(temas_pv), "evidencias_solucao": ", ".join(temas_solucao),
                          "diagnostico": diagnostico, "ficha_anterior": (auditoria["ficha"] or {}).get("id"),
                          "ficha_nova": (resposta.get("fonte_rag") or {}).get("id")})
    with (pasta / "diagnostico_pareado.csv").open("x", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(registros[0]), lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(registros)


async def julgar(pasta, checkpoint, nome):
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import Faithfulness

    ids = json.loads((pasta / "divisao.json").read_text(encoding="utf-8"))["ragas_validacao"]
    auditoria = {r["id"]: r for r in map(json.loads, (pasta / "auditoria_base.jsonl").read_text().splitlines())}
    saidas = _respostas(checkpoint or HISTORICO)
    caminho = pasta / f"ragas_{nome}.jsonl"
    vistos = {(d["id"], d["regime"]) for d in map(json.loads, caminho.read_text().splitlines())} if caminho.exists() else set()
    async with AsyncOpenAI(api_key="ollama", base_url=LOCAL, timeout=210, max_retries=0) as cliente:
        juiz = Faithfulness(llm=llm_factory(MODELO, client=cliente, temperature=0.0, reasoning_effort="none"))
        with caminho.open("a", encoding="utf-8") as arquivo:
            for id_ in ids:
                r = saidas.get(id_, {})
                if r.get("status") != "ok" or not r.get("contextos_rag"):
                    continue
                pergunta = f"{PERGUNTA} FEN: {r['fen']}. Lance jogado: {r['lance_jogado']}."
                afirmacoes = None
                for regime in ("ficha", "ficha_e_tabuleiro"):
                    if (id_, regime) in vistos:
                        continue
                    contextos = list(r["contextos_rag"])
                    if regime == "ficha_e_tabuleiro":
                        evidencia = auditoria[id_]
                        descricao = evidencia["descricao_depois"]
                        contextos.append(evidencia["contexto_tabuleiro"] +
                                         f" Casas e defensores das peças atacadas após o erro: {descricao['pecas_atacadas']}. "
                                         f"Xeques legais após o erro: {descricao['xeques_possiveis']}.")
                    registro = {"id": id_, "regime": regime, "resposta": r["texto"], "contextos": contextos,
                                "pergunta": pergunta, "ficha": r["fonte_rag"], "modelo": MODELO,
                                "revisao": REVISAO, "ragas": version("ragas"), "temperatura": 0,
                                "raciocinio": "none", "timeout_s": 210, "nota": None}
                    try:
                        if afirmacoes is None:
                            afirmacoes = await asyncio.wait_for(juiz._create_statements(pergunta, r["texto"]), 210)
                        vereditos = await asyncio.wait_for(juiz._create_verdicts(afirmacoes, "\n".join(contextos)), 210) if afirmacoes else []
                        registro["afirmacoes"] = afirmacoes
                        registro["vereditos"] = vereditos.model_dump() if vereditos else None
                        if vereditos and isfinite(nota := juiz._compute_score(vereditos)):
                            registro["nota"] = nota
                    except Exception as erro:
                        registro["erro"] = type(erro).__name__
                    arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
                    arquivo.flush()
                    print(nome, id_, regime, registro["nota"], flush=True)
    linhas = list(map(json.loads, caminho.read_text().splitlines()))
    for regime in ("ficha", "ficha_e_tabuleiro"):
        notas = [r["nota"] for r in linhas if r["regime"] == regime and r["nota"] is not None]
        print(nome, regime, len(notas), fmean(notas) if notas else None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acao", choices=("preparar", "comparar", "diagnosticar", "julgar"))
    parser.add_argument("pasta", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--nome", choices=("base", "nova"), default="base")
    args = parser.parse_args()
    if args.acao == "preparar":
        asyncio.run(preparar(args.pasta))
    elif args.acao == "comparar":
        comparar(args.pasta, args.checkpoint)
    elif args.acao == "diagnosticar":
        if not args.checkpoint:
            parser.error("diagnosticar exige --checkpoint com as respostas da revisão.")
        diagnosticar(args.pasta, args.checkpoint)
    else:
        asyncio.run(julgar(args.pasta, args.checkpoint, args.nome))
