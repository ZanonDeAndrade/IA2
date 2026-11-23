import { test, expect } from "@playwright/test";

test.skip(process.env.LANCE_E2E_JOGO_REAL !== "1", "Requer o backend real com Stockfish e MCP.");

function resposta(page, caminho, metodo = "POST") {
  return page.waitForResponse((r) => new URL(r.url()).pathname === caminho && r.request().method() === metodo);
}

async function iniciar(page) {
  const espera = resposta(page, "/api/jogo/iniciar");
  await page.getByRole("button", { name: "Iniciar partida", exact: true }).click();
  const r = await espera;
  expect(r.status()).toBe(201);
  const jogo = await r.json();
  await expect(page.locator(".play-board .board-frame")).toHaveAttribute("data-fen", jogo.fen);
  return jogo;
}

async function mover(page, jogo, uci) {
  const tabuleiro = page.locator(".play-board .board-frame");
  const espera = resposta(page, `/api/jogo/${jogo.id}/mover`);
  await tabuleiro.locator(`[data-square="${uci.slice(0, 2)}"]`).click();
  await tabuleiro.locator(`[data-square="${uci.slice(2, 4)}"]`).click();
  const r = await espera;
  expect(r.status()).toBe(200);
  expect(r.request().postDataJSON()).toEqual({ lance: uci, versao: jogo.versao });
  const atual = await r.json();
  await expect(tabuleiro).toHaveAttribute("data-fen", atual.fen);
  return atual;
}

test("joga contra o motor, recupera o estado e abre a análise pelo resultado", async ({ page }) => {
  const erros = [];
  page.on("pageerror", (e) => erros.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") erros.push(m.text()); });
  await page.goto("/#/jogar");
  await page.getByLabel("Dificuldade").selectOption("intermediario");
  const inicial = await iniciar(page);
  const atual = await mover(page, inicial, "e2e4");
  expect(atual.lances.map((lance) => lance.autor)).toEqual(["jogador", "ia"]);
  expect(atual.lances[0].avaliacao.melhor_lance).toBeTruthy();
  expect(atual.lances[1].selecao_motor.motor).toContain("Stockfish");
  await page.getByText("Ver avaliação do lance", { exact: true }).click();
  await expect(page.getByText(`Melhor alternativa ${atual.lances[0].avaliacao.melhor_lance}`, { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.locator(".play-board .board-frame")).toHaveAttribute("data-fen", atual.fen);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize().width);

  const espera = resposta(page, `/api/jogo/${inicial.id}/desistir`);
  await page.getByRole("button", { name: "Desistir", exact: true }).click();
  await page.getByRole("button", { name: "Confirmar desistência", exact: true }).click();
  const r = await espera;
  expect(r.status()).toBe(200);
  const fim = await r.json();
  expect(fim.resultado).toBe("0-1");
  expect(fim.partida_analise_id).toBeTruthy();
  await expect(page.getByRole("heading", { name: /Stockfish venceu/ })).toBeVisible();
  await page.getByRole("button", { name: "Analisar partida", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/analise/${fim.partida_analise_id}$`));
  await expect(page.getByRole("button", { name: /1 brancas, e4,/ })).toBeVisible();
  await page.goto("/#/jogar");
  await page.getByRole("region", { name: "Partidas recentes" }).getByRole("link", { name: /Intermediário.+Brancas.+0-1/ }).click();
  await expect(page).toHaveURL(new RegExp(`/jogar/${inicial.id}$`));
  await expect(page.getByRole("heading", { name: /Stockfish venceu/ })).toBeVisible();
  expect(erros).toEqual([]);
});

test("pretas recebem a abertura do motor e avaliam um lance sob demanda", async ({ page }) => {
  await page.goto("/#/jogar");
  await page.getByLabel("Cor das peças").selectOption("black");
  await page.getByLabel("Ativar treinador").uncheck();
  await page.getByLabel("Avaliar meus lances automaticamente").uncheck();
  const inicial = await iniciar(page);
  expect(inicial.cor_do_jogador).toBe("black");
  expect(inicial.configuracoes.modo_treinador).toBe(false);
  await expect(page.getByTestId("coach-panel")).toHaveCount(0);
  expect(inicial.lances).toHaveLength(1);
  expect(inicial.lances[0].autor).toBe("ia");
  await expect(page.locator(".play-board .board-frame")).toHaveAttribute("data-orientation", "black");
  const jogada = inicial.lances_legais.find((uci) => uci.startsWith("e7")) || inicial.lances_legais[0];
  const atual = await mover(page, inicial, jogada);
  expect(atual.configuracoes.analise_automatica).toBe(false);
  expect(atual.lances[1].avaliacao).toBeNull();

  const espera = resposta(page, `/api/jogo/${inicial.id}/historico/2/avaliar`);
  await page.getByRole("button", { name: "Avaliar lance", exact: true }).click();
  const r = await espera;
  expect(r.status()).toBe(200);
  const avaliado = await r.json();
  expect(avaliado.fen).toBe(atual.fen);
  expect(avaliado.lances[1].avaliacao.perspectiva).toBe("black");
  await expect(page.locator(".play-feedback .badge")).toBeVisible();
});
