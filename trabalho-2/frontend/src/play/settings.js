export const COLORS = { white: "Brancas", black: "Pretas" };
export const LEVELS = {
  iniciante: "Iniciante",
  intermediario: "Intermediário",
  avancado: "Avançado",
  mestre: "Mestre",
};
export const MODES = {
  livre: {
    label: "Livre",
    description: "Você joga sem interrupções. O treinador ajuda só quando você pede.",
  },
  treinador: {
    label: "Treinador",
    description: "Classifica seus lances e explica automaticamente imprecisões e erros.",
  },
  intensivo: {
    label: "Aprendizado intensivo",
    description: "Comenta cada lance seu e mostra o conceito ligado à decisão.",
  },
};
export const DEFAULT_SETTINGS = {
  cor_do_jogador: "white",
  dificuldade: "iniciante",
  modo_treinador: true,
  modo_assistencia: "treinador",
  analise_automatica: true,
  mostrar_avaliacao: false,
  mostrar_melhor_lance: false,
  revelar_alternativa: true,
};
export const SOURCES = {
  qwen3: "Qwen3 + RAG · validado",
  motor: "Apoio do Stockfish · sem IA generativa",
  historico: "Histórico da partida · verificado",
  regras: "Regras do xadrez · verificado",
  ficha: "Trecho da ficha de conceitos",
  indisponivel: "Treinador indisponível",
};
export const END_REASONS = {
  xeque_mate: "Xeque-mate",
  afogamento: "Afogamento",
  material_insuficiente: "Material insuficiente",
  repeticao_quintupla: "Repetição quíntupla da posição",
  regra_75_lances: "Regra dos 75 lances",
  tripla_repeticao: "Tripla repetição da posição",
  regra_50_lances: "Regra dos 50 lances",
  desistencia: "Desistência do jogador",
  limite_de_lances: "Limite de lances atingido",
};

export function playPath(id) {
  return id ? `#/jogar/${encodeURIComponent(id)}` : "#/jogar";
}
