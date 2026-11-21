"""Validação dos corpos HTTP do Lance a Lance."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcp_server.tools.pgn import LIMITE_PGN


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Importacao(Entrada):
    usuario: str | None = Field(None, pattern=r"^[a-zA-Z0-9_-]{1,50}$")
    pgn: str | None = Field(None, min_length=1, max_length=LIMITE_PGN)
    max: int = Field(10, ge=1, le=50)
    ritmo: Literal["bullet", "blitz", "rapid", "daily"] | None = None
    cor_do_jogador: Literal["white", "black"] | None = None

    @model_validator(mode="after")
    def origem_valida(self):
        if self.pgn is None and self.usuario is None:
            raise ValueError("Informe um usuário do Chess.com ou um PGN.")
        if self.pgn is None and self.cor_do_jogador is not None:
            raise ValueError("Informe a cor apenas na importação de PGN.")
        if self.pgn is not None and self.ritmo is not None:
            raise ValueError("O filtro por ritmo se aplica à busca do Chess.com.")
        return self


class Posicao(Entrada):
    fen: str = Field(min_length=1, max_length=160)


class Lance(Posicao):
    lance_jogado: str = Field(min_length=1, max_length=16)


class Mensagem(Entrada):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class Pergunta(Posicao):
    pergunta: str = Field(min_length=1, max_length=2000)
    historico: list[Mensagem] = Field(default_factory=list, max_length=12)


class Erro(BaseModel):
    detail: str


class Centipeoes(BaseModel):
    tipo: Literal["cp"]
    valor: int


class Mate(BaseModel):
    tipo: Literal["mate"]
    valor: int
    a_favor: bool


Avaliacao = Centipeoes | Mate


class Jogador(BaseModel):
    nome: str | None
    rating: int | None
    resultado: str | None = None


class Ficha(BaseModel):
    id: str
    titulo: str
    arquivo: str


class Explicacao(BaseModel):
    fen: str
    lance_jogado: str
    melhor_lance: str
    melhor_lance_uci: str
    classe: str
    queda: float
    tema: str
    tema_label: str
    texto: str
    ficha: Ficha | None
    ferramentas_usadas: list[str]
    tentativas: int
    validada: bool
    fallback: bool
    cache: bool


class Resumo(BaseModel):
    imprecisoes: int
    erros: int
    erros_graves: int
    precisao: float | None
    lances_do_jogador_analisados: int


class PartidaImportada(BaseModel):
    id: str
    url: str | None
    data: str | None
    ritmo: str | None
    cor_do_jogador: Literal["white", "black"]
    jogadores: dict[str, Jogador]
    adversario: str | None
    resultado: str
    abertura: str | None
    total_lances: int
    status_analise: str
    erros_graves: int = 0


class Importadas(BaseModel):
    usuario: str | None
    partidas: list[PartidaImportada]


class Movimento(BaseModel):
    indice: int
    numero: int
    cor: Literal["white", "black"]
    san: str
    uci: str
    fen_antes: str
    fen_depois: str
    perspectiva: Literal["white", "black"]
    avaliacao_antes: Avaliacao
    avaliacao_depois: Avaliacao
    cp_antes: int | None
    cp_depois: int | None
    chance_vitoria_antes: float
    chance_vitoria_depois: float
    queda: float
    classe: Literal["aceitavel", "imprecisao", "erro", "erro_grave"]
    melhor_lance: str
    melhor_lance_uci: str
    linha_motor: list[str]
    explicacao: Explicacao | None


class PontoCurva(BaseModel):
    lance: int
    cp: int | None
    avaliacao: Avaliacao
    perspectiva: Literal["white"]


class Partida(PartidaImportada):
    usuario: str | None
    pgn: str
    fen_inicial: str
    eco: str | None = None
    resumo: Resumo
    lances: list[Movimento]
    curva_avaliacao: list[PontoCurva]


class TarefaCriada(BaseModel):
    tarefa_id: str


class Progresso(BaseModel):
    lance_atual: int
    total_lances: int
    percentual: float


class Tarefa(BaseModel):
    id: str
    partida_id: str
    status: Literal["pendente", "em_andamento", "concluida", "erro"]
    progresso: Progresso
    iniciada_em: str
    erro: str | None
    resultado: str | None


class FerramentaUsada(BaseModel):
    nome: str
    argumentos: dict


class Chat(BaseModel):
    fen: str
    pergunta: str
    resposta: str
    ferramentas_usadas: list[FerramentaUsada]
    validada: bool
    status: Literal["ok", "indisponivel"]


class TemaFraco(BaseModel):
    tema: str
    tema_label: str
    erros: int


class Evolucao(Resumo):
    partida_id: str
    data: str | None


class Puzzle(BaseModel):
    id: str
    fen: str
    fen_origem: str
    lance_preparatorio: str
    solucao: list[str]
    rating: int
    temas: list[str]
    temas_label: list[str]
    url: str


class Relatorio(BaseModel):
    usuario: str
    partidas_analisadas: int
    rating_estimado: int | None
    temas_fracos: list[TemaFraco]
    erros_sem_tema: int
    evolucao: list[Evolucao]
    puzzles_recomendados: list[Puzzle]
    puzzles_personalizados_por_tema: bool
    aviso_puzzles: str | None
