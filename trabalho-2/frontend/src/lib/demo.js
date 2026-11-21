import { Chess } from "chess.js";
import { INITIAL_FEN } from "./chess";

// Exemplo didático local, sem inferência nem métricas experimentais reais.
export const DEMO_PGN =
  '[Event "Demonstração Lance a Lance"]\n[White "Jogador demo"]\n[Black "Treinador demo"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1';
const board = new Chess();
board.loadPgn(DEMO_PGN);
const history = board.history({ verbose: true });
const values = [-80, -50, -10000, -10000];
const lances = history.map((m, i) => ({
  indice: i + 1,
  numero: Math.floor(i / 2) + 1,
  cor: m.color === "w" ? "white" : "black",
  san: m.san,
  uci: m.from + m.to,
  fen_antes: m.before,
  fen_depois: m.after,
  classe: i === 2 ? "erro_grave" : i === 0 ? "imprecisao" : "aceitavel",
  queda: i === 2 ? 43 : i === 0 ? 12 : 0,
  melhor_lance: i === 2 ? "e4" : m.san,
  melhor_lance_uci: i === 2 ? "e2e4" : m.from + m.to,
  linha_motor: i === 2 ? ["e4"] : [m.san],
  explicacao: null,
}));
export const demoExplanation = {
  fen: lances[2].fen_antes,
  lance_jogado: "g4",
  melhor_lance: "e4",
  melhor_lance_uci: "e2e4",
  classe: "erro_grave",
  queda: 43,
  tema: "mate",
  tema_label: "Segurança do rei",
  texto:
    "O avanço g4 abre a diagonal e1–h4 e permite Qh4#, encerrando a partida. O desenvolvimento com e4 evita esse mate imediato. Antes de avançar os peões do roque, confira as diagonais que levam ao seu rei.",
  ficha: { id: "mate", titulo: "Mate", arquivo: "knowledge_base/mate.md" },
  ferramentas_usadas: [],
  validada: true,
  fallback: false,
  cache: false,
};
lances[2].explicacao = demoExplanation;
export const demoGame = {
  id: "demo",
  usuario: "jogador_demo",
  data: "2026-11-21",
  cor_do_jogador: "white",
  jogadores: {
    white: { nome: "Jogador demo", rating: 1000 },
    black: { nome: "Treinador demo", rating: 1000 },
  },
  adversario: "Treinador demo",
  resultado: "0-1",
  abertura: "Mate do Louco",
  ritmo: "rapid",
  total_lances: 4,
  status_analise: "concluida",
  erros_graves: 1,
  pgn: DEMO_PGN,
  fen_inicial: INITIAL_FEN,
  lances,
  resumo: {
    imprecisoes: 1,
    erros: 0,
    erros_graves: 1,
    precisao: null,
    lances_do_jogador_analisados: 2,
  },
  curva_avaliacao: [
    { lance: 0, cp: 0 },
    ...values.map((cp, i) => ({
      lance: i + 1,
      cp: i > 1 ? null : cp,
      avaliacao:
        i > 1
          ? { tipo: "mate", valor: i === 2 ? 1 : 0, a_favor: false }
          : { tipo: "cp", valor: cp },
    })),
  ],
};
export const demoReport = {
  usuario: "jogador_demo",
  partidas_analisadas: 1,
  rating_estimado: 1000,
  temas_fracos: [{ tema: "mate", tema_label: "Segurança do rei", erros: 1 }],
  erros_sem_tema: 0,
  evolucao: [
    {
      partida_id: "demo",
      data: "2026-11-21",
      precisao: null,
      erros_graves: 1,
      erros: 0,
      imprecisoes: 1,
    },
  ],
  puzzles_recomendados: [
    {
      id: "demo-mate",
      fen: lances[3].fen_antes,
      solucao: ["d8h4"],
      rating: 600,
      temas_label: ["Mate em 1", "Segurança do rei"],
      url: "https://lichess.org/training/mateIn1",
    },
  ],
  puzzles_personalizados_por_tema: false,
  aviso_puzzles: null,
};
