import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { test, expect } from "@playwright/test";

const pgn = await readFile(new URL("../../data/demos/xdFXCpYF.pgn", import.meta.url), "utf8");
const semLLM = process.env.LANCE_E2E_SEM_LLM === "1";
const usuario = "Stonewall_BoyRivers";

function responseFrom(page, path, method = "GET") {
  return page.waitForResponse((r) => new URL(r.url()).pathname === path && r.request().method() === method, { timeout: 165000 });
}

function diagnosticos(page) {
  const erros = [];
  page.on("pageerror", (e) => erros.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") erros.push(m.text()); });
  page.on("requestfailed", (req) => {
    const falha = req.failure()?.errorText;
    if (falha && falha !== "net::ERR_ABORTED") erros.push(`${falha} ${new URL(req.url()).pathname}`);
  });
  page.on("response", (r) => {
    const path = new URL(r.url()).pathname;
    if (r.status() >= 400 && (path.startsWith("/api/") || path === "/healthz"))
      erros.push(`${r.status()} ${path}`);
  });
  return erros;
}

test.skip(process.env.LANCE_E2E_REAL !== "1", "Requer o Compose real com Stockfish e MCP.");

test("API real: importa uma partida pública do Chess.com e abre a partida", async ({ page }, info) => {
  test.setTimeout(90000);
  const erros = diagnosticos(page);
  await page.goto("/");
  await expect(page.getByText("Servidor conectado")).toBeVisible();
  await page.getByLabel("Seu usuário no Chess.com").fill("hikaru");
  await page.getByLabel("Quantidade de partidas").selectOption("1");
  await page.getByLabel("Ritmo", { exact: true }).selectOption("blitz");
  const importacao = responseFrom(page, "/api/partidas/importar", "POST");
  await page.getByRole("button", { name: "Importar partidas", exact: true }).click();
  const resposta = await importacao;
  expect(resposta.status()).toBe(201);
  const dados = await resposta.json();
  expect(dados.partidas).toHaveLength(1);
  const partida = dados.partidas[0];
  expect(partida.url).toMatch(/^https:\/\/www\.chess\.com\/game\//);
  expect(partida.ritmo).toBe("blitz");
  await expect(page.getByText(partida.adversario, { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: info.outputPath("inicio.png") });
  await page.getByRole("link", { name: "Abrir análise" }).click();
  await expect(page.locator(".board-frame")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/analise/${partida.id}$`));
  expect(erros).toEqual([]);
  await writeFile(info.outputPath("chesscom.json"), JSON.stringify({ id: partida.id, url: partida.url, ritmo: partida.ritmo, erros }, null, 2));
});

test("API real: PGN, motor, tabuleiro, gráfico, explicação, chat, relatório e cache", async ({ page }, info) => {
  test.setTimeout(420000);
  const erros = diagnosticos(page);
  const evidencia = { origem: "https://lichess.org/game/xdFXCpYF", viewport: [], chat: [] };
  const tabuleiro = page.locator(".board-frame");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Importar partida" })).toBeVisible();
  await expect(page.getByText("Servidor conectado")).toBeVisible();
  evidencia.frontend_ms = await page.evaluate(() => performance.getEntriesByType("navigation")[0].domContentLoadedEventEnd);
  await page.getByRole("button", { name: "Colar PGN", exact: true }).click();
  await page.getByLabel("Identificador do jogador (opcional)").fill(usuario);
  await page.getByLabel("Sua cor na partida").selectOption("black");
  await page.getByLabel("Partida em PGN").fill(pgn);
  const importacao = responseFrom(page, "/api/partidas/importar", "POST");
  await page.getByRole("button", { name: "Importar partidas", exact: true }).click();
  const resposta = await importacao;
  expect(resposta.status()).toBe(201);
  const { partidas: [importada] } = await resposta.json();
  evidencia.partida = importada.id;
  await expect(page.getByRole("heading", { name: "kopano2019 vs. Stonewall_BoyRivers" })).toBeVisible();
  const rotaPartida = `/api/partidas/${importada.id}`;
  const analisar = page.getByRole("button", { name: /^(Analisar partida|Retomar análise)$/ });
  if (await analisar.isVisible()) {
    const t = performance.now();
    const tarefa = responseFrom(page, `${rotaPartida}/analisar`, "POST");
    await analisar.click();
    await expect(page.locator(".progress-panel")).toBeVisible();
    const criada = await tarefa;
    expect(criada.status()).toBe(202);
    const { tarefa_id } = await criada.json();
    const progresso = await page.waitForResponse(async (r) => {
      if (!r.url().endsWith(`/api/tarefas/${tarefa_id}`) || !r.ok()) return false;
      return (await r.json()).status === "concluida";
    }, { timeout: 65000 });
    evidencia.progresso = (await progresso.json()).progresso;
    evidencia.analise_segundos = (performance.now() - t) / 1000;
    expect(evidencia.analise_segundos).toBeLessThan(60);
    expect(evidencia.progresso.percentual).toBe(100);
    await writeFile(info.outputPath("medicao-motor.json"), JSON.stringify(evidencia, null, 2));
  }
  await expect(page.getByRole("button", { name: /31 pretas, Rd2, Erro grave/ })).toBeVisible({ timeout: 90000 });
  const jogo = await (await page.request.get(rotaPartida)).json();
  expect(jogo.lances).toHaveLength(81);
  expect(jogo.curva_avaliacao).toHaveLength(82);
  expect(jogo.curva_avaliacao.every((p) => p.perspectiva === "white")).toBe(true);
  const alvo = jogo.lances.find((l) => l.indice === 62);
  expect(alvo.san).toBe("Rd2");
  expect(alvo.classe).toBe("erro_grave");
  evidencia.meios_lances = jogo.lances.length;
  const inicio = page.getByRole("button", { name: "Posição inicial" });
  if (await inicio.isEnabled()) await inicio.click();
  await expect(tabuleiro).toHaveAttribute("data-fen", jogo.fen_inicial);
  await page.getByRole("button", { name: "Próximo lance" }).click();
  await expect(tabuleiro).toHaveAttribute("data-fen", jogo.lances[0].fen_depois);
  await page.getByRole("button", { name: "Último lance" }).click();
  await expect(tabuleiro).toHaveAttribute("data-fen", jogo.lances.at(-1).fen_depois);
  await page.getByRole("button", { name: "Lance anterior" }).click();
  await expect(tabuleiro).toHaveAttribute("data-fen", jogo.lances.at(-2).fen_depois);

  const grafico = page.getByRole("img", { name: /Avaliação ao longo da partida/ });
  const area = grafico.locator(".recharts-cartesian-grid");
  await area.scrollIntoViewIfNeeded();
  const caixa = await area.boundingBox();
  await page.mouse.move(caixa.x + caixa.width / 2, caixa.y + caixa.height / 2);
  const dica = grafico.locator(".chart-tooltip");
  await expect(dica).toHaveText(/Meio-lance \d+/);
  const indice = Number((await dica.innerText()).match(/Meio-lance (\d+)/)[1]);
  await page.mouse.click(caixa.x + caixa.width / 2, caixa.y + caixa.height / 2);
  await expect(tabuleiro).toHaveAttribute("data-fen", indice ? jogo.lances[indice - 1].fen_depois : jogo.fen_inicial);
  evidencia.grafico_meio_lance = indice;

  await page.getByRole("button", { name: /31 pretas, Rd2, Erro grave/ }).click();
  await expect(tabuleiro).toHaveAttribute("data-fen", alvo.fen_antes);
  await expect(tabuleiro.locator('[data-square="d8"] [data-piece="bR"]')).toBeVisible();
  await page.getByRole("button", { name: "Próximo lance" }).click();
  await expect(tabuleiro).toHaveAttribute("data-fen", alvo.fen_depois);
  await page.getByRole("button", { name: "Antes do lance", exact: true }).click();
  await page.getByRole("button", { name: "Lance anterior" }).click();
  await expect(tabuleiro).toHaveAttribute("data-fen", jogo.lances[59].fen_depois);
  await page.getByRole("button", { name: /31 pretas, Rd2, Erro grave/ }).click();
  const explicar = page.getByRole("button", { name: "Explicar este lance" });
  let explicacao = alvo.explicacao;
  if (await explicar.isVisible()) {
    const espera = responseFrom(page, "/api/explicar", "POST");
    const t = performance.now();
    await explicar.click();
    const r = await espera;
    expect(r.status()).toBe(200);
    expect(r.request().postDataJSON()).toEqual({ fen: alvo.fen_antes, lance_jogado: "Rd2" });
    explicacao = await r.json();
    evidencia.explicacao_segundos = (performance.now() - t) / 1000;
  }
  expect(explicacao.validada).toBe(true);
  expect(explicacao.melhor_lance).toBe(alvo.melhor_lance);
  expect(explicacao.ferramentas_usadas).toContain("validar_lances");
  await expect(page.getByText(explicacao.texto, { exact: true })).toBeVisible();
  if (semLLM) {
    expect(explicacao.fallback).toBe(true);
    await expect(page.getByText("Explicação de apoio baseada nos dados do motor.")).toBeVisible();
  } else {
    expect(explicacao.fallback).toBe(false);
    expect(explicacao.ficha.arquivo).toMatch(/^knowledge_base\/.+\.md$/);
    await expect(page.getByText(explicacao.ficha.titulo, { exact: true }).last()).toBeVisible();
    const cache = await page.request.post("/api/explicar", { data: { fen: alvo.fen_antes, lance_jogado: "Rd2" } });
    expect(cache.ok()).toBe(true);
    expect(await cache.json()).toMatchObject({ cache: true, texto: explicacao.texto });
  }
  evidencia.explicacao = explicacao;
  await page.screenshot({ path: info.outputPath("analise.png") });

  async function perguntar(pergunta, fen, ferramenta, inicioDeContexto = false) {
    await page.getByLabel("Pergunta sobre a posição atual").fill(pergunta);
    const espera = responseFrom(page, "/api/chat", "POST");
    const t = performance.now();
    await page.getByRole("button", { name: "Enviar pergunta" }).click();
    const resp = await espera;
    expect(resp.status()).toBe(200);
    const envio = resp.request().postDataJSON();
    const retorno = await resp.json();
    expect(envio.fen).toBe(fen);
    expect(envio.lance_selecionado).toEqual({ partida_id: jogo.id, indice: 62 });
    if (inicioDeContexto) expect(envio.historico).toEqual([]);
    expect(retorno.fen).toBe(fen);
    if (semLLM) {
      expect(retorno.status).toBe("indisponivel");
      await expect(page.getByText(/O treinador está indisponível/)).toBeVisible();
    } else {
      expect(retorno.status).toBe("ok");
      expect(retorno.validada).toBe(true);
      expect(retorno.fallback).toBe(false);
      expect(retorno.ferramentas_usadas.map((f) => f.nome)).toContain(ferramenta);
      await expect(page.getByRole("log")).toContainText(retorno.resposta);
    }
    evidencia.chat.push({ ...retorno, segundos: (performance.now() - t) / 1000 });
    return retorno;
  }
  await perguntar("Qual é a situação desta posição?", alvo.fen_antes, "descrever_posicao", true);
  if (!semLLM) {
    const ameaca = await perguntar("Existe alguma peça ameaçada?", alvo.fen_antes, "descrever_posicao");
    expect(ameaca.resposta).toMatch(/sob ataque de/);
    const melhor = await perguntar("Qual seria o melhor lance?", alvo.fen_antes, "analisar_posicao");
    expect(melhor.ferramentas_usadas.some((f) => f.nome === "validar_lances" && f.argumentos.fen === alvo.fen_antes)).toBe(true);
    const motivo = await perguntar("Por que esse movimento foi ruim?", alvo.fen_antes, "analisar_posicao");
    expect(motivo.ferramentas_usadas[0].argumentos.fen).toBe(alvo.fen_depois);
    await page.getByRole("button", { name: "Depois do lance", exact: true }).click();
    await expect(tabuleiro).toHaveAttribute("data-fen", alvo.fen_depois);
    await expect(tabuleiro.locator('[data-square="d2"] [data-piece="bR"]')).toBeVisible();
    const depois = await perguntar("Quem ataca a torre preta em d2?", alvo.fen_depois, "descrever_posicao", true);
    expect(depois.resposta).toMatch(/torre das pretas na coluna d, linha dois/);
    const tema = await perguntar("Qual conceito tático está envolvido?", alvo.fen_depois, "analisar_posicao");
    expect(tema.resposta).toContain(explicacao.tema_label.toLowerCase());
  }
  const selecionado = await tabuleiro.getAttribute("data-fen");
  await page.reload();
  await expect(tabuleiro).toHaveAttribute("data-fen", selecionado);
  if (!semLLM) await expect(page.getByText(explicacao.texto, { exact: true })).toBeVisible();

  const relatorio = responseFrom(page, `/api/relatorio/${usuario}`);
  await page.getByRole("link", { name: "Ver meu progresso", exact: true }).click();
  const resp = await relatorio;
  expect(resp.status()).toBe(200);
  const dados = await resp.json();
  expect(dados.partidas_analisadas).toBeGreaterThan(0);
  expect(dados.evolucao.some((e) => e.partida_id === jogo.id)).toBe(true);
  if (!semLLM) expect(dados.temas_fracos.length).toBeGreaterThan(0);
  expect(dados.puzzles_recomendados.length).toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: "Sua evolução", exact: true })).toBeVisible();
  const primeiro = dados.puzzles_recomendados[0];
  await expect(page.getByRole("link", { name: "Treinar na Lichess" }).first()).toHaveAttribute("href", primeiro.url);
  expect(primeiro.url).toBe(`https://lichess.org/training/${primeiro.id}`);
  await page.getByRole("button", { name: "Explorar puzzle" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Fechar puzzle" }).click();
  await page.screenshot({ path: info.outputPath("relatorio.png") });
  evidencia.relatorio = { temas: dados.temas_fracos, puzzles: dados.puzzles_recomendados.map((p) => p.url) };

  const rotaRelatorio = page.url();
  for (const [width, height] of [[1440, 900], [1280, 800], [768, 1024], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await expect(page.getByRole("heading", { name: "Sua evolução", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.goto(`/#/analise/${jogo.id}`);
    await expect(tabuleiro).toBeVisible();
    await expect(page.getByLabel("Pergunta sobre a posição atual")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    if (width === 390) await page.screenshot({ path: info.outputPath("analise-celular.png") });
    await page.goto(rotaRelatorio);
    evidencia.viewport.push({ width, height });
  }
  evidencia.erros = erros;
  await writeFile(info.outputPath("fluxo.json"), JSON.stringify(evidencia, null, 2));
  expect(erros).toEqual([]);
});

test("API real: PGN inválido exibe a validação e preserva o texto", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Colar PGN", exact: true }).click();
  const campo = page.getByLabel("Partida em PGN");
  await campo.fill("1. Qz9");
  const espera = responseFrom(page, "/api/partidas/importar", "POST");
  await page.getByRole("button", { name: "Importar partidas", exact: true }).click();
  expect((await espera).status()).toBe(422);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(campo).toHaveValue("1. Qz9");
  await expect(page).not.toHaveURL(/\/analise\//);
});
