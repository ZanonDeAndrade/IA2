import { Chess } from "chess.js";

export const pgn =
  '[White "alice"]\n[Black "bob"]\n[WhiteElo "1200"]\n[BlackElo "1300"]\n[Date "2026.11.20"]\n\n1. f3 e5 2. g4 Qh4# 0-1';
const board = new Chess();
board.loadPgn(pgn);
export const explanation = {
  fen: board.history({ verbose: true })[2].before,
  lance_jogado: "g4",
  melhor_lance: "e4",
  melhor_lance_uci: "e2e4",
  classe: "erro_grave",
  queda: 40,
  tema: "mate",
  tema_label: "Mate",
  texto:
    "O lance g4 permite Qh4#. Confira a segurança do rei antes de avançar os peões.",
  ficha: { id: "mate", titulo: "Mate", arquivo: "knowledge_base/mate.md" },
  ferramentas_usadas: ["analisar_posicao", "validar_lances"],
  validada: true,
  fallback: false,
  cache: false,
};
export const game = {
  id: "real-contract",
  usuario: "alice",
  data: "2026-11-20",
  cor_do_jogador: "white",
  jogadores: {
    white: { nome: "alice", rating: 1200 },
    black: { nome: "bob", rating: 1300 },
  },
  adversario: "bob",
  resultado: "0-1",
  abertura: null,
  total_lances: 4,
  status_analise: "concluida",
  erros_graves: 1,
  pgn,
  fen_inicial: new Chess().fen(),
  resumo: {
    imprecisoes: 1,
    erros: 0,
    erros_graves: 1,
    precisao: 70,
    lances_do_jogador_analisados: 2,
  },
  lances: board
    .history({ verbose: true })
    .map((m, i) => ({
      indice: i + 1,
      numero: Math.floor(i / 2) + 1,
      cor: m.color === "w" ? "white" : "black",
      san: m.san,
      uci: m.from + m.to,
      fen_antes: m.before,
      fen_depois: m.after,
      classe: i === 2 ? "erro_grave" : "aceitavel",
      queda: i === 2 ? 40 : 0,
      melhor_lance: i === 2 ? "e4" : m.san,
      melhor_lance_uci: i === 2 ? "e2e4" : m.from + m.to,
      linha_motor: [],
      explicacao: null,
    })),
  curva_avaliacao: [
    { lance: 0, cp: 0 },
    { lance: 1, cp: -80 },
    { lance: 2, cp: -40 },
    {
      lance: 3,
      cp: null,
      avaliacao: { tipo: "mate", valor: 1, a_favor: false },
    },
    {
      lance: 4,
      cp: null,
      avaliacao: { tipo: "mate", valor: 0, a_favor: false },
    },
  ],
};
export const report = {
  usuario: "alice",
  partidas_analisadas: 1,
  rating_estimado: 1200,
  temas_fracos: [{ tema: "mate", tema_label: "Mate", erros: 1 }],
  erros_sem_tema: 0,
  evolucao: [
    { partida_id: game.id, data: game.data, precisao: 70, erros_graves: 1 },
  ],
  puzzles_recomendados: [
    {
      id: "mate",
      fen: game.lances[3].fen_antes,
      solucao: ["d8h4"],
      rating: 600,
      temas_label: ["Mate em 1"],
      url: "https://lichess.org/training/mateIn1",
    },
  ],
  puzzles_personalizados_por_tema: true,
  aviso_puzzles: null,
};

export async function mockApi(page, overrides = {}) {
  const captured = [];
  let analyzed = false;
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    const body = req.method() === "POST" ? req.postDataJSON() : null;
    captured.push({ path, body });
    if (overrides.handle && (await overrides.handle(route, path, body))) return;
    let result;
    if (path.endsWith("/importar"))
      result = {
        usuario: "alice",
        partidas: [{ ...game, status_analise: "pendente" }],
      };
    else if (path.endsWith("/analisar")) {
      analyzed = true;
      result = { tarefa_id: "task-1" };
    } else if (path.includes("/tarefas/"))
      result = {
        id: "task-1",
        status: "concluida",
        progresso: { lance_atual: 4, total_lances: 4, percentual: 100 },
      };
    else if (path.includes("/partidas/"))
      result =
        analyzed || overrides.analyzed
          ? game
          : {
              ...game,
              status_analise: "pendente",
              lances: [],
              curva_avaliacao: [],
            };
    else if (path === "/api/explicar") result = explanation;
    else if (path === "/api/chat")
      result = {
        resposta: "Observe a diagonal até o rei.",
        validada: true,
        status: "ok",
        ferramentas_usadas: [
          { nome: "descrever_posicao", argumentos: { fen: body.fen } },
        ],
      };
    else if (path.includes("/relatorio/")) result = report;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(result || {}),
    });
  });
  await page.route("**/healthz", (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  return captured;
}
