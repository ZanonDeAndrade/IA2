import { Chess } from "chess.js";

export const INITIAL_FEN = new Chess().fen();
export const CLASSES = {
  aceitavel: { label: "Aceitável", symbol: "✓", color: "#3caa8a" },
  imprecisao: { label: "Imprecisão", symbol: "?!", color: "#d5a52c" },
  erro: { label: "Erro", symbol: "?", color: "#f09546" },
  erro_grave: { label: "Erro grave", symbol: "??", color: "#ec6e79" },
};
export function moveUci(fen, san) {
  try {
    const m = new Chess(fen).move(san);
    return m.from + m.to + (m.promotion || "");
  } catch {
    return null;
  }
}
export function arrow(uci, color) {
  return uci
    ? { startSquare: uci.slice(0, 2), endSquare: uci.slice(2, 4), color }
    : null;
}
export function evaluation(point) {
  if (!point) return "—";
  const value = point.avaliacao;
  if (value?.tipo === "mate")
    return `Mate ${value.a_favor ? "+" : "−"}${Math.abs(value.valor)}`;
  const cp = point.cp ?? value?.valor;
  return cp == null ? "—" : `${cp >= 0 ? "+" : ""}${(cp / 100).toFixed(1)}`;
}
export function dateLabel(value) {
  if (!value) return "Data não informada";
  const date = new Date(value.slice(0, 10) + "T12:00:00");
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("pt-BR");
}
export function safeTrainingUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "lichess.org"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

export const BOARD_COLORS = {
  darkSquareStyle: { backgroundColor: "#52766a" },
  lightSquareStyle: { backgroundColor: "#e0e7df" },
};
