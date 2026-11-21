"""Executa e documenta a avaliação A/B/C com checkpoint por posição e versão."""

import argparse
import asyncio
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
from random import Random
from time import perf_counter
from urllib.parse import urlsplit

from dotenv import load_dotenv

from evaluation.dataset import PASTA, SEMENTE, carregar_dataset
from evaluation.metrics import VERSOES, checar_lances, medir
from evaluation.report import salvar_resultados

RAIZ = PASTA.parent
CAMINHO_DATASET_PADRAO = PASTA / "dataset.jsonl"
PASTA_RESULTADOS = PASTA / "results" / "execucao"
MAX_PILOTO = 10
LIMITE_PADRAO_RAGAS = 3
PERGUNTA = "Explique o erro, recomende uma alternativa e ensine uma lição em português simples."
FORMATO = (
    "Escreva para jogadores até 1800 de rating. Responda em JSON sem bloco Markdown com "
    "os campos explicacao, melhor_lance e tema. A explicação tem até quatro frases. "
    "Use SAN padrão para qualquer lance. Uma variante sempre começa no FEN informado "
    "e deve ser escrita como uma sequência contínua em SAN. Evite coordenadas isoladas. "
    "melhor_lance é a única jogada que você recomenda, em SAN, ou null se indisponível. "
    "tema é um dos identificadores: "
)


def _json(caminho: Path, dados: dict):
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporario.replace(caminho)


def _versao(pacote: str) -> str | None:
    try:
        return version(pacote)
    except PackageNotFoundError:
        return None


def ler_checkpoint(caminho: Path) -> dict[tuple[str, str], dict]:
    """Recupera registros fechados por nova linha, removendo só a escrita interrompida."""
    if not caminho.is_file():
        return {}
    dados = caminho.read_bytes()
    fim = dados.rfind(b"\n") + 1
    recuperados = {}
    for linha in dados[:fim].splitlines():
        linha = json.loads(linha)
        recuperados[linha["id"], linha["versao"]] = linha
    if fim != len(dados):
        with caminho.open("r+b") as arquivo:
            arquivo.truncate(fim)
    return recuperados


def checkpoint(caminho: Path, resultado: dict) -> None:
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(resultado, ensure_ascii=False, allow_nan=False) + "\n")
        arquivo.flush()
        os.fsync(arquivo.fileno())


def _objeto(texto: str) -> dict:
    # Uma cerca Markdown acidental é interpretada para pontuar o conteúdo. Nenhuma resposta é reenviada.
    if texto.startswith("```") and texto.endswith("```") and "\n" in texto:
        texto = texto.split("\n", 1)[1][:-3].strip()
    try:
        dados = json.loads(texto)
        return dados if isinstance(dados, dict) else {}
    except ValueError:
        return {}


def _texto(dados: dict, campo: str) -> str:
    valor = dados.get(campo)
    return valor.strip() if isinstance(valor, str) else ""


def _erro(erro: Exception) -> str:
    status = getattr(erro, "status_code", None)
    return type(erro).__name__ + (f" (HTTP {status})" if type(status) is int else "")


def _endpoint(url: str | None) -> str:
    if not url:
        return "api.openai.com"
    destino = urlsplit(url)
    return f"{destino.scheme}://{destino.hostname}" + (f":{destino.port}" if destino.port else "")


class ModeloMedido:
    """Observa somente os retornos e contadores do mesmo modelo usado pelo grafo."""

    def __init__(self, modelo):
        self.modelo = modelo
        self.respostas = []
        self.erros = []
        self.chamadas = 0

    async def ainvoke(self, mensagens, **opcoes):
        self.chamadas += 1
        try:
            resposta = await self.modelo.ainvoke(mensagens, **opcoes)
        except Exception as erro:
            self.erros.append(_erro(erro))
            raise
        self.respostas.append(resposta)
        return resposta

    def consumo(self, precos: tuple[float, float] | None) -> dict:
        usos = [resposta.usage_metadata or {} for resposta in self.respostas]
        campos = ("input_tokens", "output_tokens")
        completos = [u for u in usos if all(type(u.get(k)) is int and u[k] >= 0 for k in campos)]
        completo = bool(completos) and len(completos) == self.chamadas
        entrada, saida = (sum(u[k] for u in completos) if completo else None for k in campos)
        custo = (entrada * precos[0] + saida * precos[1]) / 1_000_000 if precos and completo else None
        return {"chamadas_llm": self.chamadas, "chamadas_com_tokens": len(completos),
                "tokens_entrada": entrada, "tokens_saida": saida,
                "tokens_total": entrada + saida if completo else None, "custo_usd": custo}


def _mensagens_ab(item: dict, versao: str) -> list:
    from langchain_core.messages import HumanMessage, SystemMessage

    from agent.graph import TEMAS

    dados = {"fen": item["fen"], "lance_jogado": item["lance_jogado"]}
    if versao == "B":
        dados.update(avaliacao=item["motor"]["avaliacao"], melhor_lance=item["melhor_lance"],
                     linha_motor=item["motor"]["linha_principal"])
    return [SystemMessage(content=f"{PERGUNTA}\n{FORMATO}{', '.join(TEMAS)}"),
            HumanMessage(content=json.dumps(dados, ensure_ascii=False))]


async def _rodar_ab(item: dict, versao: str, observado: ModeloMedido) -> dict:
    from agent.graph import TEMAS
    from agent.llm import formato_json

    resposta = await observado.ainvoke(
        _mensagens_ab(item, versao), **formato_json(("explicacao", "melhor_lance", "tema"), nulos=("melhor_lance",)),
    )
    bruto = resposta.text.strip()
    dados = _objeto(bruto)
    explicacao, recomendado, tema = (_texto(dados, k) for k in ("explicacao", "melhor_lance", "tema"))
    recomendado, tema = recomendado or None, tema or None
    completa = bool(explicacao and recomendado and tema in TEMAS)
    texto = explicacao or bruto
    return {"texto": texto, "resposta_bruta": bruto, "recomendado": recomendado, "tema": tema,
            "status": "ok" if completa else "incompleta",
            "avaliavel": bool(texto), "validada_agente": None, "ragas_status": "inaplicavel_sem_rag",
            "erros": [] if completa else ["Resposta vazia ou com campos obrigatórios incompletos."]}


async def _rodar_c(item: dict, observado: ModeloMedido, *, exigir_mcp: bool = False) -> dict:
    from agent.graph import construir_grafo_explicacao
    from agent.mcp import Ferramentas, sessao_mcp

    async with sessao_mcp() as disponiveis:
        ferramentas = Ferramentas(disponiveis)
        estado = await construir_grafo_explicacao(observado, ferramentas, exigir_mcp=exigir_mcp).ainvoke({
            "fen": item["fen"], "lance_jogado": item["lance_jogado"],
            "melhor_lance": item["melhor_lance"], "linha_motor": item["motor"]["linha_principal"],
        })
    bloqueio_mcp = estado.get("bloqueio_mcp")
    texto = estado.get("texto", "") if not bloqueio_mcp else ""
    validada = estado.get("validada", False)
    usou_rag = any(r["nome"] == "buscar_conceitos" for r in ferramentas.usadas)
    contexto = estado.get("ficha")
    if estado.get("pronto") and validada and contexto:
        contextos = [contexto["texto"]]
        fonte_rag = {campo: contexto[campo] for campo in ("id", "titulo", "arquivo")}
        ragas_status = "pendente"
    else:
        contextos = []
        fonte_rag = None
        ragas_status = "inaplicavel_fallback" if validada and not estado.get("pronto") else "sem_contexto"
    respostas = [resposta.text for resposta in observado.respostas]
    rascunhos = []
    for bruto in respostas[1:]:
        partes = _objeto(bruto)
        rascunhos.append(". ".join(_texto(partes, k).rstrip(".!?")
                                  for k in ("aconteceu", "motivo", "licao")) if partes else bruto)
    invalidos = sum(any(l["legal"] is False for l in checar_lances(item["fen"], rascunho)) for rascunho in rascunhos)
    # O nó do agente sempre escreve a alternativa confirmada nesse formato.
    recomendacao = item["melhor_lance"] if validada and f"Stockfish indicou `{item['melhor_lance']}`" in texto else None
    completa = validada and bool(recomendacao) and bool(contextos) and not observado.erros
    erros = list(estado.get("erros", []))
    if not validada:
        erros.append("O agente não confirmou a resposta final.")
    elif not estado.get("pronto"):
        erros.append("O agente entregou apenas a explicação determinística de contingência.")
    if bloqueio_mcp:
        erros.append(f"Ferramenta obrigatória não retornou dados utilizáveis: {bloqueio_mcp}.")
    elif not usou_rag or not contexto:
        erros.append("A passagem pelo fluxo completo com recuperação de ficha não foi confirmada.")
    return {"texto": texto, "resposta_bruta": respostas, "recomendado": recomendacao,
            "tema": estado.get("tema"), "status": "ok" if completa else "incompleta",
            "avaliavel": bool(texto and validada), "validada_agente": validada,
            "tentativas": estado.get("tentativas", 0), "fallback": bool(validada and not estado.get("pronto")),
            "ferramentas_usadas": ferramentas.usadas, "contextos_rag": contextos, "ragas_status": ragas_status,
            "fonte_rag": fonte_rag, "bloqueio_mcp": bloqueio_mcp,
            "rascunhos_n": len(rascunhos), "rascunhos_invalidos": invalidos, "erros": erros}


async def rodar_versao(item: dict, versao: str, modelo, timeout: float, precos=None, *, exigir_mcp=False) -> dict:
    observado = ModeloMedido(modelo)
    inicio = perf_counter()
    try:
        if versao not in VERSOES:
            raise ValueError("Versão desconhecida.")
        tarefa = (_rodar_c(item, observado, exigir_mcp=exigir_mcp)
                  if versao == "C" else _rodar_ab(item, versao, observado))
        resultado = await asyncio.wait_for(tarefa, timeout)
    except Exception as erro:
        resultado = {"status": "erro", "avaliavel": False, "erros": [_erro(erro)],
                     "ragas_status": "sem_resposta" if versao == "C" else "inaplicavel_sem_rag"}
    segundos = perf_counter() - inicio
    if resultado["avaliavel"]:
        resultado.update(medir(item, resultado["texto"], resultado["recomendado"], resultado["tema"]))
    resultado["erros"].extend(observado.erros)
    return {"id": item["id"], "versao": versao, "fen": item["fen"], "origem": item["origem"],
            "lance_jogado": item["lance_jogado"], "melhor_referencia": item["melhor_lance"],
            "tema_esperado": item["tema_esperado"], "segundos": segundos,
            **observado.consumo(precos), **resultado}


def _config_modelo(args):
    from agent.llm import configurar_modelo

    return configurar_modelo(args.temperatura, args.timeout)


async def _preflight_c(item: dict) -> str | None:
    from agent.mcp import Ferramentas, sessao_mcp

    try:
        async with sessao_mcp() as disponiveis:
            ferramentas = Ferramentas(disponiveis)
            try:
                fatos = await ferramentas.chamar("descrever_posicao", fen=item["fen"])
                validacao = await ferramentas.validar(item["fen"], [item["lance_jogado"]])
                fichas = await ferramentas.chamar("buscar_conceitos", pergunta="garfo", k=1, tema="garfo")
            except RuntimeError as erro:
                return str(erro)
            if not isinstance(fatos, dict) or not fatos or "erro" in fatos:
                return "descrever_posicao retornou dados insuficientes."
            if not validacao or validacao[0].get("legal") is not True:
                return "validar_lances não confirmou um lance do dataset."
            if not fichas or not fichas[0].get("texto"):
                return "O índice RAG não devolveu uma ficha. Execute python -m knowledge_base.index."
    except Exception as erro:
        return f"Sessão MCP indisponível: {_erro(erro)}."
    return None


async def _executar(args, dataset, modelo, caminho, obtidos, config):
    disponiveis = []
    for versao in args.versoes:
        if not dataset:
            config["preflight"][versao] = "Dataset vazio."
        elif modelo is None:
            config["preflight"][versao] = "Configure LLM_PROVIDER, LLM_MODEL e a credencial quando exigida."
        elif versao == "C" and (problema := await _preflight_c(dataset[0])):
            config["preflight"][versao] = problema
        else:
            config["preflight"][versao] = "Disponível."
            disponiveis.append(versao)
    for item in dataset:
        ordem = Random(f"{args.semente}:{item['id']}").sample(VERSOES, len(VERSOES))
        for versao in (v for v in ordem if v in disponiveis):
            chave = item["id"], versao
            anterior = obtidos.get(chave)
            if anterior and (not args.repetir_falhas or anterior["status"] == "ok"):
                continue
            resultado = await rodar_versao(item, versao, modelo, args.timeout, args.precos)
            checkpoint(caminho, resultado)
            obtidos[chave] = resultado
            print(f"{versao} {item['id']} {resultado['status']}", flush=True)


async def _ragas(args, obtidos, caminho, chave, base_url, config):
    """Avalia somente saídas que realmente receberam contexto RAG."""
    elegiveis = [
        (k, item) for k, item in obtidos.items()
        if item["versao"] == "C" and item["status"] == "ok" and item.get("contextos_rag") and item.get("ragas") is None
    ]
    if not elegiveis:
        print("RAGAS: nenhuma resposta C pendente com contexto recuperado.")
        return
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import Faithfulness

    opcoes_juiz = {}
    if raciocinio := os.getenv("RAGAS_RACIOCINIO"):
        opcoes_juiz["reasoning_effort"] = raciocinio
    julgamento = {"versao": _versao("ragas"), "metrica": "Faithfulness", "modelo": args.ragas_model,
                  "temperatura": 0.0, "contexto": "trecho recuperado e entregue ao LLM", "timeout_s": args.timeout,
                  "endpoint": _endpoint(base_url), "raciocinio": opcoes_juiz.get("reasoning_effort")}
    registro = args.resultados / "ragas_config.json"
    if registro.is_file() and json.loads(registro.read_text(encoding="utf-8")) != julgamento:
        raise ValueError("A configuração do juiz mudou. Use outra pasta para preservar a comparabilidade.")
    _json(registro, julgamento)
    config["ragas"] = julgamento
    async with AsyncOpenAI(api_key=chave, base_url=base_url, timeout=args.timeout, max_retries=0) as cliente:
        juiz = Faithfulness(llm=llm_factory(args.ragas_model, client=cliente, temperature=0.0, **opcoes_juiz))
        for k, item in sorted(elegiveis)[:args.limite_ragas]:
            try:
                nota = await asyncio.wait_for(juiz.ascore(
                    user_input=f"{PERGUNTA} FEN: {item['fen']}. Lance jogado: {item['lance_jogado']}.",
                    response=item["texto"], retrieved_contexts=item["contextos_rag"],
                ), args.timeout)
                valor = float(nota.value)
                if not math.isfinite(valor) or not 0 <= valor <= 1:
                    raise ValueError("Escore inválido.")
                item = {**item, "ragas": valor, "ragas_status": "ok"}
            except Exception as erro:
                item = {**item, "ragas_status": f"erro: {_erro(erro)}"}
            checkpoint(caminho, item)
            obtidos[k] = item


def _fingerprint(arquivos: list[Path]) -> str:
    digest = sha256()
    for caminho in sorted(arquivos):
        digest.update(str(caminho.relative_to(RAIZ)).encode() + b"\0")
        digest.update(caminho.read_bytes() + b"\0")
    return digest.hexdigest()


def main() -> None:
    load_dotenv(RAIZ / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CAMINHO_DATASET_PADRAO)
    parser.add_argument("--resultados", type=Path, default=PASTA_RESULTADOS)
    parser.add_argument("--versoes", nargs="+", choices=VERSOES, default=list(VERSOES))
    escopo = parser.add_mutually_exclusive_group()
    escopo.add_argument("--limite", type=int, help=f"Executa um piloto de 1 a {MAX_PILOTO} posições.")
    escopo.add_argument("--completa", action="store_true", help="Executa todas as posições disponíveis.")
    parser.add_argument("--semente", type=int, default=SEMENTE)
    parser.add_argument("--temperatura", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--precos", nargs=2, type=float, metavar=("USD_ENTRADA", "USD_SAIDA"),
                        help="Preços por milhão de tokens. Informe ambos para estimar custo.")
    parser.add_argument("--repetir-falhas", action="store_true")
    parser.add_argument("--somente-relatorio", action="store_true", help="Exporta o checkpoint sem gerar explicações.")
    parser.add_argument("--ragas-model", default=os.getenv("RAGAS_MODEL"))
    parser.add_argument("--ragas", action="store_true", help="Pontua as respostas C que utilizaram contexto.")
    juiz_escopo = parser.add_mutually_exclusive_group()
    juiz_escopo.add_argument("--limite-ragas", type=int,
                            help=f"Máximo de respostas enviadas ao juiz RAGAS (padrão {LIMITE_PADRAO_RAGAS}).")
    juiz_escopo.add_argument("--ragas-completo", action="store_true",
                            help="Autoriza pontuar todas as respostas C pendentes com RAGAS.")
    parser.add_argument("--avaliacoes-humanas", type=Path)
    args = parser.parse_args()
    if args.limite is not None and not 1 <= args.limite <= MAX_PILOTO:
        parser.error(f"--limite deve estar entre 1 e {MAX_PILOTO}. Use --completa para toda a amostra.")
    executar = args.limite is not None or args.completa
    if args.somente_relatorio and executar:
        parser.error("--somente-relatorio já usa o escopo registrado no checkpoint.")
    if args.ragas and not (executar or args.somente_relatorio):
        parser.error("--ragas exige um escopo de execução ou --somente-relatorio.")
    if not args.ragas and (args.ragas_completo or args.limite_ragas is not None):
        parser.error("O escopo do juiz exige --ragas.")
    if args.limite_ragas is not None and not 1 <= args.limite_ragas <= MAX_PILOTO:
        parser.error(f"--limite-ragas deve estar entre 1 e {MAX_PILOTO}. Use --ragas-completo para toda a amostra.")
    if not args.ragas_completo and args.limite_ragas is None:
        args.limite_ragas = LIMITE_PADRAO_RAGAS
    if not math.isfinite(args.timeout) or args.timeout <= 0 or not math.isfinite(args.temperatura):
        parser.error("Timeout e temperatura inválidos.")
    if args.precos and any(not math.isfinite(p) or p < 0 for p in args.precos):
        parser.error("Preços devem ser finitos e não negativos.")
    if args.ragas and not args.ragas_model:
        parser.error("Configure RAGAS_MODEL ou --ragas-model ao usar --ragas.")
    hash_dataset = sha256(args.dataset.read_bytes()).hexdigest()
    dataset = carregar_dataset(args.dataset)
    if not executar and not args.somente_relatorio:
        versoes = list(dict.fromkeys(args.versoes))
        print(f"Planejamento: {len(dataset)} posições validadas, versões {', '.join(versoes)}, "
              f"até {len(dataset) * len(versoes)} pares posição/versão.")
        print("Use --limite N para um piloto ou --completa para executar todas as posições.")
        return
    pasta = args.resultados
    config_path = pasta / "config.json"
    caminho = pasta / "checkpoint.jsonl"
    anterior = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None
    if args.somente_relatorio and anterior is not None:
        if anterior["dataset_sha256"] != hash_dataset:
            parser.error("Informe o dataset original para exportar o checkpoint.")
        por_id = {item["id"]: item for item in dataset}
        dataset = [por_id[id_] for id_ in anterior["ids"]]
        args.semente = anterior["semente_amostra"]
    if args.limite is not None and len(dataset) > args.limite:
        indices = sorted(Random(args.semente).sample(range(len(dataset)), args.limite))
        dataset = [dataset[i] for i in indices]
    nome, provedor, modelo, chave, base_url = _config_modelo(args) if not args.somente_relatorio else (
        None, None, None, os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"), os.getenv("LLM_BASE_URL"),
    )
    pasta.mkdir(parents=True, exist_ok=True)
    fonte_meta = args.dataset.with_suffix(".meta.json")
    from agent.llm import timeout_llm

    origem_meta = json.loads(fonte_meta.read_text(encoding="utf-8")) if fonte_meta.is_file() else {}
    if origem_meta.get("dataset_sha256", hash_dataset) != hash_dataset:
        parser.error("O hash do dataset diverge dos metadados de referência.")
    identidade = {
        "dataset_sha256": hash_dataset,
        "ids": [item["id"] for item in dataset], "semente_amostra": args.semente,
    }
    config = {
        **identidade, "modelo": nome, "provedor": provedor, "temperatura": args.temperatura,
        "endpoint_llm": _endpoint(base_url),
        "modelo_revisao": os.getenv("LLM_REVISAO") or None,
        "raciocinio": os.getenv("LLM_RACIOCINIO") or None,
        "max_tokens_por_chamada": int(os.environ["LLM_MAX_TOKENS"]) if os.getenv("LLM_MAX_TOKENS") else None,
        "timeout_modelo_s": min(args.timeout, timeout_llm()),
        "formato_json": os.getenv("LLM_JSON_MODE") == "1",
        "timeout_s": args.timeout, "precos_por_milhao_usd": args.precos, "fonte_dataset": origem_meta,
        "bibliotecas": {p: _versao(p) for p in ("chess", "langchain-openai", "langgraph", "ragas", "chromadb")},
        "codigo_sha256": _fingerprint([*PASTA.glob("*.py"), *RAIZ.joinpath("agent").glob("*.py"),
                                       *RAIZ.joinpath("agent/prompts").glob("*.md"),
                                       *RAIZ.joinpath("mcp_server/tools").glob("*.py"),
                                       RAIZ / "knowledge_base/index.py"]),
        "fichas_sha256": _fingerprint(list(RAIZ.joinpath("knowledge_base").glob("*.md"))),
        "embeddings_model": os.getenv("EMBEDDING_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "mcp_transporte": "http" if os.getenv("MCP_URL") else "stdio",
        "preflight": {},
    }
    if anterior is not None:
        chaves = identidade if args.somente_relatorio else set(config) - {"preflight"}
        if any(anterior[k] != config[k] for k in chaves):
            parser.error("A configuração diverge do checkpoint. Use outra pasta ou a configuração original.")
        config = anterior
    elif caminho.is_file():
        parser.error("Checkpoint sem manifesto de configuração.")
    elif not args.somente_relatorio and modelo is not None:
        _json(config_path, config)
    obtidos = ler_checkpoint(caminho)
    try:
        if not args.somente_relatorio:
            asyncio.run(_executar(args, dataset, modelo, caminho, obtidos, config))
        if args.ragas:
            local = (os.getenv("LLM_PROVIDER") or "").lower() == "ollama"
            juiz_chave = os.getenv("RAGAS_API_KEY") or chave or ("ollama" if local else None)
            juiz_url = os.getenv("RAGAS_BASE_URL") or base_url or ("http://localhost:11434/v1" if local else None)
            if not juiz_chave:
                parser.error("Configure a chave do endpoint do juiz RAGAS.")
            asyncio.run(_ragas(args, obtidos, caminho, juiz_chave, juiz_url, config))
    finally:
        if config_path.is_file():
            _json(config_path, config)
        resultados = sorted(obtidos.values(), key=lambda r: (r["id"], r["versao"]))
        salvar_resultados(pasta, dataset, resultados, config, args.avaliacoes_humanas)
        print(f"{len(resultados)} execuções registradas em {pasta}.")
    if not args.somente_relatorio and any(config["preflight"].get(v) != "Disponível." for v in args.versoes):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
