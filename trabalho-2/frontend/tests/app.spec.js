import { test, expect } from "@playwright/test";
import { mockApi, game, pgn, report } from "./fixtures";

test("demo navega, troca tema, filtra erros e abre puzzle sem servidor", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/healthz", (route) => route.abort());
  await page.goto("/");
  await page.getByRole("button", { name: "Modo claro" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Experimentar uma análise" }).click();
  await expect(
    page.getByText("Demonstração offline.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Entenda o lance" }),
  ).toBeVisible();
  await page.getByLabel("Só erros").check();
  await expect(
    page.getByRole("button", { name: "2 brancas, g4, Erro grave" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "1 pretas, e5, Aceitável" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Depois do lance", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Depois do lance", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page
    .getByRole("link", { name: "Ver meu progresso", exact: true })
    .click();
  await page.getByRole("button", { name: "Explorar puzzle" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Revelar primeira jogada" }).click();
  await expect(
    page.getByRole("button", { name: "Ocultar primeira jogada" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("integra contrato completo de importação, análise, explicação e chat com FEN atual", async ({
  page,
}) => {
  const captured = await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Colar PGN", exact: true }).click();
  await page.getByLabel("Identificador do jogador (opcional)").fill("alice");
  await page.getByLabel("Partida em PGN").fill(pgn);
  await page
    .getByRole("button", { name: "Importar partidas", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Analisar partida", exact: true })
    .click();
  await page.getByRole("button", { name: "2 brancas, g4, Erro grave" }).click();
  await page.getByRole("button", { name: "Explicar este lance" }).click();
  await expect(
    page.getByText("O lance g4 permite Qh4#.", { exact: false }),
  ).toBeVisible();
  await page
    .getByLabel("Pergunta sobre a posição atual")
    .fill("Por que esse lance perde?");
  await page.getByRole("button", { name: "Enviar pergunta" }).click();
  await expect(page.getByText("Observe a diagonal até o rei.")).toBeVisible();
  const chat = captured.find((r) => r.path === "/api/chat");
  expect(chat.body.fen).toBe(game.lances[2].fen_antes);
  expect(captured.find((r) => r.path === "/api/explicar").body).toEqual({
    fen: game.lances[2].fen_antes,
    lance_jogado: "g4",
  });
  await page
    .getByRole("button", { name: "Depois do lance", exact: true })
    .click();
  await expect(page.getByText("Observe a diagonal até o rei.")).toHaveCount(0);
  await page
    .getByRole("link", { name: "Ver meu progresso", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Seus pontos de atenção" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Explorar puzzle" }),
  ).toBeVisible();
  expect(captured.find((r) => r.path.endsWith("/importar")).body.pgn).toBe(pgn);
});

test("trata erro de importação e validação estruturada sem perder entrada", async ({
  page,
}) => {
  await mockApi(page, {
    handle: async (route, path) => {
      if (!path.endsWith("/importar")) return false;
      await route.fulfill({
        status: 422,
        json: {
          detail: [{ loc: ["body", "usuario"], msg: "Usuário não encontrado" }],
        },
      });
      return true;
    },
  });
  await page.goto("/");
  await page.getByLabel("Seu usuário no Chess.com").fill("nao_existe");
  await page
    .getByRole("button", { name: "Importar partidas", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Usuário não encontrado");
  await expect(page.getByLabel("Seu usuário no Chess.com")).toHaveValue(
    "nao_existe",
  );
  await expect(
    page.getByRole("button", { name: "Importar partidas", exact: true }),
  ).toBeEnabled();
});

test("acompanha tarefa em progresso e exibe falha do motor", async ({
  page,
}) => {
  let polls = 0;
  await mockApi(page, {
    handle: async (route, path) => {
      if (!path.includes("/tarefas/")) return false;
      polls++;
      await route.fulfill({
        json:
          polls === 1
            ? {
                status: "em_andamento",
                progresso: { lance_atual: 2, total_lances: 4, percentual: 50 },
              }
            : {
                status: "erro",
                progresso: { lance_atual: 2, total_lances: 4, percentual: 50 },
                erro: "Motor indisponível",
              },
      });
      return true;
    },
  });
  await page.goto("/#/analise/real-contract");
  await page
    .getByRole("button", { name: "Analisar partida", exact: true })
    .click();
  await expect(page.getByText("50%", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Motor indisponível");
});

test("não publica texto não validado e permite consultar partida salva offline", async ({
  page,
}) => {
  await mockApi(page, {
    analyzed: true,
    handle: async (route, path) => {
      if (path !== "/api/explicar") return false;
      await route.fulfill({
        json: { validada: false, texto: "TEXTO_INVALIDO_NAO_EXIBIR" },
      });
      return true;
    },
  });
  await page.goto("/#/analise/real-contract");
  await page.getByRole("button", { name: "2 brancas, g4, Erro grave" }).click();
  await page.getByRole("button", { name: "Explicar este lance" }).click();
  await expect(
    page.getByText(
      "Não foi possível validar uma explicação para esta posição.",
    ),
  ).toBeVisible();
  await expect(page.getByText("TEXTO_INVALIDO_NAO_EXIBIR")).toHaveCount(0);
  await page.route("**/api/partidas/**", (route) => route.abort());
  await page.reload();
  await expect(
    page.getByText("Exibindo a última versão salva", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Pergunta sobre a posição atual"),
  ).toBeDisabled();
});

test("relatório vazio e falha na base de puzzles preservam estatísticas", async ({
  page,
}) => {
  let empty = true;
  await mockApi(page, {
    handle: async (route, path) => {
      if (!path.includes("/relatorio/")) return false;
      await route.fulfill({
        json: empty
          ? { ...report, partidas_analisadas: 0 }
          : {
              ...report,
              puzzles_recomendados: [],
              aviso_puzzles: "Base de puzzles indisponível",
            },
      });
      return true;
    },
  });
  await page.goto("/#/relatorio/alice");
  await expect(
    page.getByRole("heading", {
      name: "Seu progresso começa na primeira análise",
    }),
  ).toBeVisible();
  empty = false;
  await page.getByRole("button", { name: "Atualizar relatório" }).click();
  await expect(page.getByText("Base de puzzles indisponível")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Sua evolução", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
