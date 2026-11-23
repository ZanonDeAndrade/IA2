"""Fluxos LangGraph de explicação e chat, com validação antes da publicação."""

import asyncio
from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import re
from typing import TypedDict

import chess

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from agent.mcp import RAIZ, Ferramentas, carregar_ferramentas_mcp as carregar_ferramentas_mcp, sessao_mcp
from agent.taticas import candidatos_taticos, justificar_alternativa
from agent.validator import explicacao_padrao, extrair_lances, ler_fen, validar_resposta_async

LOGGER = logging.getLogger(__name__)
MAX_TENTATIVAS = 3
MAX_RODADAS_MCP = 4
TEMAS = {
    "garfo": "Garfo", "cravada": "Cravada", "espeto": "Espeto",
    "ataque_descoberto": "Ataque descoberto", "peca_pendurada": "Peça pendurada",
    "mate": "Xeque-mate", "sobrecarga": "Sobrecarga", "desvio": "Desvio",
    "atracao": "Atração", "ataque_duplo": "Ataque duplo", "outro": "Outro",
}
_CHAT_TOOLS = {"descrever_posicao", "analisar_posicao", "buscar_conceitos"}
_SEM_RESPOSTA = "Não foi possível confirmar uma resposta para esta posição."
_AVALIACAO_NUMERICA = re.compile(
    r"[+−-]\s*\d|\d+[.,]\d+|\d\s*(?:%|cp\b|centipe(?:ão|ões)\b)|\bmate em\s+\d",
    re.IGNORECASE,
)
_RECOMENDACAO = re.compile(r"\b(?:melhor (?:lance|jogada)|eu jogaria|jogue|recomendo jogar)\b", re.IGNORECASE)
_AMEACA = re.compile(r"ameaç|ataca|sob ataque", re.IGNORECASE)
_SITUACAO = re.compile(r"situação.{0,20}posição", re.IGNORECASE)
_MOTIVO_DO_LANCE = re.compile(r"\b(?:por qu[eê]|porque)\b.*\b(?:lance|movimento|jogada|erro)\b", re.IGNORECASE)
_TEMA_DO_LANCE = re.compile(r"\b(?:tema|conceito|tática)\b.*\b(?:envolvid[oa]|desse lance|deste lance)\b", re.IGNORECASE)


class Estado(TypedDict, total=False):
    fen: str
    lance_jogado: str
    melhor_lance: str
    linha_motor: list[str]
    tema: str
    ficha: dict | None
    escolhas_fatuais: dict[str, list[str]]
    evidencias_taticas: list[dict]
    justificativa: str
    respostas_fatuais_chat: list[str]
    pergunta: str
    historico: list[dict]
    lance_selecionado: dict
    treino: dict
    mensagens: list
    evidencias: set[str]
    rodadas: int
    tentativas: int
    texto: str
    erros: list[str]
    pronto: bool
    validada: bool
    fallback_chat: bool
    bloqueio_mcp: str


def _prompt(nome: str) -> str:
    return (Path(__file__).resolve().parent / "prompts" / f"{nome}.md").read_text(encoding="utf-8")


def _modelo():
    from dotenv import load_dotenv
    from agent.llm import configurar_modelo

    load_dotenv(RAIZ / ".env")
    return configurar_modelo(float(os.getenv("LLM_TEMPERATURA") or 0))[2]


async def _invocar(modelo, mensagens: list, *, campos: tuple[str, ...] = (),
                   escolhas: dict[str, list[str]] | None = None) -> AIMessage:
    from agent.llm import formato_json, timeout_llm

    opcoes = formato_json(campos, escolhas) if campos else {}
    resposta = await asyncio.wait_for(modelo.ainvoke(mensagens, **opcoes), timeout=timeout_llm() + 5)
    if not isinstance(resposta, AIMessage):
        raise ValueError("O modelo não retornou uma mensagem.")
    uso = resposta.usage_metadata or {}
    if all(type(uso.get(campo)) is int for campo in ("input_tokens", "output_tokens")):
        LOGGER.info("LLM tokens_entrada=%d tokens_saida=%d", uso["input_tokens"], uso["output_tokens"])
    return resposta


def _contexto(dados: dict) -> HumanMessage:
    return HumanMessage(content=json.dumps(dados, ensure_ascii=False, separators=(",", ":")))


def _fatos_do_lance(antes: dict, depois: dict, origem: str, destino: str) -> tuple[dict, dict]:
    """Resume as descrições MCP para o modelo comparar somente fatos pertinentes."""
    def nome(peca: dict) -> str:
        lado = "brancas" if peca["cor"] == "white" else "pretas"
        tipo = "peão" if peca["tipo"] == "peao" else peca["tipo"]
        return f"{tipo} das {lado}"

    campos = ("lado_a_jogar", "em_xeque", "xeque_mate", "afogamento")
    anterior, posterior = ({k: dados[k] for k in campos if k in dados} for dados in (antes, depois))
    for dados, outro, resumido, casa in ((antes, depois, anterior, origem), (depois, antes, posterior, destino)):
        pecas = {p["casa"]: nome(p) for p in dados.get("pecas", [])}
        resumido["peca_movida"] = pecas.get(casa)
        ataque = next((p for p in dados.get("pecas_atacadas", []) if p["casa"] == casa), None)
        if ataque:
            resumido["peca_movida_defendida"] = bool(ataque["defensores"])
        resumido["quantidade_de_xeques_legais"] = len(dados.get("xeques_possiveis", []))
        for campo in ("pecas_atacadas", "pecas_cravadas"):
            resumido[campo] = [
                {"alvo": nome(peca), "atacantes": [pecas[c] for c in peca.get("atacantes", []) if c in pecas],
                 "defensores": [pecas[c] for c in peca.get("defensores", []) if c in pecas]}
                for peca in dados.get(campo, []) if peca not in outro.get(campo, [])
            ]
    if antes.get("material") != depois.get("material"):
        anterior["material"], posterior["material"] = antes.get("material"), depois.get("material")
    return anterior, posterior


def _escolhas_fatuais(fatos: dict, motivo: str | None) -> dict[str, list[str]]:
    depois = fatos["depois"]
    peca = fatos["antes"]["peca_movida"]
    artigo = "uma" if (peca or "").startswith(("torre", "dama")) else "um"
    aconteceu = f"O lance da partida deslocou {artigo} {peca}." if peca else "O lance da partida mudou a posição."
    if motivo:
        motivos = [motivo]
    elif "peca_movida_defendida" in depois:
        defesa = "tem defesa" if depois["peca_movida_defendida"] else "ficou sem defesa"
        motivos = [f"Na posição resultante, a peça movida está sob ataque e {defesa}."]
    elif depois["quantidade_de_xeques_legais"]:
        motivos = ["Na posição resultante, o lado a jogar dispõe de pelo menos um xeque legal."]
    else:
        motivos = ["A variante analisada não confirma um motivo tático específico para o lance."]
    return {"aconteceu": [aconteceu], "motivo": motivos}


def _licoes_da_ficha(ficha: dict | None) -> list[str]:
    if not ficha:
        return []
    secoes = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", ficha["texto"], flags=re.M | re.S))
    frases = []
    for secao in ("Como evitar", "Como reconhecer"):
        texto = secoes.get(secao, "").strip()
        if texto:
            frases.append(re.split(r"(?<=[.!?])\s+|\n", texto, maxsplit=1)[0])
    return frases


def _texto_conceitual(texto: str) -> str:
    return re.split(r"^## (?:Exemplo|Referências)\b", texto, 1, flags=re.MULTILINE)[0].strip()


def _casa_por_extenso(casa: str) -> str:
    linhas = ("um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito")
    return f"coluna {casa[0]}, linha {linhas[int(casa[1]) - 1]}"


def _resultado_para_chat(nome: str, dados) -> str:
    if nome == "descrever_posicao" and isinstance(dados, dict) and "pecas" in dados:
        dados = {**dados, "pecas": {p["casa"]: [p["tipo"], p["cor"]] for p in dados["pecas"]}}
        conteudo = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
        return re.sub(r'"([a-h][1-8])"', lambda m: json.dumps(_casa_por_extenso(m[1]), ensure_ascii=False), conteudo)
    if nome == "buscar_conceitos" and isinstance(dados, list):
        dados = [{**ficha, "texto": _texto_conceitual(ficha["texto"])} for ficha in dados if ficha.get("texto")]
    return json.dumps(dados, ensure_ascii=False, separators=(",", ":"))


def _respostas_da_descricao(dados: dict, pergunta: str) -> list[str]:
    nomes_lados = {"white": "brancas", "black": "pretas"}
    lado = nomes_lados[dados["lado_a_jogar"]]
    material = dados["material"]
    jogam = f"É a vez das {lado}."
    def quantidade(n: int, peca: str) -> str:
        return f"{n} {peca if n == 1 else peca + 's'}"

    pesadas = []
    for cor, nome in nomes_lados.items():
        damas, torres = (quantidade(material[cor][tipo], tipo) for tipo in ("dama", "torre"))
        pesadas.append(f"{damas} e {torres} das {nome}")
    resumo = f"{jogam} As peças pesadas são {' e '.join(pesadas)}."
    respostas = [resumo, jogam]
    pecas = {p["casa"]: p for p in dados["pecas"]}

    def identificar(peca: dict) -> str:
        tipo = "peão" if peca["tipo"] == "peao" else peca["tipo"]
        return f"{tipo} das {nomes_lados[peca['cor']]} na {_casa_por_extenso(peca['casa'])}"

    atacadas = dados["pecas_atacadas"]
    ameaca = _AMEACA.search(pergunta)
    if ameaca:
        respostas = []
        if casa := re.search(r"\b[a-h][1-8]\b", pergunta.casefold()):
            alvo = casa.group()
            atacadas = [p for p in atacadas if p["casa"] == alvo]
            if not atacadas:
                if alvo in pecas:
                    return [f"A peça identificada como {identificar(pecas[alvo])} está fora de ataque nesta posição."]
                return [f"A {_casa_por_extenso(alvo)} está vazia nesta posição."]
    if _SITUACAO.search(pergunta) and not ameaca:
        if dados["xeque_mate"]:
            return [f"As {lado} estão em xeque-mate."]
        if dados["afogamento"]:
            return [f"As {lado} estão afogadas e a partida está empatada."]
        return [f"{jogam} O rei está em xeque." if dados["em_xeque"] else resumo]
    for alvo in atacadas:
        quem = " e ".join(identificar(pecas[casa]) for casa in alvo["atacantes"])
        defesa = "tem defesa" if alvo["defensores"] else "está sem defesa"
        respostas.append(f"Na posição atual, {identificar(alvo)} está sob ataque de {quem} e {defesa}.")
    if not atacadas:
        respostas.append("A descrição do tabuleiro não registra peças sob ataque.")
    return respostas


def _explicacao_resultado(estado: Estado, ferramentas: Ferramentas) -> dict:
    tema = estado.get("tema", "outro")
    ficha = (estado.get("ficha") or {}) if estado.get("pronto") else {}
    return {
        "tema": tema, "tema_label": TEMAS[tema], "texto": estado.get("texto", _SEM_RESPOSTA),
        "ficha": {campo: ficha[campo] for campo in ("id", "titulo", "arquivo")} if ficha else None,
        "ferramentas_usadas": list(dict.fromkeys(item["nome"] for item in ferramentas.usadas)),
        "tentativas": estado.get("tentativas", 0), "validada": estado.get("validada", False),
        "fallback": bool(estado.get("validada") and not estado.get("pronto")),
    }


def construir_grafo_explicacao(modelo=None, ferramentas: Ferramentas | None = None, *, exigir_mcp: bool = False):
    """Compila o fluxo. O backend pode usar explicar_erro_async para gerenciar a sessão."""
    ferramentas = ferramentas if ferramentas is not None else Ferramentas([])

    async def preparar(estado: Estado) -> dict:
        fen, jogado = estado["fen"], estado["lance_jogado"]
        raiz = ler_fen(fen)
        movimento = raiz.parse_san(jogado)
        tabuleiro = raiz.copy(stack=False)
        tabuleiro.push(movimento)
        if modelo is None:
            return {"pronto": False}
        try:
            antes = await ferramentas.chamar("descrever_posicao", fen=fen)
            depois = await ferramentas.chamar("descrever_posicao", fen=tabuleiro.fen())
            if not all(isinstance(fatos, dict) and fatos and "erro" not in fatos for fatos in (antes, depois)):
                raise ValueError("Descrição da posição sem fatos utilizáveis.")
        except (RuntimeError, ValueError):
            return {"pronto": False, **({"bloqueio_mcp": "descrever_posicao"} if exigir_mcp else {})}
        antes, depois = _fatos_do_lance(antes, depois, movimento.uci()[:2], movimento.uci()[2:4])
        fatos = {"antes": antes, "depois": depois}
        evidencias = []
        if "analisar_posicao" in ferramentas.disponiveis:
            try:
                analise = await ferramentas.chamar("analisar_posicao", fen=tabuleiro.fen(), profundidade=16, multipv=1)
                evidencias = candidatos_taticos(tabuleiro, analise)
            except (RuntimeError, KeyError, TypeError):
                LOGGER.info("Não foi possível conferir a variante após o lance.")
        principal = evidencias[0] if evidencias else None
        tema = principal.tema if principal else "outro"
        escolhas = _escolhas_fatuais(fatos, principal.frase if principal else None)
        ficha = None
        try:
            trechos = await ferramentas.chamar("buscar_conceitos", pergunta=TEMAS[tema], tema=tema, k=4)
            ficha = next((t for t in trechos if t.get("id") == tema and all(
                isinstance(t.get(c), str) and t[c] for c in ("titulo", "arquivo", "texto")
            )), None)
        except (RuntimeError, TypeError, AttributeError):
            LOGGER.info("Ficha conceitual indisponível para o tema %s", tema)
        if ficha:
            conceitual = _texto_conceitual(ficha["texto"])
            ficha = {**ficha, "texto": conceitual} if conceitual else None
        if exigir_mcp and ficha is None:
            return {"pronto": False, "tema": tema, "bloqueio_mcp": "buscar_conceitos"}
        if licoes := _licoes_da_ficha(ficha):
            escolhas["licao"] = licoes
        justificativa = justificar_alternativa(raiz, estado["melhor_lance"], estado["linha_motor"])
        return {"pronto": True, "tema": tema, "ficha": ficha,
                "escolhas_fatuais": escolhas, "evidencias_taticas": [asdict(e) for e in evidencias],
                "justificativa": justificativa}

    async def gerar(estado: Estado) -> dict:
        instrucoes = "\n".join(_prompt(nome) for nome in ("sistema", "tema", "explicacao"))
        if estado.get("erros"):
            instrucoes += "\n" + _prompt("correcao")
        escolhas = estado["escolhas_fatuais"]
        dados = {"tema": TEMAS[estado["tema"]], "ficha": estado["ficha"],
                 "frases_permitidas": escolhas, "erros": estado.get("erros", [])}
        if treino := estado.get("treino"):
            dados["treino"] = treino
        try:
            resposta = await _invocar(modelo, [
                SystemMessage(content=instrucoes),
                _contexto(dados),
            ], campos=("aconteceu", "motivo", "licao"), escolhas=escolhas)
            texto = resposta.text.strip()
        except Exception as erro:
            LOGGER.warning("Geração da explicação falhou (%s)", type(erro).__name__)
            texto = ""
        return {"texto": texto, "tentativas": estado.get("tentativas", 0) + 1}

    async def validar(estado: Estado) -> dict:
        try:
            bruto = estado["texto"]
            if bruto.startswith(("```json\n", "```\n")) and bruto.endswith("```"):
                bruto = bruto.split("\n", 1)[1][:-3].strip()
            partes = json.loads(bruto)
            if any(partes[campo] not in opcoes for campo, opcoes in estado.get("escolhas_fatuais", {}).items()):
                return {"validada": False, "erros": ["Use as frases permitidas para descrever os fatos."]}
            frases = [partes[chave].strip() for chave in ("aconteceu", "motivo", "licao")]
            if any(not frase or re.search(r"[.!?]\s+\S|[\r\n]", frase) for frase in frases):
                raise ValueError("É esperada uma frase por campo.")
            texto = " ".join(frase.rstrip(".!?") + "." for frase in frases)
        except (ValueError, KeyError, TypeError, AttributeError):
            return {"validada": False, "erros": ["Preencha os três campos com uma frase cada."]}
        if _AVALIACAO_NUMERICA.search(texto):
            return {"validada": False, "erros": ["Omita avaliações numéricas da redação."]}
        resultado = await validar_resposta_async(
            texto, estado["fen"], estado["linha_motor"], validar_lances=ferramentas.validar,
        )
        alternativa = f"O Stockfish indicou `{estado['melhor_lance']}` como alternativa{estado.get('justificativa', '')}."
        if resultado["valida"]:
            resultado = await validar_resposta_async(
                alternativa, estado["fen"], estado["linha_motor"], validar_lances=ferramentas.validar,
            )
        if not resultado["valida"]:
            if exigir_mcp and resultado.get("ferramenta_indisponivel"):
                return {"validada": False, "erros": resultado["erros"], "bloqueio_mcp": "validar_lances"}
            return {"validada": False, "erros": resultado["erros"]}
        return {"validada": True, "texto": f"{texto} {alternativa}", "erros": []}

    async def fallback(estado: Estado) -> dict:
        jogado, melhor, linha = (estado[chave] for chave in ("lance_jogado", "melhor_lance", "linha_motor"))
        texto = explicacao_padrao(jogado, melhor, linha)
        melhor_confirmado = await validar_resposta_async(
            melhor, estado["fen"], linha, validar_lances=ferramentas.validar,
        )
        if not melhor_confirmado["valida"]:
            return {"texto": _SEM_RESPOSTA, "validada": False, "pronto": False}
        resultado = await validar_resposta_async(
            texto, estado["fen"], linha, validar_lances=ferramentas.validar, outras_linhas=([jogado],),
        )
        return {"texto": texto if resultado["valida"] else _SEM_RESPOSTA,
                "validada": resultado["valida"], "pronto": False, "tema": "outro"}

    async def apos_preparar(estado: Estado) -> str:
        if estado.get("bloqueio_mcp"):
            return END
        return "gerar" if estado["pronto"] else "fallback"

    async def apos_validar(estado: Estado) -> str:
        if estado["validada"] or estado.get("bloqueio_mcp"):
            return END
        return "gerar" if estado["tentativas"] < MAX_TENTATIVAS else "fallback"

    grafo = StateGraph(Estado)
    for no in (preparar, gerar, validar, fallback):
        grafo.add_node(no.__name__, no)
    grafo.add_edge(START, "preparar")
    grafo.add_conditional_edges("preparar", apos_preparar, [END, "gerar", "fallback"])
    grafo.add_edge("gerar", "validar")
    grafo.add_conditional_edges("validar", apos_validar, [END, "gerar", "fallback"])
    grafo.add_edge("fallback", END)
    return grafo.compile()


def construir_agente_chat(modelo=None, ferramentas: Ferramentas | None = None):
    """Compila o ciclo de ferramentas, redação, validação e correção."""
    ferramentas = ferramentas if ferramentas is not None else Ferramentas([])
    permitidas = [f for nome, f in ferramentas.disponiveis.items() if nome in _CHAT_TOOLS]
    modelo_chat = modelo.bind_tools(permitidas) if modelo is not None and permitidas else modelo

    async def iniciar(estado: Estado) -> dict:
        historico = [item for item in (estado.get("historico") or [])[-12:]
                     if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
                     and isinstance(item.get("content"), str)]
        dados = {"fen": estado["fen"], "pergunta": estado["pergunta"]}
        if historico:
            dados["historico"] = historico
        if contexto := estado.get("lance_selecionado"):
            dados["lance_selecionado"] = {k: v for k, v in contexto.items() if k != "fen_apos_lance"}
        if treino := estado.get("treino"):
            dados["treino"] = treino
        mensagens = [SystemMessage(content=_prompt("sistema") + "\n" + _prompt("chat")), _contexto(dados)]
        return {"mensagens": mensagens, "rodadas": 0, "tentativas": 0, "evidencias": set()}

    def consulta_explicita(pergunta: str) -> str | None:
        pergunta = pergunta.casefold()
        if re.search(r"buscar_conceitos|\bconceito\b|base de conhecimento", pergunta):
            return "buscar_conceitos"
        if re.search(r"analisar_posicao|stockfish|melhor (?:lance|movimento|jogada)|que lance devo", pergunta):
            return "analisar_posicao"
        if (_AMEACA.search(pergunta) or _SITUACAO.search(pergunta)
                or re.search(r"descrever_posicao|descriç|descrev|(?:quem|cor).{0,20}vez", pergunta)):
            return "descrever_posicao"
        return None

    async def consultar_modelo(estado: Estado) -> dict:
        try:
            pergunta = estado["pergunta"]
            contexto = estado.get("lance_selecionado")
            nome = consulta_explicita(pergunta) if estado["rodadas"] == 0 else None
            consulta = None
            if nome in ferramentas.disponiveis:
                argumentos = {"pergunta": pergunta} if nome == "buscar_conceitos" else {"fen": estado["fen"]}
                consulta = AIMessage(content="", tool_calls=[{"name": nome, "args": argumentos, "id": "consulta-atual"}])
            if (modelo is not None and contexto and estado["rodadas"] == 0 and "analisar_posicao" in ferramentas.disponiveis
                    and (_MOTIVO_DO_LANCE.search(pergunta) or _TEMA_DO_LANCE.search(pergunta))):
                consulta = AIMessage(content="", tool_calls=[{
                    "name": "analisar_posicao", "args": {"fen": contexto["fen_apos_lance"]}, "id": "consequencia-do-lance",
                }])
                return {"mensagens": [*estado["mensagens"], consulta], "texto": ""}
            if modelo is not None and consulta and os.getenv("LLM_JSON_MODE") == "1":
                return {"mensagens": [*estado["mensagens"], consulta], "texto": ""}
            opcoes = estado.get("respostas_fatuais_chat") or []
            linha = estado.get("linha_motor")
            conceito_consultado = "buscar_conceitos" in estado["evidencias"]
            if linha and not conceito_consultado and os.getenv("LLM_JSON_MODE") == "1" and consulta_explicita(pergunta) == "analisar_posicao":
                opcoes = [f"O Stockfish indica `{linha[0]}` como melhor lance."]
            elif linha or conceito_consultado:
                opcoes = []
            if opcoes:
                resposta = await _invocar(modelo, [
                    SystemMessage(content="Selecione a frase que responde mais diretamente à pergunta. Copie a frase integralmente."),
                    _contexto({"pergunta": estado["pergunta"], "respostas_verificadas": opcoes}),
                ], campos=("resposta",), escolhas={"resposta": opcoes})
                texto = json.loads(resposta.text)["resposta"]
                if texto not in opcoes:
                    raise ValueError("Resposta fora das frases verificadas.")
                return {"mensagens": [*estado["mensagens"], AIMessage(content=texto)], "texto": texto}
            resposta = await _invocar(modelo_chat, estado["mensagens"])
            if not resposta.tool_calls and resposta.text and consulta:
                resposta = consulta
            return {"mensagens": [*estado["mensagens"], resposta], "texto": resposta.text}
        except Exception as erro:
            LOGGER.warning("Modelo do chat indisponível (%s)", type(erro).__name__)
            return {"mensagens": [*estado["mensagens"], AIMessage(content="")],
                    "texto": "", "tentativas": MAX_TENTATIVAS}

    async def executar_ferramentas(estado: Estado) -> dict:
        mensagens = list(estado["mensagens"])
        chamadas = mensagens[-1].tool_calls
        linha = estado.get("linha_motor", [])
        evidencias = set(estado["evidencias"])
        respostas_fatuais = estado.get("respostas_fatuais_chat", [])
        for chamada in chamadas:
            nome, argumentos = chamada["name"], dict(chamada["args"])
            try:
                if nome not in _CHAT_TOOLS or len(chamadas) > len(_CHAT_TOOLS):
                    raise ValueError("Chamada não permitida.")
                if (estado["rodadas"] == 0 and chamada["id"] == "consequencia-do-lance"
                        and (contexto := estado.get("lance_selecionado"))
                        and (_MOTIVO_DO_LANCE.search(estado["pergunta"]) or _TEMA_DO_LANCE.search(estado["pergunta"]))):
                    dados = await ferramentas.chamar("analisar_posicao", fen=contexto["fen_apos_lance"], profundidade=16, multipv=1)
                    tabuleiro = ler_fen(contexto["fen_apos_lance"])
                    motivos = candidatos_taticos(tabuleiro, dados)
                    motivo = next((item for item in motivos if item.tema == contexto.get("tema")), motivos[0] if motivos else None)
                    if tabuleiro.is_checkmate():
                        respostas_fatuais = ["O lance encerrou a partida com xeque-mate."]
                    elif motivo:
                        respostas_fatuais = [f"O tema identificado é {TEMAS[motivo.tema].lower()}. {motivo.frase}"]
                    else:
                        respostas_fatuais = ["A variante analisada não confirma um tema tático específico para o lance."]
                    evidencias.add(nome)
                    mensagens.append(ToolMessage(content=json.dumps(respostas_fatuais, ensure_ascii=False),
                                                 tool_call_id=chamada["id"], name=nome))
                    continue
                if nome != "buscar_conceitos":
                    argumentos["fen"] = estado["fen"]
                if nome == "analisar_posicao":
                    argumentos = {"fen": estado["fen"], "profundidade": 18, "multipv": 3}
                elif nome == "buscar_conceitos":
                    argumentos["k"] = 4
                dados = await ferramentas.chamar(nome, **argumentos)
                if nome == "analisar_posicao":
                    if not isinstance(dados, dict):
                        raise ValueError("Saída do motor inválida.")
                    variante = dados.get("linha_principal", [])
                    if isinstance(variante, list) and all(isinstance(lance, str) for lance in variante):
                        linha = variante
                if dados:
                    evidencias.add(nome)
                if (nome == "descrever_posicao" and os.getenv("LLM_JSON_MODE") == "1"
                        and isinstance(dados, dict) and "pecas" in dados):
                    respostas_fatuais = _respostas_da_descricao(dados, estado["pergunta"])
            except (RuntimeError, ValueError):
                dados = {"erro": "Ferramenta indisponível ou consulta inválida."}
            mensagens.append(ToolMessage(content=_resultado_para_chat(nome, dados),
                                         tool_call_id=chamada["id"], name=nome))
        return {"mensagens": mensagens, "linha_motor": linha, "rodadas": estado["rodadas"] + 1,
                "evidencias": evidencias, "respostas_fatuais_chat": respostas_fatuais}

    async def validar(estado: Estado) -> dict:
        texto = estado["texto"].strip()
        erros = []
        if not estado["evidencias"]:
            erros.append("Nenhuma ferramenta retornou evidência para a resposta.")
        if _AVALIACAO_NUMERICA.search(texto):
            erros.append("Omita avaliações numéricas da redação.")
        if _RECOMENDACAO.search(texto) and not extrair_lances(texto):
            erros.append("Uma recomendação concreta precisa citar em SAN o lance confirmado pelo Stockfish.")
        if not erros:
            resultado = await validar_resposta_async(
                texto, estado["fen"], estado.get("linha_motor"), validar_lances=ferramentas.validar,
            )
            erros.extend(resultado["erros"])
        atualizacao = {"validada": not erros, "tentativas": estado["tentativas"] + 1}
        if erros:
            LOGGER.info("Rascunho de chat rejeitado pelo validador (%d restrições)", len(erros))
            correcao = _prompt("correcao") + "\n" + " ".join(erros)
            atualizacao["mensagens"] = [*estado["mensagens"], HumanMessage(content=correcao)]
        return atualizacao

    async def fallback(estado: Estado) -> dict:
        linha = estado.get("linha_motor")
        if linha:
            texto = f"O Stockfish indicou a variante `{' '.join(linha)}`."
            resultado = await validar_resposta_async(
                texto, estado["fen"], linha, validar_lances=ferramentas.validar,
            )
            if resultado["valida"]:
                return {"texto": texto, "validada": True, "fallback_chat": True}
        return {"texto": _SEM_RESPOSTA, "validada": False}

    async def apos_modelo(estado: Estado) -> str:
        if estado["tentativas"] >= MAX_TENTATIVAS:
            return "fallback"
        if estado["mensagens"][-1].tool_calls:
            return "executar_ferramentas" if estado["rodadas"] < MAX_RODADAS_MCP else "fallback"
        return "validar"

    async def apos_validar(estado: Estado) -> str:
        if estado["validada"]:
            return END
        return "consultar_modelo" if estado["tentativas"] < MAX_TENTATIVAS else "fallback"

    grafo = StateGraph(Estado)
    for no in (iniciar, consultar_modelo, executar_ferramentas, validar, fallback):
        grafo.add_node(no.__name__, no)
    grafo.add_edge(START, "iniciar")
    grafo.add_edge("iniciar", "consultar_modelo")
    grafo.add_conditional_edges("consultar_modelo", apos_modelo, ["executar_ferramentas", "validar", "fallback"])
    grafo.add_edge("executar_ferramentas", "consultar_modelo")
    grafo.add_conditional_edges("validar", apos_validar, [END, "consultar_modelo", "fallback"])
    grafo.add_edge("fallback", END)
    return grafo.compile()


async def explicar_erro_async(fen: str, lance_jogado: str, melhor_lance: str, linha_motor: list[str],
                              *, treino: dict | None = None) -> dict:
    ferramentas = Ferramentas([])
    try:
        tabuleiro = ler_fen(fen)
    except ValueError:
        return _explicacao_resultado({"texto": "A posição FEN é inválida."}, ferramentas)
    try:
        jogado = tabuleiro.parse_san(lance_jogado)
        melhor = tabuleiro.parse_san(melhor_lance)
        if jogado not in tabuleiro.legal_moves or melhor not in tabuleiro.legal_moves:
            raise ValueError("Lances de entrada inválidos.")
        jogado_san, melhor_san = tabuleiro.san(jogado), tabuleiro.san(melhor)
        if not linha_motor or tabuleiro.parse_san(linha_motor[0]) != melhor:
            raise ValueError("Melhor lance diverge da variante.")
        async with sessao_mcp() as disponiveis:
            ferramentas = Ferramentas(disponiveis)
            resultado = await construir_grafo_explicacao(_modelo(), ferramentas).ainvoke({
                "fen": fen, "lance_jogado": jogado_san, "melhor_lance": melhor_san, "linha_motor": linha_motor,
                **({"treino": treino} if treino else {}),
            })
        return _explicacao_resultado(resultado, ferramentas)
    except Exception as erro:
        LOGGER.warning("Explicação indisponível (%s)", type(erro).__name__)
        return _explicacao_resultado({}, ferramentas)


async def responder_chat_async(fen: str, pergunta: str, historico: list[dict] | None = None,
                              *, lance_selecionado: dict | None = None, treino: dict | None = None) -> dict:
    ferramentas = Ferramentas([])
    try:
        ler_fen(fen)
    except ValueError:
        return {"resposta": "A posição FEN é inválida.", "ferramentas_usadas": [], "validada": False}
    if not pergunta.strip():
        return {"resposta": "Escreva uma pergunta sobre a posição.", "ferramentas_usadas": [], "validada": False}
    resultado: Estado = {}
    try:
        async with sessao_mcp() as disponiveis:
            ferramentas = Ferramentas(disponiveis)
            resultado = await construir_agente_chat(_modelo(), ferramentas).ainvoke({
                "fen": fen, "pergunta": pergunta, "historico": historico or [], "lance_selecionado": lance_selecionado,
                **({"treino": treino} if treino else {}),
            })
    except Exception as erro:
        LOGGER.warning("Chat indisponível (%s)", type(erro).__name__)
    return {"resposta": resultado.get("texto", _SEM_RESPOSTA), "ferramentas_usadas": ferramentas.usadas,
            "validada": resultado.get("validada", False), "fallback": resultado.get("fallback_chat", False)}


def explicar_erro(fen: str, lance_jogado: str, melhor_lance: str, linha_motor: list[str]) -> dict:
    return asyncio.run(explicar_erro_async(fen, lance_jogado, melhor_lance, linha_motor))


def responder_chat(fen: str, pergunta: str, historico: list[dict] | None = None) -> dict:
    return asyncio.run(responder_chat_async(fen, pergunta, historico))
