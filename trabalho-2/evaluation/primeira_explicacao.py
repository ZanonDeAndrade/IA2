"""Verifica uma posição real e, sob autorização explícita, executa o agente."""

import argparse
import asyncio
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv

from agent.mcp import RAIZ, Ferramentas, sessao_mcp
from agent.validator import ler_fen
from evaluation.dataset import lance_legal
from evaluation.run_eval import CAMINHO_DATASET_PADRAO, _config_modelo, carregar_dataset, rodar_versao


def _linha_motor(fen: str, dados: dict) -> list[str]:
    if not isinstance(dados, dict) or dados.get("avaliacao") is None:
        raise ValueError("O Stockfish não retornou a avaliação da posição.")
    variante = dados.get("linha_principal")
    if not isinstance(variante, list) or not variante or not all(isinstance(san, str) for san in variante):
        raise ValueError("O Stockfish não retornou uma variante principal utilizável.")
    tabuleiro = ler_fen(fen)
    linha = []
    for san in variante:
        try:
            movimento = lance_legal(tabuleiro, san)
        except ValueError as erro:
            raise ValueError("A variante retornada pelo Stockfish contém lance inválido.") from erro
        linha.append(tabuleiro.san(movimento))
        tabuleiro.push(movimento)
    return linha


async def verificar(item: dict) -> dict:
    """Verifica o motor e as ferramentas necessárias ao grafo, sem chamar o LLM."""
    fen, jogado = item["fen"], item["lance_jogado"]
    saida = {"id": item["id"], "fen": fen, "lance_jogado": jogado, "status": "bloqueado",
             "etapa": "sessao_mcp", "ferramentas_preflight": []}
    try:
        async with sessao_mcp() as disponiveis:
            ferramentas = Ferramentas(disponiveis)
            saida["ferramentas_preflight"] = ferramentas.usadas
            try:
                saida["etapa"] = "analisar_posicao"
                analise = await ferramentas.chamar("analisar_posicao", fen=fen, profundidade=18, multipv=3)
                linha = _linha_motor(fen, analise)
                depois = ler_fen(fen)
                lance = lance_legal(depois, jogado)
                if linha[0] == depois.san(lance):
                    raise ValueError("A análise ao vivo recomendou a jogada da partida. Selecione outra posição.")
                depois.push(lance)
                saida["motor"] = {"avaliacao": analise["avaliacao"], "linha_principal": linha}

                saida["etapa"] = "descrever_posicao"
                for posicao in (fen, depois.fen()):
                    fatos = await ferramentas.chamar("descrever_posicao", fen=posicao)
                    if not isinstance(fatos, dict) or not fatos or "erro" in fatos:
                        raise ValueError("A descrição da posição não retornou fatos utilizáveis.")

                saida["etapa"] = "validar_lances"
                confirmados = await ferramentas.validar(fen, [jogado, linha[0]])
                if (
                    not isinstance(confirmados, list) or len(confirmados) != 2
                    or any(not isinstance(registro, dict) or registro.get("legal") is not True
                           or registro.get("lance") != san or registro.get("san") != san
                           for registro, san in zip(confirmados, (jogado, linha[0])))
                ):
                    raise ValueError("A ferramenta não confirmou os dois lances no formato esperado.")

                saida["etapa"] = "buscar_conceitos"
                tema = item["tema_esperado"]
                fichas = await ferramentas.chamar("buscar_conceitos", pergunta=tema, k=4, tema=tema)
                ficha = next((f for f in fichas if isinstance(f, dict) and f.get("id") == tema
                              and all(isinstance(f.get(k), str) and f[k] for k in ("titulo", "arquivo", "texto"))),
                             None) if isinstance(fichas, list) else None
                if ficha is None:
                    raise ValueError("A busca não recuperou uma ficha compatível. Confira o índice RAG.")
                saida["fonte_preflight"] = {k: ficha[k] for k in ("id", "titulo", "arquivo")}
            except (RuntimeError, ValueError) as erro:
                return {**saida, "motivo": str(erro)}
    except Exception as erro:
        return {**saida, "motivo": f"Falha na sessão MCP ({type(erro).__name__})."}
    return {**saida, "status": "preflight_ok", "etapa": "preflight"}


async def executar(item: dict, args: argparse.Namespace) -> dict:
    saida = await verificar(item)
    if saida["status"] != "preflight_ok" or not args.executar:
        return saida
    if (os.getenv("LLM_PROVIDER") or "").lower() not in {"openai", "ollama"}:
        return {**saida, "status": "bloqueado", "etapa": "llm",
                "motivo": "Selecione LLM_PROVIDER e configure LLM_MODEL e a credencial quando exigida."}
    try:
        _, _, modelo, _, _ = _config_modelo(args)
    except Exception as erro:
        return {**saida, "status": "bloqueado", "etapa": "llm",
                "motivo": f"Falha ao configurar o LLM ({type(erro).__name__})."}
    if modelo is None:
        return {**saida, "status": "bloqueado", "etapa": "llm",
                "motivo": "Configure LLM_MODEL e a credencial quando exigida."}
    motor = saida["motor"]
    caso = {**item, "motor": motor, "melhor_lance": motor["linha_principal"][0]}
    resultado = await rodar_versao(caso, "C", modelo, args.timeout, exigir_mcp=True)
    aprovada = (
        resultado["status"] == "ok" and resultado.get("validada_agente")
        and not resultado.get("fallback") and not resultado.get("tem_lance_invalido")
    )
    bloqueio = resultado.get("bloqueio_mcp")
    status = "explicacao_validada" if aprovada else ("bloqueado" if bloqueio else "incompleto")
    return {
        **saida, "status": status, "etapa": bloqueio or "agente",
        "explicacao": resultado.get("texto") if aprovada else None, "tema_identificado": resultado.get("tema"),
        "melhor_lance": motor["linha_principal"][0], "validada": aprovada, "fonte_agente": resultado.get("fonte_rag"),
        "fallback": resultado.get("fallback", False), "tentativas": resultado.get("tentativas", 0),
        "ferramentas_agente": resultado.get("ferramentas_usadas", []), "erros": resultado["erros"],
        "chamadas_llm": resultado["chamadas_llm"],
        "tokens_entrada": resultado["tokens_entrada"], "tokens_saida": resultado["tokens_saida"],
        "rascunhos_invalidos": resultado.get("rascunhos_invalidos", 0),
    }


def main() -> None:
    load_dotenv(RAIZ / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CAMINHO_DATASET_PADRAO)
    parser.add_argument("--id", help="Identificador da posição. O padrão é a primeira do dataset.")
    parser.add_argument("--executar", action="store_true", help="Autoriza chamar o LLM configurado para esta posição.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Tempo máximo do fluxo do agente, em segundos.")
    parser.add_argument("--temperatura", type=float, default=0.0)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0 or not math.isfinite(args.temperatura):
        parser.error("Timeout ou temperatura inválidos.")
    dataset = carregar_dataset(args.dataset)
    item = next((caso for caso in dataset if args.id is None or caso["id"] == args.id), None)
    if item is None:
        parser.error("Nenhuma posição encontrada para o identificador informado.")
    saida = asyncio.run(executar(item, args))
    print(json.dumps(saida, ensure_ascii=False, indent=2))
    if saida["status"] in {"bloqueado", "incompleto"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
