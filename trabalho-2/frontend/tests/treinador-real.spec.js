import { expect, test } from "@playwright/test";
import { Chess } from "chess.js";

// Cenário completo contra a API real (Compose, Stockfish, MCP, RAG e Qwen3 no Ollama), sem mocks HTTP.
test.skip(process.env.LANCE_E2E_TREINADOR !== "1", "Requer o Compose com Stockfish, MCP, RAG e Ollama reais.");

const VALUES = { p: 1, n: 3, b: 3, r: 5, q: 9 };
const response = (page, path, method = "POST") => page.waitForResponse(
  (r) => new URL(r.url()).pathname === path && r.request().method() === method, { timeout: 60000 },
);

// Lance que deixa uma peça menor ou maior ao alcance de um peão adversário: um erro verificável.
function blunder(fen) {
  const chess = new Chess(fen);
  const exposes = (move) => {
    const after = new Chess(fen);
    after.move(move);
    return after.moves({ verbose: true }).some((reply) => reply.to === move.to && VALUES[reply.piece] < VALUES[move.piece]);
  };
  const moves = chess.moves({ verbose: true }).filter((m) => VALUES[m.piece] >= 3 && !m.captured && exposes(m));
  return moves.sort((a, b) => VALUES[b.piece] - VALUES[a.piece] || a.lan.localeCompare(b.lan))[0];
}

async function play(page, game, uci, mobile) {
  const board = page.locator(".play-board .board-frame");
  const turn = response(page, `/api/jogo/${game.id}/mover`);
  for (const square of [uci.slice(0, 2), uci.slice(2, 4)]) {
    const tile = page.locator(`#play-board-square-${square}`);
    if (mobile) await tile.tap();
    else await tile.click();
  }
  const http = await turn;
  expect(http.status()).toBe(200);
  const next = await http.json();
  await expect(board).toHaveAttribute("data-fen", next.fen);
  return next;
}

async function waitJob(page, game, index, timeout = 300000) {
  let job;
  await expect.poll(async () => {
    const panel = await (await page.request.get(`/api/jogo/${game.id}/treinador`)).json();
    job = panel.explicacoes.find((item) => item.indice === index);
    return job?.status;
  }, { timeout, intervals: [2000] }).toMatch(/concluida|erro|ignorada|cancelada/);
  return job;
}

async function scenario(page, info, color) {
  const mobile = info.project.name === "mobile";
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("crash", () => errors.push("A página travou."));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const evidence = { cor: color, projeto: info.project.name, tempos: {} };
  const coach = page.getByTestId("coach-panel");
  const board = page.locator(".play-board .board-frame");

  // 1-6. Abrir, escolher o modo, cor, dificuldade e treinador; iniciar.
  await page.goto("/");
  await page.getByRole("link", { name: "Jogar contra IA", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Configurar partida" })).toBeVisible();
  await page.getByLabel("Cor das peças").selectOption(color);
  await page.getByLabel("Dificuldade", { exact: true }).selectOption("iniciante");
  await page.getByRole("radio", { name: /^Treinador/ }).check();
  const created = response(page, "/api/jogo/iniciar");
  await page.getByRole("button", { name: "Iniciar partida" }).click();
  const startHttp = await created;
  expect(startHttp.status()).toBe(201);
  let game = await startHttp.json();
  expect(game).toMatchObject({ cor_do_jogador: color, dificuldade: "iniciante", vez: "jogador" });
  expect(game.configuracoes.modo_assistencia).toBe("treinador");
  await expect(board).toHaveAttribute("data-orientation", color);
  if (color === "black") expect(game.lances[0]).toMatchObject({ autor: "ia", cor: "white" });

  // 7-9. Lance válido, resposta real do Stockfish e classificação antes da explicação.
  const opening = color === "white" ? "e2e4" : "e7e5";
  const first = game.lances_legais.includes(opening) ? opening : game.lances_legais[0];
  const before = game;
  const t0 = Date.now();
  game = await play(page, game, first, mobile);
  evidence.tempos.primeiro_turno_ms = Date.now() - t0;
  const [mine, reply] = game.lances.slice(-2);
  expect(mine).toMatchObject({ autor: "jogador", uci: first, fen_antes: before.fen });
  expect(reply.autor).toBe("ia");
  expect(reply.selecao_motor.motor).toMatch(/Stockfish/i);
  expect(mine.avaliacao.classe).toBeTruthy();
  await expect(page.getByRole("region", { name: "Última classificação" })).toContainText(mine.san);
  await expect(page.getByRole("region", { name: "Histórico de movimentos" })).toContainText(reply.san);

  // Erro verificável para acionar a explicação automática do modo Treinador.
  const bad = blunder(game.fen);
  expect(bad, "a posição deveria permitir expor uma peça").toBeTruthy();
  game = await play(page, game, bad.lan, mobile);
  const errorMove = game.lances.findLast((move) => move.autor === "jogador");
  expect(errorMove.uci).toBe(bad.lan);
  evidence.erro = { san: errorMove.san, classe: errorMove.avaliacao.classe, queda: errorMove.avaliacao.queda,
    melhor: errorMove.avaliacao.melhor_lance };
  expect(["imprecisao", "erro", "erro_grave"]).toContain(errorMove.avaliacao.classe);
  await expect(coach).toContainText(`${errorMove.numero}${color === "white" ? "." : "…"} ${errorMove.san}`);

  // 13. Outro lance enquanto o Qwen3 ainda pode estar explicando o anterior: o tabuleiro não trava.
  const quiet = game.lances_legais.find((uci) => {
    const chess = new Chess(game.fen);
    const move = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    return move.piece === "p" && !move.captured;
  }) || game.lances_legais[0];
  const t1 = Date.now();
  game = await play(page, game, quiet, mobile);
  evidence.tempos.turno_com_fila_ativa_ms = Date.now() - t1;
  const lastMine = game.lances.findLast((move) => move.autor === "jogador");

  // 10 e 14. Explicação do Qwen3 vinculada ao lance correto, mesmo concluída depois de outro lance.
  const job = await waitJob(page, game, errorMove.indice);
  evidence.explicacao = { status: job.status, fonte: job.resultado?.fonte, duracao_ms: job.duracao_ms,
    tema: job.resultado?.tema, ficha: job.resultado?.ficha?.titulo, texto: job.resultado?.texto };
  expect(job.status).toBe("concluida");
  expect(job.resultado.fonte).toBe("qwen3");
  expect(job.resultado.validada && !job.resultado.fallback).toBe(true);
  expect(job.contexto).toMatchObject({ lance_id: errorMove.id, fen_antes: errorMove.fen_antes,
    fen_depois: errorMove.fen_depois, lance: errorMove.san, melhor_lance: errorMove.avaliacao.melhor_lance });
  expect(job.resultado.texto).toContain(`\`${errorMove.avaliacao.melhor_lance}\``);
  await expect(coach).toContainText(`Seu lance ${lastMine.numero}${color === "white" ? "." : "…"} ${lastMine.san}`);
  await expect(coach.locator(`.coach-result[data-indice="${errorMove.indice}"]`)).toHaveCount(0);
  await coach.getByText(/Explicações anteriores/).click();
  await coach.getByRole("button", { name: new RegExp(`Ver explicação do lance ${errorMove.numero}.*${errorMove.san.replace(/[+#]/g, "")}`) }).click();
  await expect(coach.locator(`.coach-result[data-indice="${errorMove.indice}"]`)).toBeVisible();
  await expect(coach).toContainText("Qwen3 + RAG · validado");
  await expect(coach.locator(".coach-text")).toContainText(job.resultado.texto.split("`")[0].slice(0, 40));
  await coach.getByRole("button", { name: "Voltar ao lance atual" }).click();

  // 11. Dica em etapas, sem revelar o lance antes da terceira.
  const hints = page.getByTestId("hint-panel");
  const hintHttp = response(page, `/api/jogo/${game.id}/dica`);
  await hints.getByRole("button", { name: "Preciso de uma dica" }).click();
  const hint = await (await hintHttp).json();
  expect(hint).toMatchObject({ nivel: 1, versao: game.versao, fen: game.fen, lance: null, fonte: "stockfish" });
  await expect(hints).toContainText("Objetivo");
  const hint2Http = response(page, `/api/jogo/${game.id}/dica`);
  await hints.getByRole("button", { name: "Mais uma dica" }).click();
  const hint2 = await (await hint2Http).json();
  expect(hint2.lance).toBeNull();
  evidence.dicas = [hint.texto, hint2.texto];

  // 12. Chat sobre a posição e o histórico desta partida.
  const chat = page.getByTestId("game-chat");
  const chatHttp = response(page, `/api/jogo/${game.id}/chat`);
  await chat.getByRole("button", { name: "Qual foi meu maior erro até agora?" }).click();
  const answer = await (await chatHttp).json();
  expect(answer).toMatchObject({ versao: game.versao, fen: game.fen, validada: true, fonte: "historico" });
  await expect(chat).toContainText("Seu maior erro até agora foi");
  const conceptHttp = response(page, `/api/jogo/${game.id}/chat`);
  await chat.getByRole("button", { name: "O que significa cravada?" }).click();
  const concept = await (await conceptHttp).json();
  evidence.chat = { historico: answer.resposta, conceito: concept.resposta, fonte_conceito: concept.fonte,
    conceito_ms: concept.duracao_ms };
  expect(concept.validada).toBe(true);
  expect(["qwen3", "ficha"]).toContain(concept.fonte);
  await chat.getByLabel("Posição da pergunta").selectOption(String(errorMove.indice));
  const selectedHttp = response(page, `/api/jogo/${game.id}/chat`);
  await chat.getByRole("button", { name: "Estou em uma posição favorável?" }).click();
  const selected = await (await selectedHttp).json();
  expect(selected).toMatchObject({ fen: errorMove.fen_depois, indice: errorMove.indice, fonte: "motor", validada: true });
  await expect(chat.getByRole("log")).toContainText(selected.resposta);

  // 15-16. Atualizar e recuperar a partida, a explicação e a conversa.
  await page.reload();
  await expect(board).toHaveAttribute("data-fen", game.fen);
  await expect(page.getByRole("region", { name: "Histórico de movimentos" })).toContainText(errorMove.san);
  await expect(chat).toContainText("Seu maior erro até agora foi");
  await expect(coach).toContainText(lastMine.san);

  // 17-18. Encerrar e abrir o relatório com dados reais.
  await page.getByRole("button", { name: "Desistir", exact: true }).click();
  const ended = response(page, `/api/jogo/${game.id}/desistir`);
  await page.getByRole("button", { name: "Confirmar desistência" }).click();
  const final = await (await ended).json();
  expect(final).toMatchObject({ status: "encerrada", motivo: "desistencia" });
  const report = page.getByTestId("game-report");
  await expect(report).toContainText("Lances críticos");
  const savedHints = page.getByRole("region", { name: "Histórico de dicas" });
  await savedHints.locator("summary").click();
  await expect(savedHints).toContainText(hint.texto.replace(/`/g, ""));
  const reportData = await (await page.request.get(`/api/jogo/${game.id}/relatorio`)).json();
  const mineEvaluated = final.lances.filter((move) => move.autor === "jogador" && move.avaliacao);
  expect(reportData.estatisticas.lances_do_jogador_analisados).toBe(mineEvaluated.length);
  expect(reportData.lances_criticos.map((item) => item.indice)).toContain(errorMove.indice);
  expect(reportData.dicas_usadas).toMatchObject({ nivel_1: 1, nivel_2: 1, nivel_3: 0 });
  evidence.relatorio = { dificuldades: reportData.dificuldades, recomendacoes: reportData.recomendacoes,
    temas: reportData.temas, puzzles: reportData.puzzles.length };
  await report.getByRole("button", { name: new RegExp(`Revisar o lance ${errorMove.numero} `) }).click();
  await expect(page.getByText(`Revisão · após ${errorMove.san}`)).toBeVisible();
  await expect(coach.locator(`.coach-result[data-indice="${errorMove.indice}"]`)).toBeVisible();

  // 19-20. Abrir a análise e conferir PGN e lances.
  const analysis = response(page, `/api/partidas/${final.partida_analise_id}/analisar`);
  await page.getByRole("button", { name: "Analisar partida" }).click();
  expect((await analysis).status()).toBe(202);
  await expect(page).toHaveURL(new RegExp(`/analise/${final.partida_analise_id}$`));
  await expect.poll(async () => (await (await page.request.get(`/api/partidas/${final.partida_analise_id}`)).json()).status_analise,
    { timeout: 90000 }).toBe("concluida");
  const reviewed = await (await page.request.get(`/api/partidas/${final.partida_analise_id}`)).json();
  expect(reviewed.pgn).toBe(final.pgn);
  expect(reviewed.lances.map((move) => move.san)).toEqual(final.lances.map((move) => move.san));
  const analyzedError = reviewed.lances.find((move) => move.indice === errorMove.indice);
  expect(analyzedError.classe).toBe(errorMove.avaliacao.classe);
  await page.reload();
  await expect(page.getByRole("group", { name: "Lances da partida" })).toContainText(errorMove.san);
  expect(errors).toEqual([]);
  evidence.metricas = await (await page.request.get("/api/treinador/metricas")).json();
  await info.attach("evidencias", { contentType: "application/json", body: JSON.stringify(evidence, null, 2) });
}

test("treinador real com brancas no desktop", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "Cenário de brancas no desktop.");
  test.setTimeout(900000);
  await scenario(page, info, "white");
});

test("treinador real com pretas no celular", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile", "Cenário de pretas no celular.");
  test.setTimeout(900000);
  await scenario(page, info, "black");
});

// Mesmo fluxo com o Ollama inacessível: o jogo, a classificação e o histórico continuam.
test("sem Ollama o jogo continua e o treinador se declara indisponível", async ({ page }, info) => {
  const base = process.env.LANCE_E2E_SEM_LLM_URL;
  test.skip(!base || info.project.name !== "desktop", "Requer a pilha com o LLM inacessível.");
  test.setTimeout(300000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("crash", () => errors.push("A página travou."));
  const coach = page.getByTestId("coach-panel");
  const api = (path) => `${base}${path}`;
  await page.goto(`${base}/#/jogar`);
  await page.getByRole("radio", { name: /^Treinador/ }).check();
  const created = page.waitForResponse((r) => r.url().endsWith("/api/jogo/iniciar"));
  await page.getByRole("button", { name: "Iniciar partida" }).click();
  let game = await (await created).json();
  await expect(coach).toContainText("Treinador indisponível");
  await expect(coach).toContainText("A partida segue com o Stockfish");
  game = await play(page, game, "e2e4", false);
  const bad = blunder(game.fen);
  game = await play(page, game, bad.lan, false);
  const errorMove = game.lances.findLast((move) => move.autor === "jogador");
  expect(["imprecisao", "erro", "erro_grave"]).toContain(errorMove.avaliacao.classe);
  await expect(page.getByRole("region", { name: "Última classificação" })).toContainText(errorMove.san);
  let job;
  await expect.poll(async () => {
    const panel = await (await page.request.get(api(`/api/jogo/${game.id}/treinador`))).json();
    job = panel.explicacoes.find((item) => item.indice === errorMove.indice);
    return job?.status;
  }, { timeout: 60000 }).toBe("concluida");
  expect(job.resultado).toMatchObject({ fonte: "motor", fallback: true, validada: true, modelo: null });
  await expect(coach).toContainText("Apoio do Stockfish · sem IA generativa");
  await expect(coach).toContainText("O Qwen3 está indisponível");
  await expect(coach).not.toContainText("Qwen3 + RAG · validado");
  const chat = page.getByTestId("game-chat");
  const open = page.waitForResponse((r) => r.url().endsWith(`/api/jogo/${game.id}/chat`));
  await chat.getByRole("button", { name: "Por que meu último movimento foi ruim?" }).click();
  expect(await (await open).json()).toMatchObject({ status: "indisponivel", fonte: "indisponivel", validada: false });
  const history = page.waitForResponse((r) => r.url().endsWith(`/api/jogo/${game.id}/chat`));
  await chat.getByRole("button", { name: "Qual foi meu maior erro até agora?" }).click();
  expect(await (await history).json()).toMatchObject({ fonte: "historico", validada: true });
  const hint = page.waitForResponse((r) => r.url().endsWith(`/api/jogo/${game.id}/dica`));
  await page.getByTestId("hint-panel").getByRole("button", { name: "Preciso de uma dica" }).click();
  expect((await hint).status()).toBe(200);
  game = await play(page, game, game.lances_legais[0], false);
  await page.reload();
  await expect(page.locator(".play-board .board-frame")).toHaveAttribute("data-fen", game.fen);
  await page.getByRole("button", { name: "Desistir", exact: true }).click();
  await page.getByRole("button", { name: "Confirmar desistência" }).click();
  await expect(page.getByTestId("game-report")).toContainText("Lances críticos");
  const report = await (await page.request.get(api(`/api/jogo/${game.id}/relatorio`))).json();
  expect(report.explicacoes.qwen3).toBe(0);
  expect(report.explicacoes.motor).toBeGreaterThanOrEqual(1);
  expect(report.temas).toEqual([]);
  expect(errors).toEqual([]);
});
