import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const directory = fileURLToPath(new URL("../../docs/img/", import.meta.url));
await mkdir(directory, { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
  });
  const base = process.env.LANCE_PREVIEW_URL || "http://127.0.0.1:5173";
  const screenshots = [];
  for (const [name, route] of [
    ["inicio", "/"],
    ["analise-demo", "/#/demo/analise/demo"],
    ["relatorio-demo", "/#/demo/relatorio"],
  ]) {
    await page.goto(base + route);
    await page.locator("h1").waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(500);
    await page.screenshot({
      path: path.join(directory, `${name}.png`),
      fullPage: true,
    });
    screenshots.push(`${name}.png`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(base + "/#/demo/analise/demo");
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({
    path: path.join(directory, "analise-celular.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(base);
  await page.getByRole("button", { name: "Modo claro" }).click();
  await page.screenshot({
    path: path.join(directory, "inicio-claro.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Modo escuro" }).click();
  await page.goto(base + "/#/demo/analise/demo");
  await page
    .getByRole("button", { name: "Posição inicial", exact: true })
    .click();
  for (let i = 0; i < 5; i++) {
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(directory, `frame-${i}.png`) });
    if (i < 4)
      await page
        .getByRole("button", { name: "Próximo lance", exact: true })
        .click();
  }
  await writeFile(
    path.join(directory, "capturas.json"),
    JSON.stringify(
      {
        modo: "Demonstração offline com dados didáticos; não representa inferência real.",
        telas: screenshots,
        responsivo: "390 × 844",
        desktop: "1440 × 1000",
      },
      null,
      2,
    ),
  );
  console.log(`Capturas salvas em ${directory}`);
} finally {
  await browser.close();
}
