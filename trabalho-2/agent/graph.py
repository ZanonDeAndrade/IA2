"""Fluxos LangGraph de explicação e chat, com validação antes da publicação."""

import asyncio
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


class Estado(TypedDict, total=False):
    fen: str
    lance_jogado: str
    melhor_lance: str
    linha_motor: list[str]
    tema: str
    ficha: dict | None
    fatos: dict
    escolhas_fatuais: dict[str, list[str]]
    respostas_fatuais_chat: list[str]
    pergunta: str
    historico: list[dict]
    mensagens: list
    evidencias: set[str]
    rodadas: int
    tentativas: int
    texto: str
    erros: list[str]
    pronto: bool
    validada: bool
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
        return f"{peca['tipo']} das {lado}"

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


def _garfo_com_xeque(tabuleiro: chess.Board, linha: list[str]) -> dict[str, str] | None:
    """Confirma que a peça que deu xeque captura o outro alvo na mesma variante."""
    nomes = {chess.PAWN: "peão", chess.QUEEN: "dama", chess.ROOK: "torre", chess.BISHOP: "bispo", chess.KNIGHT: "cavalo"}
    copia = tabuleiro.copy(stack=False)
    for indice, san in enumerate(linha[:4]):
        try:
            lance = copia.parse_san(san)
        except ValueError:
            return None
        copia.push(lance)
        if copia.turn == tabuleiro.turn or not copia.is_check() or copia.king(copia.turn) not in copia.attacks(lance.to_square):
            continue
        if indice + 2 >= len(linha):
            break
        resposta = copia.copy(stack=False)
        try:
            defesa = resposta.push_san(linha[indice + 1])
            captura = resposta.parse_san(linha[indice + 2])
        except ValueError:
            return None
        alvo = copia.piece_at(captura.to_square)
        atacante = copia.piece_at(lance.to_square)
        if (alvo and alvo.color == copia.turn and alvo.piece_type not in {chess.PAWN, chess.KING}
                and atacante and atacante.piece_type in nomes and defesa.from_square != captura.to_square
                and captura.from_square == lance.to_square and resposta.is_capture(captura)
                and captura.to_square in copia.attacks(lance.to_square)):
            cor = "brancas" if atacante.color == chess.WHITE else "pretas"
            return {"atacante": f"{nomes[atacante.piece_type]} das {cor}", "alvo": nomes[alvo.piece_type]}
    return None


def _escolhas_fatuais(fatos: dict) -> dict[str, list[str]]:
    depois = fatos["depois"]
    peca = depois["peca_movida"]
    artigo = "uma" if (peca or "").startswith(("torre", "dama")) else "um"
    aconteceu = f"O lance da partida deslocou {artigo} {peca}." if peca else "O lance da partida mudou a posição."
    motivos = []
    if mate := fatos.get("mate_em"):
        unidade = "lance" if mate == 1 else "lances"
        motivos.append(f"Na posição resultante, o Stockfish indicou mate em {mate} {unidade} para o lado a jogar.")
    elif garfo := fatos.get("garfo_com_xeque"):
        alvo = garfo["alvo"]
        artigo = "uma" if alvo in {"torre", "dama"} else "um"
        artigo_atacante = "uma" if garfo["atacante"].startswith(("torre", "dama")) else "um"
        motivos.append(f"Na variante analisada, {artigo_atacante} {garfo['atacante']} dá xeque e depois captura {artigo} {alvo}.")
    else:
        if "peca_movida_defendida" in depois:
            defesa = "tem defesa" if depois["peca_movida_defendida"] else "ficou sem defesa"
            motivos.append(f"Na posição resultante, a peça movida está sob ataque e {defesa}.")
        if depois["quantidade_de_xeques_legais"]:
            motivos.append("Na posição resultante, o lado a jogar dispõe de pelo menos um xeque legal.")
    return {"aconteceu": [aconteceu],
            "motivo": motivos or ["Compare as ameaças da posição resultante com a alternativa analisada."]}


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


def _respostas_da_descricao(dados: dict) -> list[str]:
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
    respostas = [f"{jogam} As peças pesadas são {' e '.join(pesadas)}.", jogam]
    pecas = {p["casa"]: p for p in dados["pecas"]}

    def identificar(peca: dict) -> str:
        tipo = "peão" if peca["tipo"] == "peao" else peca["tipo"]
        return f"{tipo} das {nomes_lados[peca['cor']]} na {_casa_por_extenso(peca['casa'])}"

    for alvo in dados["pecas_atacadas"]:
        quem = " e ".join(identificar(pecas[casa]) for casa in alvo["atacantes"])
        defesa = "tem defesa" if alvo["defensores"] else "está sem defesa"
        respostas.append(f"Na posição atual, {identificar(alvo)} está sob ataque de {quem} e {defesa}.")
    if not dados["pecas_atacadas"]:
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
        tabuleiro = ler_fen(fen)
        movimento = tabuleiro.parse_san(jogado)
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
        escolhas = {}
        selecao = {}
        instrucao_tema = _prompt("sistema") + "\n" + _prompt("tema")
        temas_permitidos = TEMAS
        if os.getenv("LLM_JSON_MODE") == "1":
            if "analisar_posicao" in ferramentas.disponiveis:
                try:
                    analise = await ferramentas.chamar("analisar_posicao", fen=tabuleiro.fen(), profundidade=16, multipv=1)
                    avaliacao = analise.get("avaliacao", {})
                    if avaliacao.get("tipo") == "mate" and avaliacao["valor"] > 0:
                        fatos["mate_em"] = avaliacao["valor"]
                    elif garfo := _garfo_com_xeque(tabuleiro, analise["linha_principal"]):
                        fatos["garfo_com_xeque"] = garfo
                except (RuntimeError, KeyError, TypeError):
                    LOGGER.info("Não foi possível conferir a variante após o lance.")
            escolhas = _escolhas_fatuais(fatos)
            if fatos.get("mate_em"):
                temas_permitidos = {"mate": TEMAS["mate"]}
            elif fatos.get("garfo_com_xeque"):
                temas_permitidos = {"garfo": TEMAS["garfo"]}
            else:
                temas_permitidos = {"outro": TEMAS["outro"], **{
                    tema: titulo for tema, titulo in TEMAS.items() if tema not in {"garfo", "mate", "outro"}
                }}
            selecao = {"tema": list(temas_permitidos)}
            instrucao_tema += "\nRetorne um objeto JSON com a chave tema."
        else:
            instrucao_tema += "\nDevolva apenas o identificador, sem aspas, pontuação ou Markdown."
        try:
            resposta = await _invocar(modelo, [
                SystemMessage(content=instrucao_tema),
                _contexto({"temas_permitidos": temas_permitidos, "fatos": fatos}),
            ], campos=("tema",) if selecao else (), escolhas=selecao)
            tema = json.loads(resposta.text)["tema"] if selecao else resposta.text.strip().lower()
            if not isinstance(tema, str) or tema not in temas_permitidos:
                tema = "outro"
        except Exception as erro:
            LOGGER.warning("Preparação da explicação falhou (%s)", type(erro).__name__)
            return {"pronto": False}
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
        return {"pronto": True, "tema": tema, "ficha": ficha, "fatos": fatos, "escolhas_fatuais": escolhas}

    async def gerar(estado: Estado) -> dict:
        instrucoes = _prompt("sistema") + "\n" + _prompt("explicacao")
        if estado.get("erros"):
            instrucoes += "\n" + _prompt("correcao")
        escolhas = estado.get("escolhas_fatuais") or {}
        if escolhas:
            instrucoes += "\nCopie frases permitidas para aconteceu e motivo. Redija uma lição geral curta, sem afirmar outros fatos sobre esta posição."
            if estado["fatos"].get("garfo_com_xeque"):
                instrucoes += "\nNa lição, ensine o jogador a procurar xeques e ataques simultâneos do adversário antes de jogar."
        try:
            resposta = await _invocar(modelo, [
                SystemMessage(content=instrucoes),
                _contexto({"fatos": estado["fatos"], "tema": TEMAS[estado["tema"]],
                           "ficha": estado["ficha"], "erros": estado.get("erros", []),
                           **({"frases_permitidas": escolhas} if escolhas else {})}),
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
        alternativa = f"O Stockfish indicou `{estado['melhor_lance']}` como alternativa."
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
        mensagens = [SystemMessage(content=_prompt("sistema") + "\n" + _prompt("chat"))]
        for item in (estado.get("historico") or [])[-12:]:
            if not isinstance(item, dict):
                continue
            papel, texto = item.get("role"), item.get("content")
            if papel in ("user", "assistant") and isinstance(texto, str):
                tipo = HumanMessage if papel == "user" else AIMessage
                mensagens.append(tipo(content=texto))
        mensagens.append(_contexto({"fen": estado["fen"], "pergunta": estado["pergunta"]}))
        return {"mensagens": mensagens, "rodadas": 0, "tentativas": 0, "evidencias": set()}

    async def consultar_modelo(estado: Estado) -> dict:
        try:
            opcoes = estado.get("respostas_fatuais_chat") or []
            if opcoes and not estado.get("linha_motor") and "buscar_conceitos" not in estado["evidencias"]:
                resposta = await _invocar(modelo, [
                    SystemMessage(content="Selecione a frase que responde mais diretamente à pergunta. Copie a frase integralmente."),
                    _contexto({"pergunta": estado["pergunta"], "respostas_verificadas": opcoes}),
                ], campos=("resposta",), escolhas={"resposta": opcoes})
                texto = json.loads(resposta.text)["resposta"]
                if texto not in opcoes:
                    raise ValueError("Resposta fora das frases verificadas.")
                return {"mensagens": [*estado["mensagens"], AIMessage(content=texto)], "texto": texto}
            resposta = await _invocar(modelo_chat, estado["mensagens"])
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
                    respostas_fatuais = _respostas_da_descricao(dados)
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
                return {"texto": texto, "validada": True}
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


async def explicar_erro_async(fen: str, lance_jogado: str, melhor_lance: str, linha_motor: list[str]) -> dict:
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
            })
        return _explicacao_resultado(resultado, ferramentas)
    except Exception as erro:
        LOGGER.warning("Explicação indisponível (%s)", type(erro).__name__)
        return _explicacao_resultado({}, ferramentas)


async def responder_chat_async(fen: str, pergunta: str, historico: list[dict] | None = None) -> dict:
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
                "fen": fen, "pergunta": pergunta, "historico": historico or [],
            })
    except Exception as erro:
        LOGGER.warning("Chat indisponível (%s)", type(erro).__name__)
    return {"resposta": resultado.get("texto", _SEM_RESPOSTA), "ferramentas_usadas": ferramentas.usadas,
            "validada": resultado.get("validada", False)}


def explicar_erro(fen: str, lance_jogado: str, melhor_lance: str, linha_motor: list[str]) -> dict:
    return asyncio.run(explicar_erro_async(fen, lance_jogado, melhor_lance, linha_motor))


def responder_chat(fen: str, pergunta: str, historico: list[dict] | None = None) -> dict:
    return asyncio.run(responder_chat_async(fen, pergunta, historico))
