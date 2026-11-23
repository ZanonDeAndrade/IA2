import { expect, test } from "@playwright/test";
import { Chess } from "chess.js";

test.skip(process.env.LANCE_E2E_JOGO_REAL !== "1", "Requer a API com o modo de jogo, MCP e Stockfish reais.");

const classes = { aceitavel: "Aceitável", imprecisao: "Imprecisão", erro: "Erro", erro_grave: "Erro grave" };
const turnResponse = (page, endpoint) => page.waitForResponse(
  (response) => new URL(response.url()).pathname === endpoint && response.request().method() === "POST",
  { timeout: 50000 },
);
const matchUrl = (id) => `/api/jogo/${id}`;

async function moveOnBoard(page, uci, mobile) {
  for (const square of [uci.slice(0, 2), uci.slice(2, 4)]) {
    const tile = page.locator(`#play-board-square-${square}`);
    if (mobile) await tile.tap();
    else await tile.click();
  }
}

test("jogo real: turno do Stockfish, classificação, persistência, desistência, análise e progresso", async ({ page }, info) => {
  test.setTimeout(160000);
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const board = page.locator(".play-board .board-frame");
  const mobile = info.project.name === "mobile";
  await page.goto("/#/jogar");
  await page.getByRole("radio", { name: /Livre/ }).check();
  const created = turnResponse(page, "/api/jogo/iniciar");
  await page.getByRole("button", { name: "Iniciar partida" }).click();
  const start = await created;
  expect(start.status()).toBe(201);
  let game = await start.json();
  const url = matchUrl(game.id);
  expect(game.vez).toBe("jogador");
  await expect(board).toHaveAttribute("data-orientation", "white");
  await expect(board).toHaveAttribute("data-fen", game.fen);

  const illegal = await page.request.post(`${url}/mover`, { data: { versao: game.versao, lance: "e2e5" } });
  expect(illegal.status()).toBe(422);
  const intact = await (await page.request.get(url)).json();
  expect([intact.versao, intact.fen, intact.lances]).toEqual([game.versao, game.fen, game.lances]);

  const originalVersion = game.versao;
  const proof = [];
  for (const planned of ["e2e4", "g1f3", "d2d4"]) {
    const uci = game.lances_legais.includes(planned) ? planned : game.lances_legais.find((move) => move.length === 4);
    const before = game;
    const response = turnResponse(page, `${url}/mover`);
    await moveOnBoard(page, uci, mobile);
    const http = await response;
    expect(http.status()).toBe(200);
    game = await http.json();
    expect(game.versao).toBe(before.versao + 1);
    expect(game.lances).toHaveLength(before.lances.length + 2);
    const [player, ai] = game.lances.slice(-2);
    expect(player).toMatchObject({ uci, autor: "jogador", fen_antes: before.fen });
    expect(ai).toMatchObject({ autor: "ia", fen_antes: player.fen_depois, fen_depois: game.fen });
    expect(ai.selecao_motor.motor).toMatch(/Stockfish/i);
    const verified = new Chess(before.fen);
    for (const turn of [player, ai]) {
      const applied = verified.move(turn.san);
      expect(applied.from + applied.to + (applied.promotion || "")).toBe(turn.uci);
    }
    expect(verified.fen()).toBe(game.fen);
    await expect(board).toHaveAttribute("data-fen", game.fen);
    await expect(page.getByRole("region", { name: "Última classificação" }))
      .toContainText(classes[player.avaliacao.classe]);
    await expect(page.getByRole("region", { name: "Histórico de movimentos" }))
      .toContainText(ai.san);
    proof.push({ jogador: player.san, stockfish: ai.san, classe: player.avaliacao.classe });
  }
  expect(game.versao).toBe(originalVersion + 3);
  expect(game.estatisticas.lances_do_jogador_analisados).toBe(3);

  await page.reload();
  await expect(board).toHaveAttribute("data-fen", game.fen);
  await expect(page.getByRole("region", { name: "Histórico de movimentos" }).locator("tbody tr")).toHaveCount(3);
  const turn = game.em_xeque ? "Sua vez · você está em xeque" : "Sua vez";
  await expect(page.getByText(turn, { exact: true })).toBeVisible();
  const hints = page.getByTestId("hint-panel");
  for (const [label, level] of [["Preciso de uma dica", 1], ["Mais uma dica", 2]]) {
    const step = turnResponse(page, `${url}/dica`);
    await hints.getByRole("button", { name: label }).click();
    const response = await step;
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ nivel: level, versao: game.versao, fen: game.fen, lance: null });
  }
  await hints.getByRole("button", { name: "Mostrar o lance sugerido" }).click();
  const reveal = turnResponse(page, `${url}/dica`);
  await hints.getByRole("button", { name: "Revelar o lance" }).click();
  const position = await (await reveal).json();
  expect(game.lances_legais).toContain(position.lance.uci);
  await expect(hints).toContainText(position.lance.san);

  await page.getByRole("button", { name: "Desistir", exact: true }).click();
  const resignation = turnResponse(page, `${url}/desistir`);
  await page.getByRole("button", { name: "Confirmar desistência" }).click();
  const ended = await resignation;
  expect(ended.status()).toBe(200);
  const result = await ended.json();
  expect(result).toMatchObject({
    versao: game.versao + 1, status: "encerrada", resultado: "0-1", motivo: "desistencia", fen: game.fen,
  });
  expect(result.lances).toEqual(game.lances);
  expect(result.partida_analise_id).toBeTruthy();
  await expect(page.getByRole("heading", { name: /Stockfish venceu/ })).toBeVisible();
  await page.getByRole("button", { name: "Posição inicial" }).click();
  await expect(board).toHaveAttribute("data-fen", result.fen_inicial);
  await page.getByRole("button", { name: "Posição atual" }).click();
  await expect(board).toHaveAttribute("data-fen", result.fen);

  const reportUrl = await page.getByRole("link", { name: "Ver meu progresso" }).getAttribute("href");
  const analysis = turnResponse(page, `/api/partidas/${result.partida_analise_id}/analisar`);
  await page.getByRole("button", { name: "Analisar partida" }).click();
  expect((await analysis).status()).toBe(202);
  await expect(page).toHaveURL(new RegExp(`/analise/${result.partida_analise_id}$`));
  await expect(page.getByRole("heading", { name: "Jogador vs. Stockfish" })).toBeVisible();
  await expect.poll(async () => {
    const response = await page.request.get(`/api/partidas/${result.partida_analise_id}`);
    return (await response.json()).status_analise;
  }, { timeout: 45000 }).toBe("concluida");
  await page.goto(`/${reportUrl}`);
  await expect(page.getByText("Partidas analisadas", { exact: true })).toBeVisible();
  expect(pageErrors).toEqual([]);
  await info.attach("turnos-verificados", {
    contentType: "application/json",
    body: JSON.stringify({ id: game.id, turnos: proof, resultado: result.resultado }, null, 2),
  });
});

test("jogo real: o Stockfish abre de brancas e a orientação é restaurada no celular e desktop", async ({ page }) => {
  await page.goto("/#/jogar");
  await page.getByLabel("Cor das peças").selectOption("black");
  await page.getByLabel("Dificuldade", { exact: true }).selectOption("intermediario");
  const response = turnResponse(page, "/api/jogo/iniciar");
  await page.getByRole("button", { name: "Iniciar partida" }).click();
  const creation = await response;
  expect(creation.status()).toBe(201);
  const game = await creation.json();
  expect(game).toMatchObject({ cor_do_jogador: "black", dificuldade: "intermediario", vez: "jogador", versao: 0 });
  expect(game.lances).toHaveLength(1);
  expect(game.lances[0]).toMatchObject({ cor: "white", autor: "ia", fen_depois: game.fen });
  expect(game.lances[0].selecao_motor.motor).toMatch(/Stockfish/i);
  const board = page.locator(".play-board .board-frame");
  await expect(board).toHaveAttribute("data-orientation", "black");
  await page.reload();
  await expect(board).toHaveAttribute("data-fen", game.fen);
  await expect(board).toHaveAttribute("data-orientation", "black");
});
