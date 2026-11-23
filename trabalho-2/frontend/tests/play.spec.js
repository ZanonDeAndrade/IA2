import { expect, test } from "@playwright/test";
import { Chess } from "chess.js";
import { explanation } from "./fixtures";

const initial = new Chess().fen();
const gameId = "partida-de-teste";
const playUrl = `/#/jogar/${gameId}`;
const square = (page, name) => page.locator(`#play-board-square-${name}`);
const boardFrame = (page) => page.getByRole("region", { name: "Tabuleiro da partida" }).locator(".board-frame");
const feedback = (page) => page.getByRole("region", { name: "Última classificação" });
const history = (page) => page.getByRole("region", { name: "Histórico de movimentos" });
const coach = (page) => page.getByTestId("coach-panel");

function record(chess, uci, author, classification) {
  const number = chess.moveNumber();
  const move = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
  return {
    id: `${gameId}:${chess.history().length}`,
    numero: number, autor: author, cor: move.color === "w" ? "white" : "black",
    san: move.san, uci, fen_antes: move.before, fen_depois: move.after,
    avaliacao: classification ? {
      classe: classification, avaliacao_depois: { tipo: "cp", valor: 32 },
      melhor_lance: move.san, melhor_lance_uci: uci, linha_motor: [move.san], queda: 8,
    } : null,
    sugerir_explicacao: false,
  };
}

function snapshot(chess, options = {}, moves = []) {
  return {
    id: gameId,
    versao: 0,
    usuario: "teste",
    status: "em_andamento",
    dificuldade: "iniciante",
    cor_do_jogador: "white",
    vez: "jogador",
    processando: false,
    resultado: "*",
    fen_inicial: initial,
    fen: chess.fen(),
    lances: moves.map((move, index) => ({ ...move, indice: index + 1 })),
    lances_legais: chess.moves({ verbose: true }).map((m) => m.from + m.to + (m.promotion || "")),
    configuracoes: { modo_treinador: true, modo_assistencia: "livre", frequencia_explicacoes: "sob_demanda",
      mostrar_avaliacao: false, mostrar_melhor_lance: false, revelar_alternativa: true },
    estatisticas: { lances_do_jogador_analisados: moves.filter((move) => move.avaliacao).length, precisao: null },
    ...options,
  };
}

function job(move, status, result) {
  return {
    id: `job-${move.indice}`, indice: move.indice, status, tipo: "explicacao", origem: "automatica", tentativas: 1,
    contexto: { jogo_id: gameId, lance_id: move.id, indice: move.indice, numero: move.numero, cor: move.cor,
      lance: move.san, uci: move.uci, fen_antes: move.fen_antes, fen_depois: move.fen_depois,
      melhor_lance: move.avaliacao?.melhor_lance || move.san, melhor_lance_uci: move.uci,
      classe: move.avaliacao?.classe || "aceitavel", queda: 8, versao: 0 },
    resultado: result ? { ...explanation, fen: move.fen_antes, lance_jogado: move.san, tipo: "explicacao",
      fonte: "qwen3", modelo: "qwen3:1.7b", ...result } : null,
    erro: null, criado_em: "2026-11-23T00:00:00Z", concluido_em: result ? "2026-11-23T00:00:05Z" : null,
    duracao_ms: result ? 5000 : null,
  };
}

async function mockPlay(page, options = {}) {
  let state = options.state;
  const received = { starts: [], moves: [], aids: [], hints: [], chats: [], recoveries: 0 };
  const hints = [];
  let synced = false;
  options.syncGate?.then(() => { synced = true; });
  const opening = new Chess();
  await page.route("**/healthz", (route) => route.fulfill({ json: { status: "ok" } }));
  await page.route("**/api/jogo/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/iniciar")) {
      const settings = route.request().postDataJSON();
      received.starts.push(settings);
      if (options.startError) return route.fulfill({ status: 503, json: { detail: "Stockfish indisponível." } });
      const black = settings.cor_do_jogador === "black";
      const moves = black ? [record(opening, "e2e4", "ia")] : [];
      state = snapshot(opening, {
        dificuldade: settings.dificuldade,
        cor_do_jogador: black ? "black" : "white",
        configuracoes: settings,
      }, moves);
      return route.fulfill({ status: 201, json: state });
    }
    if (path.endsWith("/mover")) {
      const body = route.request().postDataJSON();
      received.moves.push(body);
      if (options.rejectFirst && received.moves.length === 1) {
        return route.fulfill({ status: 422, json: { detail: "O backend rejeitou esse lance." } });
      }
      const chess = new Chess(state.fen);
      const player = record(chess, body.lance, "jogador", options.classification || "imprecisao");
      player.sugerir_explicacao = Boolean(options.autoExplain);
      const reply = chess.moves({ verbose: true })[0];
      const moves = [...state.lances, player];
      if (reply) moves.push(record(chess, reply.from + reply.to + (reply.promotion || ""), "ia"));
      if (options.moveGate) await options.moveGate;
      state = snapshot(chess, {
        cor_do_jogador: state.cor_do_jogador,
        configuracoes: state.configuracoes,
        dificuldade: state.dificuldade,
        versao: state.versao + 1,
        fen_inicial: state.fen_inicial,
      }, moves);
      return route.fulfill({ json: state });
    }
    if (path.endsWith("/posicao")) {
      const params = new URL(route.request().url()).searchParams;
      const show = params.get("recomendar") === "true";
      const chess = new Chess(state.fen);
      const best = chess.moves({ verbose: true })[0];
      received.aids.push(show);
      return route.fulfill({ json: {
        versao: state.versao, avaliacao: { tipo: "cp", valor: 24 },
        dica: show && { san: best.san, uci: best.from + best.to + (best.promotion || "") } || null,
      } });
    }
    if (path.endsWith("/treinador")) {
      return route.fulfill({ json: {
        jogo_id: gameId, versao: state?.versao ?? 0, modo_assistencia: state?.configuracoes.modo_assistencia || "livre",
        treinador: { configurado: true, disponivel: !options.coachDown, provedor: "ollama", modelo: "qwen3:1.7b",
          verificado_em: 0, mensagem: options.coachDown ? "O provedor do modelo não respondeu." : "Treinador disponível." },
        explicacoes: options.jobs ? options.jobs(state) : [], dicas: hints, fila: {},
      } });
    }
    if (path.endsWith("/dica")) {
      const body = route.request().postDataJSON();
      received.hints.push(body);
      const best = new Chess(state.fen).moves({ verbose: true })[0];
      const hint = { jogo_id: gameId, versao: body.versao, fen: state.fen, nivel: body.nivel, tipo: "plano",
        tema: "outro", tema_label: "Outro", casa: body.nivel > 1 ? best.from : null,
        lance: body.nivel === 3 ? { san: best.san, uci: best.from + best.to } : null, ficha: null, conceito: null,
        texto: ["", "Objetivo verificado.", `Concentre-se na casa ${best.from}.`, `O Stockfish sugere \`${best.san}\`.`][body.nivel],
        fonte: "stockfish", criado_em: "2026-11-23T00:00:00Z", duracao_ms: 12 };
      hints.push(hint);
      return route.fulfill({ json: hint });
    }
    if (path.endsWith("/chat")) {
      const body = route.request().postDataJSON();
      received.chats.push(body);
      return route.fulfill({ json: { jogo_id: gameId, versao: body.versao, fen: state.fen, indice: null, lance: null,
        pergunta: body.pergunta, resposta: "Resposta verificada.", ferramentas_usadas: [], validada: true,
        status: "ok", fallback: false, fonte: "historico", duracao_ms: 3 } });
    }
    if (path.endsWith("/configuracoes")) {
      const body = route.request().postDataJSON();
      state = { ...state, versao: state.versao + 1, configuracoes: { ...state.configuracoes, ...body } };
      return route.fulfill({ json: state });
    }
    if (path.endsWith("/relatorio")) {
      return route.fulfill({ json: { id: gameId, status: state.status, resultado: state.resultado, motivo: state.motivo,
        cor_do_jogador: state.cor_do_jogador, dificuldade: state.dificuldade, modo_assistencia: "livre",
        total_meios_lances: state.lances.length, lances_do_jogador: 1,
        estatisticas: { imprecisoes: 1, erros: 0, erros_graves: 0, precisao: 92, lances_do_jogador_analisados: 1 },
        lances_criticos: [], temas: [], dificuldades: [], evolucao: [], dicas_usadas: { total: 0, nivel_1: 0, nivel_2: 0, nivel_3: 0 },
        explicacoes: { qwen3: 0, motor: 0, pendentes: 0, ignoradas: 0, falhas: 0, canceladas: 0 },
        recomendacoes: ["Continue jogando com o treinador ativo."], puzzles: [], puzzles_por_tema: false,
        aviso_puzzles: null, partida_analise_id: "analise-real", status_analise: "pendente" } });
    }
    if (path.endsWith("/explicar")) {
      if (options.explainGate) await options.explainGate;
      if (options.explainError) return route.fulfill({ status: 503, json: { detail: "Treinador indisponível." } });
      return route.fulfill({ json: explanation });
    }
    if (path.endsWith("/desistir")) {
      state = { ...state, versao: state.versao + 1, status: "encerrada", motivo: "desistencia",
        resultado: "0-1", vez: null, lances_legais: [], partida_analise_id: "analise-real" };
      return route.fulfill({ json: state });
    }
    received.recoveries += 1;
    // Em desenvolvimento o StrictMode repete a primeira consulta. O turno segue em
    // processamento até o teste liberar, e a interface continua consultando.
    if (options.syncGate && !synced)
      return route.fulfill({ json: { ...state, processando: true, lances_legais: [] } });
    return state ? route.fulfill({ json: state }) : route.fulfill({ status: 404, json: { detail: "Partida não encontrada." } });
  });
  return received;
}

async function playMove(page, from, to, mobile) {
  for (const name of [from, to]) {
    if (mobile) await square(page, name).tap();
    else await square(page, name).click();
  }
}

test("abre a configuração, envia as escolhas e recupera partida de pretas", async ({ page }) => {
  const received = await mockPlay(page);
  await page.goto("/");
  await page.getByRole("link", { name: "Jogar contra IA", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Configurar partida" })).toBeVisible();
  await page.getByLabel("Cor das peças").selectOption("black");
  await page.getByLabel("Dificuldade", { exact: true }).selectOption("mestre");
  await page.getByRole("radio", { name: /Livre/ }).check();
  await expect(page.getByLabel("Avaliar meus lances automaticamente")).toBeEnabled();
  await page.getByLabel("Mostrar avaliação", { exact: true }).check();
  await page.getByRole("button", { name: "Iniciar partida" }).click();
  await expect(page).toHaveURL(new RegExp(`/jogar/${gameId}$`));
  await expect(boardFrame(page)).toHaveAttribute("data-orientation", "black");
  await expect(history(page)).toContainText("e4");
  await expect(coach(page)).toContainText("Modo Livre.");
  await expect(coach(page)).toContainText("Jogue um lance para receber a orientação do treinador.");
  await expect(page.getByText("+0.2", { exact: true })).toBeVisible();
  expect(received.starts).toEqual([expect.objectContaining({
    cor_do_jogador: "black", dificuldade: "mestre", modo_assistencia: "livre",
    mostrar_avaliacao: true, mostrar_melhor_lance: false,
  })]);
  const fen = await boardFrame(page).getAttribute("data-fen");
  await page.reload();
  await expect(boardFrame(page)).toHaveAttribute("data-fen", fen);
  await expect(page.getByText("+0.2", { exact: true })).toBeVisible();
  expect(received.starts).toHaveLength(1);
});

test("movimenta, aguarda o motor, mostra classificação, solicita dica e restaura histórico", async ({ page }, info) => {
  let release;
  const moveGate = new Promise((resolve) => { release = resolve; });
  const received = await mockPlay(page, { state: snapshot(new Chess(), {
    configuracoes: { ...snapshot(new Chess()).configuracoes, modo_assistencia: "treinador" } }), moveGate });
  await page.goto(playUrl);
  await expect(boardFrame(page)).toHaveAttribute("data-fen", initial);
  await playMove(page, "e2", "e4", info.project.name === "mobile");
  await expect(page.getByText(/Stockfish processando.*e4/)).toBeVisible();
  await expect(boardFrame(page)).toHaveAttribute("data-fen", initial);
  await expect(page.getByRole("button", { name: "Desistir", exact: true })).toBeDisabled();
  await square(page, "d2").click();
  await square(page, "d4").click();
  expect(received.moves).toEqual([{ versao: 0, lance: "e2e4" }]);
  release();
  await expect(feedback(page)).toContainText("Imprecisão");
  await expect(history(page).locator("tbody td").nth(1)).not.toBeEmpty();
  await expect(history(page).getByRole("button", { name: /e4/ })).toHaveCount(0);
  expect(received.aids).toEqual([]);
  const hints = page.getByTestId("hint-panel");
  await hints.getByRole("button", { name: "Preciso de uma dica" }).click();
  await expect(hints).toContainText("Objetivo verificado.");
  await expect(hints).not.toContainText("O Stockfish sugere");
  await hints.getByRole("button", { name: "Mais uma dica" }).click();
  await expect(hints).toContainText("Concentre-se na casa");
  await hints.getByRole("button", { name: "Mostrar o lance sugerido" }).click();
  await expect(hints).toContainText("encerra o desafio desta posição");
  await hints.getByRole("button", { name: "Revelar o lance" }).click();
  await expect(hints).toContainText("O Stockfish sugere");
  expect(received.hints).toEqual([1, 2, 3].map((nivel) => ({ versao: 1, nivel })));
  expect(received.aids).toEqual([]);
  await page.getByLabel("Setas no tabuleiro").uncheck();
  const fen = await boardFrame(page).getAttribute("data-fen");
  await page.reload();
  await expect(boardFrame(page)).toHaveAttribute("data-fen", fen);
  await expect(feedback(page)).toContainText("Imprecisão");
  await expect(page.getByLabel("Setas no tabuleiro")).not.toBeChecked();
});

test("recusa movimento ilegal local e restaura a posição se o servidor rejeitar", async ({ page }) => {
  const received = await mockPlay(page, { state: snapshot(new Chess()), rejectFirst: true });
  await page.goto(playUrl);
  await playMove(page, "e2", "e5");
  await expect(page.getByRole("alert")).toContainText("Lance ilegal");
  expect(received.moves).toHaveLength(0);
  await playMove(page, "d2", "d4");
  await expect(page.getByRole("alert")).toContainText("O backend rejeitou esse lance.");
  await expect(boardFrame(page)).toHaveAttribute("data-fen", initial);
  await expect(page.getByText("Sua vez", { exact: true })).toBeVisible();
  await playMove(page, "e2", "e4");
  await expect(feedback(page)).toContainText("Imprecisão");
  expect(received.moves).toHaveLength(2);
});

test("promove por toque ou clique e envia a peça escolhida", async ({ page }, info) => {
  const position = "7k/P7/8/8/8/8/8/6K1 w - - 0 1";
  const received = await mockPlay(page, { state: snapshot(new Chess(position), { fen_inicial: position }) });
  await page.goto(playUrl);
  await playMove(page, "a7", "a8", info.project.name === "mobile");
  await expect(page.getByRole("group", { name: "Promoção de peão" })).toBeVisible();
  expect(received.moves).toHaveLength(0);
  await page.getByRole("button", { name: "cavalo", exact: true }).click();
  await expect(feedback(page)).toContainText("a8=N");
  expect(received.moves[0].lance).toBe("a7a8n");
});

test("o treinador em geração ou indisponível não trava os movimentos", async ({ page }) => {
  let late = false;
  const received = await mockPlay(page, {
    state: snapshot(new Chess(), { configuracoes: { ...snapshot(new Chess()).configuracoes, modo_assistencia: "treinador" } }),
    jobs: (state) => {
      const mine = state.lances.filter((move) => move.autor === "jogador");
      return mine.map((move, index) => index === 0 && late
        ? job(move, "concluida", { texto: "Explicação atrasada do primeiro lance." })
        : job(move, "pendente"));
    },
  });
  await page.goto(playUrl);
  await playMove(page, "e2", "e4");
  await expect(coach(page)).toContainText("Na fila do treinador");
  await playMove(page, "d2", "d4");
  await expect(feedback(page)).toContainText("d4");
  expect(received.moves).toHaveLength(2);
  late = true;
  await expect(coach(page)).toContainText("Explicações anteriores", { timeout: 15000 });
  // A resposta atrasada do primeiro lance não aparece como explicação do lance atual.
  await expect(coach(page)).toContainText("Seu lance 2. d4");
  await expect(coach(page).locator(".coach-text")).toHaveCount(0);
  await coach(page).getByText("Explicações anteriores").click();
  await coach(page).getByRole("button", { name: /Ver explicação do lance 1\. e4/ }).click();
  await expect(coach(page)).toContainText("Explicação atrasada do primeiro lance.");
  await expect(coach(page)).toContainText("Explicação anterior · 1. e4");
  await expect(page.getByText("Sua vez", { exact: true })).toBeVisible();
});

test("treinador fora do ar é informado e o jogo segue", async ({ page }) => {
  await mockPlay(page, { state: snapshot(new Chess()), coachDown: true });
  await page.goto(playUrl);
  await expect(coach(page)).toContainText("Treinador indisponível");
  await playMove(page, "e2", "e4");
  await expect(feedback(page)).toContainText("e4");
  await expect(page.getByText("Sua vez", { exact: true })).toBeVisible();
});

test("encerra por desistência e revisa sem mudar a posição real", async ({ page }) => {
  await mockPlay(page, { state: snapshot(new Chess()) });
  await page.goto(playUrl);
  await playMove(page, "e2", "e4");
  await expect(feedback(page)).toContainText("Imprecisão");
  const finalFEN = await boardFrame(page).getAttribute("data-fen");
  await page.getByRole("button", { name: "Desistir", exact: true }).click();
  await page.getByRole("button", { name: "Confirmar desistência" }).click();
  await expect(page.getByRole("heading", { name: /Stockfish venceu/ })).toBeVisible();
  await expect(page.getByText("Desistência do jogador", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analisar partida" })).toBeEnabled();
  await history(page).getByRole("button", { name: /e4, você, Imprecisão/ }).click();
  await expect(page.getByText("Revisão · após e4")).toBeVisible();
  await expect(boardFrame(page)).not.toHaveAttribute("data-fen", finalFEN);
  await history(page).getByRole("button", { name: "Posição atual" }).click();
  await expect(boardFrame(page)).toHaveAttribute("data-fen", finalFEN);
});

test("falha da API é informada no início e ao recuperar uma URL", async ({ page }) => {
  const received = await mockPlay(page, { startError: true });
  await page.goto("/#/jogar");
  await page.getByRole("button", { name: "Iniciar partida" }).click();
  await expect(page.getByRole("alert")).toContainText("Stockfish indisponível.");
  await page.goto(playUrl);
  await expect(page.getByRole("alert")).toContainText("Partida não encontrada.");
  await expect(page.getByRole("button", { name: "Tentar novamente" })).toBeVisible();
  expect(received.starts).toHaveLength(1);
});

test("recupera um turno do motor em processamento sem criar outra partida", async ({ page }) => {
  let release;
  const syncGate = new Promise((resolve) => { release = resolve; });
  const received = await mockPlay(page, { state: snapshot(new Chess()), syncGate });
  await page.goto(playUrl);
  await expect(page.getByText("Stockfish processando…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Desistir", exact: true })).toBeDisabled();
  release();
  await expect(page.getByText("Sua vez", { exact: true })).toBeVisible();
  expect(received.recoveries).toBeGreaterThanOrEqual(2);
  expect(received.starts).toHaveLength(0);
});

test("arrasta peças e acomoda desktop, notebook, tablet e celular", async ({ page }, info) => {
  test.skip(info.project.name === "mobile", "Exercita arrastar com mouse e quatro viewports no projeto desktop.");
  const received = await mockPlay(page, { state: snapshot(new Chess()) });
  await page.goto(playUrl);
  for (const [width, height] of [[1440, 1000], [1280, 800], [820, 1180], [360, 740]]) {
    await page.setViewportSize({ width, height });
    await expect(boardFrame(page)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  const rect = async (selector) => page.locator(selector).boundingBox();
  expect((await rect(".play-board")).y).toBeLessThan((await rect(".play-controls")).y);
  expect((await rect(".play-controls")).y).toBeLessThan((await rect(".play-feedback")).y);
  expect((await rect(".play-feedback")).y).toBeLessThan((await rect(".play-coach")).y);
  expect((await rect(".play-coach")).y).toBeLessThan((await rect(".play-hints")).y);
  expect((await rect(".play-hints")).y).toBeLessThan((await rect(".play-chat")).y);
  expect((await rect(".play-chat")).y).toBeLessThan((await rect(".play-history")).y);
  await page.setViewportSize({ width: 1280, height: 800 });
  const from = await square(page, "e2").boundingBox();
  const to = await square(page, "e4").boundingBox();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 });
  await page.mouse.up();
  await expect(feedback(page)).toContainText("e4");
  expect(received.moves[0].lance).toBe("e2e4");
});
