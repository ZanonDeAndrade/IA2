"""Contratos do modo jogar e formato persistido no SQLite."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.schemas import Avaliacao, Entrada, Explicacao, Ficha, FerramentaUsada, Mensagem, Movimento, Puzzle, Resumo
from mcp_server.tools.jogo import Dificuldade

Cor = Literal["white", "black"]
StatusJogo = Literal["em_andamento", "encerrada"]
Resultado = Literal["*", "1-0", "0-1", "1/2-1/2"]
EmpateReivindicado = Literal["tripla_repeticao", "regra_50_lances"]
Motivo = Literal[
    "xeque_mate", "afogamento", "material_insuficiente", "repeticao_quintupla",
    "regra_75_lances", "tripla_repeticao", "regra_50_lances", "desistencia", "limite_de_lances",
]
_UCI = r"^[a-h][1-8][a-h][1-8][qrbn]?$"


ModoAssistencia = Literal["livre", "treinador", "intensivo"]
Frequencia = Literal["sob_demanda", "erros", "todos"]
FREQUENCIA_DO_MODO: dict[str, str] = {"livre": "sob_demanda", "treinador": "erros", "intensivo": "todos"}
MODO_DA_FREQUENCIA = {valor: chave for chave, valor in FREQUENCIA_DO_MODO.items()}


class Configuracoes(Entrada):
    modo_treinador: bool = True
    # Livre: ajuda apenas sob demanda. Treinador: explica imprecisões e erros.
    # Intensivo: comenta todos os lances do jogador. O modo define a frequência.
    modo_assistencia: ModoAssistencia | None = None
    frequencia_explicacoes: Frequencia = "sob_demanda"
    analise_automatica: bool = True
    mostrar_avaliacao: bool = False
    mostrar_melhor_lance: bool = False
    revelar_alternativa: bool = True

    @model_validator(mode="after")
    def sincronizar_modo(self):
        if self.modo_assistencia is None:
            self.modo_assistencia = MODO_DA_FREQUENCIA[self.frequencia_explicacoes]
        self.frequencia_explicacoes = FREQUENCIA_DO_MODO[self.modo_assistencia]
        if self.modo_treinador and self.modo_assistencia != "livre":
            # As explicações automáticas dependem da classificação do lance.
            self.analise_automatica = True
        return self


class IniciarJogo(Configuracoes):
    cor_do_jogador: Literal["white", "black", "random"] = "white"
    dificuldade: Dificuldade = "iniciante"
    usuario: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,50}$", deprecated=True,
                                description="Campo legado. O perfil de treino é derivado de X-Sessao-Jogo.")


class Versao(Entrada):
    versao: int = Field(ge=0, strict=True)


class JogarLance(Versao):
    lance: str = Field(pattern=_UCI)


class ReivindicarEmpate(Versao):
    lance: str | None = Field(default=None, pattern=_UCI)


class SelecaoMotor(BaseModel):
    motor: str
    opcoes_uci: dict[str, bool | int]


class LanceJogo(BaseModel):
    id: str
    indice: int
    numero: int
    cor: Cor
    autor: Literal["jogador", "ia"]
    san: str
    uci: str
    fen_antes: str
    fen_depois: str
    avaliacao: Movimento | None = None
    perfil_avaliacao: str | None = None
    selecao_motor: SelecaoMotor | None = None
    sugerir_explicacao: bool = False
    # Milissegundos reais: avaliacao_ms no lance do jogador, adversario_ms no lance da IA.
    tempos: dict[str, int] = Field(default_factory=dict)


class JogoSalvo(BaseModel):
    id: str
    versao: int = 0
    criado_em: str
    cor_do_jogador: Cor
    usuario: str | None = None
    dificuldade: Dificuldade
    configuracoes: Configuracoes
    fen_inicial: str
    fen: str
    lances: list[LanceJogo] = Field(default_factory=list)
    status: StatusJogo = "em_andamento"
    resultado: Resultado = "*"
    motivo: Motivo | None = None
    pgn: str = ""
    partida_analise_id: str | None = None


class EmpateDisponivel(BaseModel):
    agora: EmpateReivindicado | None = None
    por_lance: dict[str, EmpateReivindicado] = Field(default_factory=dict)


class EstadoJogo(JogoSalvo):
    cor_da_ia: Cor
    vez: Literal["jogador", "ia"] | None
    cor_da_vez: Cor | None
    em_xeque: bool
    processando: bool
    lances_legais: list[str]
    empate_reivindicavel: EmpateDisponivel
    estatisticas: Resumo


class PartidaDaSessao(BaseModel):
    id: str
    criado_em: str
    cor_do_jogador: Cor
    dificuldade: Dificuldade
    status: StatusJogo
    resultado: Resultado
    partida_analise_id: str | None = None


class PartidasDaSessao(BaseModel):
    partidas: list[PartidaDaSessao]


class HistoricoJogo(BaseModel):
    id: str
    versao: int
    lances: list[LanceJogo]


class ResultadoJogo(BaseModel):
    id: str
    resultado: Resultado
    motivo: Motivo
    pgn: str
    partida_analise_id: str | None
    estatisticas: Resumo


class DicaPosicao(BaseModel):
    san: str
    uci: str


class AvaliacaoPosicao(BaseModel):
    versao: int
    avaliacao: Avaliacao
    dica: DicaPosicao | None = None


class AlterarConfiguracoes(Versao):
    modo_assistencia: ModoAssistencia | None = None
    mostrar_avaliacao: bool | None = None
    mostrar_melhor_lance: bool | None = None
    revelar_alternativa: bool | None = None


StatusExplicacao = Literal["pendente", "em_andamento", "concluida", "cancelada", "ignorada", "erro"]
FonteExplicacao = Literal["qwen3", "motor", "classificacao"]


class ContextoExplicacao(BaseModel):
    """Vínculo obrigatório entre a explicação e o lance que a originou."""
    jogo_id: str
    lance_id: str
    indice: int
    numero: int
    cor: Cor
    lance: str
    uci: str
    fen_antes: str
    fen_depois: str
    melhor_lance: str
    melhor_lance_uci: str
    classe: Literal["aceitavel", "imprecisao", "erro", "erro_grave"]
    queda: float
    versao: int


class ResultadoExplicacao(Explicacao):
    tipo: Literal["explicacao", "comentario", "classificacao"]
    fonte: FonteExplicacao
    modelo: str | None = None


class ExplicacaoJogo(BaseModel):
    id: str
    indice: int
    status: StatusExplicacao
    tipo: Literal["explicacao", "comentario"]
    origem: Literal["automatica", "manual"]
    tentativas: int
    contexto: ContextoExplicacao
    resultado: ResultadoExplicacao | None = None
    erro: str | None = None
    criado_em: str
    concluido_em: str | None = None
    duracao_ms: int | None = None


class PedidoExplicacao(Entrada):
    forcar: bool = False


class StatusTreinador(BaseModel):
    configurado: bool
    disponivel: bool
    provedor: str | None
    modelo: str | None
    verificado_em: float
    mensagem: str


class PedidoDica(Versao):
    nivel: int = Field(ge=1, le=3, strict=True)


class LanceSugerido(BaseModel):
    san: str
    uci: str


class Dica(BaseModel):
    jogo_id: str
    versao: int
    fen: str
    nivel: int
    texto: str
    tipo: str
    tema: str
    tema_label: str
    casa: str | None = None
    lance: LanceSugerido | None = None
    ficha: Ficha | None = None
    conceito: str | None = None
    fonte: Literal["stockfish"] = "stockfish"
    criado_em: str
    duracao_ms: int


class PainelTreinador(BaseModel):
    jogo_id: str
    versao: int
    modo_assistencia: ModoAssistencia
    treinador: StatusTreinador
    explicacoes: list[ExplicacaoJogo]
    dicas: list[Dica]
    fila: dict[str, int]


class PerguntaJogo(Versao):
    pergunta: str = Field(min_length=1, max_length=2000)
    indice: int | None = Field(default=None, ge=1, le=600)
    posicao: Literal["atual", "apos_lance"] = "atual"
    historico: list[Mensagem] = Field(default_factory=list, max_length=12)


class ChatJogo(BaseModel):
    jogo_id: str
    versao: int
    fen: str
    indice: int | None
    lance: str | None
    pergunta: str
    resposta: str
    ferramentas_usadas: list[FerramentaUsada]
    validada: bool
    status: Literal["ok", "indisponivel"]
    fallback: bool = False
    fonte: Literal["qwen3", "historico", "regras", "ficha", "motor", "indisponivel"]
    duracao_ms: int


class LanceCritico(BaseModel):
    indice: int
    numero: int
    san: str
    classe: str
    queda: float
    melhor_lance: str
    fen_antes: str
    explicacao_status: StatusExplicacao | None
    tema_label: str | None


class TemaPartida(BaseModel):
    tema: str
    tema_label: str
    ocorrencias: int
    indices: list[int]


class FasePartida(BaseModel):
    fase: Literal["inicio", "meio", "fim"]
    primeiro_lance: int
    ultimo_lance: int
    lances: int
    precisao: float | None
    imprecisoes: int
    erros: int
    erros_graves: int


class RelatorioJogo(BaseModel):
    id: str
    status: StatusJogo
    resultado: Resultado
    motivo: Motivo | None
    cor_do_jogador: Cor
    dificuldade: Dificuldade
    modo_assistencia: ModoAssistencia
    total_meios_lances: int
    lances_do_jogador: int
    estatisticas: Resumo
    lances_criticos: list[LanceCritico]
    temas: list[TemaPartida]
    dificuldades: list[str]
    evolucao: list[FasePartida]
    dicas_usadas: dict[str, int]
    explicacoes: dict[str, int]
    recomendacoes: list[str]
    puzzles: list[Puzzle]
    puzzles_por_tema: bool
    aviso_puzzles: str | None
    partida_analise_id: str | None
    status_analise: str | None


class MetricaTempo(BaseModel):
    amostras: int
    media_ms: float | None
    mediana_ms: float | None
    maximo_ms: int | None


class Metricas(BaseModel):
    adversario: MetricaTempo
    avaliacao: MetricaTempo
    explicacao_qwen3: MetricaTempo
    explicacao_motor: MetricaTempo
    dica: MetricaTempo
