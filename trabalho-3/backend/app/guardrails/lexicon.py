"""Vocabulários e padrões dos guardrails (heurísticos e curados para o MVP).

Heurística tem falso positivo e falso negativo: por isso o projeto combina estes padrões com
isolamento de papéis (system x user x tool), allowlist de tools e verificação de saída.
"""

from __future__ import annotations

import base64
import re
import unicodedata


def fold(text: str) -> str:
    """minúsculas, sem acentos e com espaços colapsados (para comparação, nunca para exibição)."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def singular(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    return [singular(w) for w in re.findall(r"[a-z0-9]+", fold(text))]


def contains_term(text_words: list[str], term: str) -> bool:
    """Termo (uma ou mais palavras) presente como sequência de palavras inteiras."""
    t = words(term)
    n = len(t)
    return any(text_words[i : i + n] == t for i in range(len(text_words) - n + 1)) if n else False


# ---------------------------------------------------------------- domínio culinário

# Alimentos comuns (forma singular, sem acento). Usado para reconhecer pedidos culinários e,
# na saída, para detectar ingredientes citados que não estão na evidência.
_FOOD_WORDS = """
ovo queijo leite farinha fuba maisena polvilho acucar sal pimenta oleo azeite manteiga margarina banha
iogurte requeijao nata fermento bicarbonato chocolate cacau achocolatado cafe cha mel melado canela cravo
baunilha gengibre arroz feijao lentilha ervilha milho soja aveia trigo quinoa macarrao pao torrada
batata mandioca aipim inhame cenoura beterraba abobora abobrinha berinjela chuchu pepino tomate cebola
alho pimentao alface couve repolho espinafre brocolis rucula agriao salsinha cebolinha coentro manjericao
oregano alecrim tomilho louro hortela cogumelo palmito azeitona banana maca laranja limao abacaxi manga
morango uva mamao melancia melao maracuja coco abacate goiaba pera pessego ameixa caju acai castanha
amendoim noze amendoa carne frango peixe atum sardinha bacalhau salmao camarao porco linguica bacon
presunto salsicha calabresa mortadela peru costela file gelatina vinagre mostarda maionese ketchup
molho shoyu caldo agua vinho cerveja
"""

# Termos compostos ficam inteiros (nunca quebrar em "de", "da"...).
_FOOD_MULTI = {
    "farinha de trigo", "farinha de mandioca", "amido de milho", "acucar mascavo", "creme de leite",
    "leite condensado", "chocolate em po", "fermento biologico", "noz moscada", "grao de bico",
    "batata doce", "couve flor", "uva passa", "carne moida", "peito de frango", "extrato de tomate",
    "leite de coco", "queijo ralado", "massa de tomate",
}

FOODS: frozenset[str] = frozenset(_FOOD_WORDS.split()) | frozenset(_FOOD_MULTI)

DISHES: frozenset[str] = frozenset(
    """bolo torta pudim brigadeiro beijinho mousse sorvete doce sobremesa biscoito bolacha cookie
    panqueca crepe omelete omeleta tapioca cuscuz polenta pure risoto lasanha pizza sopa canja
    salada sanduiche lanche hamburguer farofa vinagrete moqueca feijoada estrogonofe strogonoff
    empada empadao coxinha pastel quiche sufle nhoque escondidinho mingau granola vitamina suco""".split()
) | {"arroz doce", "torta salgada", "pao de queijo"}

CULINARY_TERMS: frozenset[str] = frozenset(
    """receita cozinhar cozinha culinaria culinario ingrediente prato preparo preparar assar assado
    fritar frito cozido grelhar refogar refogado temperar tempero forno fogao panela frigideira airfryer
    almoco jantar sobremesa comida comer refeicao cardapio porcao rende recheio cobertura calda""".split()
) | {"modo de preparo", "cafe da manha"}


def has_culinary_signal(text: str) -> bool:
    w = words(text)
    return any(contains_term(w, t) for t in (FOODS | DISHES | CULINARY_TERMS))


# ---------------------------------------------------------------- fora do domínio

# Pedidos explícitos de outra natureza: bloqueiam mesmo se houver palavra culinária.
STRONG_OFF_DOMAIN = [
    re.compile(p)
    for p in (
        r"\b(escrev|gere|gera|cri|faz|faca|implement|program|codifiq)\w*\b.{0,40}\b(codigo|script|programa|funcao|"
        r"classe|algoritmo|api|sql|html|css|regex)\b",
        r"\b(codigo|script|programa)\b.{0,20}\b(em|na linguagem)\s+(python|java|javascript|c\+\+|c#|php|ruby|go|rust)",
        r"\b(python|javascript|typescript|java|sql|html|css|php)\b.{0,30}\b(codigo|script|funcao|programa|bug|erro)",
        r"\b(escrev|faz|faca|cri|gere)\w*\b.{0,30}\b(poema|poesia|redacao|musica|letra de musica|piada|conto|"
        r"historia|trabalho escolar|tcc|artigo)\b",
        r"\b(traduz|traduza|traducao)\b",
        r"\b(hack|invadir|invasao|senha de|phishing|malware|virus de computador|ddos)\w*",
    )
]

# Temas fora do escopo: só bloqueiam quando NÃO há sinal culinário na mensagem.
WEAK_OFF_DOMAIN = frozenset(
    """politica eleicao presidente governo partido futebol campeonato jogo placar time
    bolsa acao acoes investimento criptomoeda bitcoin dolar cotacao
    matematica equacao integral derivada calcule calcular
    previsao do tempo clima noticia noticias filme serie novela
    diagnostico remedio medicamento dose sintoma doenca tratamento
    programacao computador software celular capital pais historia geografia fisica quimica""".split()
)


def strong_off_domain(text: str) -> bool:
    f = fold(text)
    return any(p.search(f) for p in STRONG_OFF_DOMAIN)


def weak_off_domain(text: str) -> bool:
    w = words(text)
    return any(contains_term(w, t) for t in WEAK_OFF_DOMAIN)


# ---------------------------------------------------------------- prompt injection

_SECRET = r"(chave|token|senha|credenci\w*|api key|apikey|variave\w* de ambiente|\.env)"
_ASK = r"(mostre|revele|qual|quais|liste|imprima|me de|me passe|me diga)"

INJECTION_PATTERNS = [
    re.compile(p, re.MULTILINE)
    for p in (
        # pt-BR: ignorar/esquecer/não seguir instruções DO ASSISTENTE (anteriores, suas, do sistema...)
        # ("esqueci as instruções da minha avó" não deve disparar)
        r"\b(ignor|esquec|desconsider|despreze|anul|sobrescrev|nao sig|nao obedec|pare de seguir|deixe de seguir)"
        r"\w*\b.{0,30}\b(instruc|regra|diretriz|orientac|prompt|restric)\w*\b.{0,30}"
        r"\b(anterior\w*|acima|previa\w*|inicia\w*|do sistema|recebid\w*|que (te|lhe|voce|vc) (deram|passaram|"
        r"recebeu|foram dad\w*)|ate agora|de antes|antes)\b",
        r"\b(ignor|esquec|desconsider|despreze|anul|sobrescrev|nao sig|nao obedec)\w*\b.{0,15}"
        r"\b(suas|seus|tuas|teus|todas as|todas|as suas|qualquer)\s+(instruc|regra|diretriz|orientac|restric)\w*",
        r"\b(ignor|desconsider|despreze|sobrescrev)\w*\b.{0,20}\b(prompt|system)\b",
        r"\b(primeira|ultima|anterior|inicial) mensagem que (voce|vc|tu) (recebeu|recebest\w*)\b"
        r"|\bo que (te|lhe) (disseram|instruiram|mandaram) (para )?fazer\b",
        r"\bfinj\w* (que|ser)\b|\bvamos fingir\b|\bfaz de conta\b",
        r"\b(decodifiq\w*|decode|base64)\b.{0,30}\b(obede\w*|execut\w*|sig\w*|faca|cumpra)\b",
        # pedir para revelar o prompt/regras DO ASSISTENTE (não "as instruções da receita")
        r"\b(revel|mostr|exib|imprim|repit|diga|conte|escrev|vaz|copi)\w*\b.{0,40}"
        r"\b((seu|sua|suas|seus|teu|tua|tuas|teus)\s+(instruc\w*|regras|configurac\w*|diretrizes|prompt)"
        r"|prompt\w*|mensagem de sistema)\b",
        r"\b(prompt|mensagem|instruc\w*) (de |do )?(sistema|system|interno|interna|inicial|oculto|secreto)\b",
        r"\bsystem prompt\b|\bdeveloper message\b|\bjailbreak\b|\bmodo (desenvolvedor|dev|deus|irrestrito)\b",
        r"\b(voce|vc|tu) (agora )?(e|sera|vai ser|passa a ser)\b.{0,30}\b(outro|outra|um|uma)\b.{0,30}"
        r"\b(assistente|ia|modelo|hacker|personagem|sem regras|sem restric)",
        r"\b(aja|atue|finja|fingir|comporte-se|se comporte|responda) (como|que e|ser)\b.{0,30}"
        r"\b(sem (regras|restricoes|filtro)|outro assistente|desenvolvedor|administrador|root|dan)\b",
        r"\ba partir de agora\b.{0,40}\b(ignore|ignora|esqueca|voce e|voce sera|responda sem|nao siga)\b",
        # en
        r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|all|your|the)\b.{0,20}"
        r"\b(instructions|rules|prompt|guidelines)\b",
        r"\b(reveal|show|print|repeat)\b.{0,20}\b(system prompt|your instructions|your prompt|hidden prompt)\b",
        r"\byou are now\b|\bact as\b.{0,20}\b(dan|developer|admin|unrestricted)\b|\bdo anything now\b",
        # es
        r"\b(ignora|olvida)\b.{0,30}\b(instrucciones|reglas)\b",
        # comandos e execução
        r"\b(execute|executar|rode|rodar|run)\b.{0,20}\b(comando|command|shell|bash|script|codigo)\b",
        r"(\brm -rf\b|\bsudo\b|\bcurl\s+http|\bwget\s+http|;\s*(ls|cat|rm)\b|\$\()",
        # chamada de ferramenta / papéis forjados
        r"\b(search_knowledge|get_document|list_topics|call_tool|tools/call|tool_call|function_call)\b",
        r"(<\|im_start\|>|<\|im_end\|>|<\|system\|>|\[inst\]|\[/inst\]|<</?sys>>|</?tool_call>|</?system>|"
        r"^\s*(system|assistant|developer)\s*:|###\s*(system|instrucao|instruction))",
        r"\"role\"\s*:\s*\"(system|assistant|developer|tool)\"",
        # segredos
        rf"\b{_SECRET}\b.{{0,30}}\b{_ASK}\b|\b{_ASK}\b.{{0,30}}\b{_SECRET}\b",
        r"\b(api key|apikey|chaves? de api|token de acesso|senha do (servidor|sistema|admin\w*))\b",
    )
]


_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SPACED_LETTERS_RE = re.compile(r"\b(?:[a-z][.\-_* ]){2,}[a-z]\b")
_B64_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _variants(text: str) -> list[str]:
    """Texto original + versões desofuscadas (letras separadas, leetspeak, base64 embutido)."""
    f = fold(text)
    out = [text.lower(), f]
    collapsed = _SPACED_LETTERS_RE.sub(lambda m: re.sub(r"[.\-_* ]", "", m.group(0)), f)
    if collapsed != f:
        out.append(collapsed)
    leet = f.translate(_LEET)
    if leet != f:
        out.append(leet)
    for token in _B64_RE.findall(text):
        try:
            decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if decoded.isprintable():
            out.append(fold(decoded))
    return out


def injection_signals(text: str) -> list[str]:
    variants = _variants(text)
    hits = []
    for i, p in enumerate(INJECTION_PATTERNS):
        if any(p.search(v) for v in variants):
            hits.append(f"inj{i:02d}")
    return hits


HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*(\s[^<>]*)?/?\s*>")
