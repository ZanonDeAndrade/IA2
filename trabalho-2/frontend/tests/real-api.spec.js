import { test, expect } from "@playwright/test";
import { pgn } from "./fixtures";

test("API real: PGN, Stockfish via MCP, explicação validada, chat indisponível sem LLM e relatório", async ({
  page,
}) => {
  test.skip(
    process.env.LANCE_E2E_REAL !== "1",
    "Requer API local com Stockfish e MCP reais, sem LLM configurado.",
  );
  test.setTimeout(180000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Colar PGN", exact: true }).click();
  await page.getByLabel("Identificador do jogador (opcional)").fill("alice");
  await page.getByLabel("Partida em PGN").fill(pgn);
  await page
    .getByRole("button", { name: "Importar partidas", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "alice vs. bob" }),
  ).toBeVisible();
  const analyze = page.getByRole("button", {
    name: /^(Analisar partida|Retomar análise)$/,
  });
  if (await analyze.isVisible()) await analyze.click();
  await page
    .getByRole("button", { name: "2 brancas, g4, Erro grave" })
    .click({ timeout: 120000 });
  const explain = page.getByRole("button", { name: "Explicar este lance" });
  if (await explain.isVisible()) await explain.click();
  await expect(
    page.getByText("Explicação de apoio baseada nos dados do motor."),
  ).toBeVisible({ timeout: 120000 });
  await page
    .getByLabel("Pergunta sobre a posição atual")
    .fill("Por que g4 perde?");
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
  await expect(
    page.getByText(
      "O treinador está indisponível para esta posição. Tente novamente em instantes.",
    ),
  ).toBeVisible({ timeout: 120000 });
  await page
    .getByRole("link", { name: "Ver meu progresso", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Sua evolução", exact: true }),
  ).toBeVisible({ timeout: 120000 });
  await expect(
    page.getByRole("button", { name: "Explorar puzzle" }).first(),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
