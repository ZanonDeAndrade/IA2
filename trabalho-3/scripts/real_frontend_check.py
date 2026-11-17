"""Teste 5 (REAL): navegador abre o frontend, envia só ingredientes e mostra a resposta do backend real.

Pré-requisito: scripts/start.sh no ar. Requer `pip install playwright` e `playwright install chromium`.
    python3 scripts/real_frontend_check.py [pasta_para_capturas]
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests" / "evidence")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    api = []
    page.on("response", lambda r: api.append(f"{r.request.method} {r.url} -> {r.status}") if "/api/" in r.url else None)
    page.goto("http://localhost:5173/")
    page.get_by_label("Ingredientes que você tem").fill("ovos, farinha de trigo, leite, queijo")
    page.get_by_role("button", name="Buscar receitas").click()
    page.get_by_text("Consultando a base de receitas…").wait_for(timeout=10_000)
    page.get_by_role("heading", name="Resposta fundamentada no nosso catálogo").wait_for(timeout=330_000)
    cards = page.get_by_role("article")
    print("cards:", cards.count())
    print("primeiro card:", cards.first.inner_text().replace("\n", " | ")[:400])
    print("fontes:", [a.get_attribute("href") for a in page.locator(".results__sources a").all()])
    cards.first.get_by_role("button", name="Ver preparo").click()
    page.screenshot(path=str(out / "frontend_real_desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    print("scroll horizontal no celular:", page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
    page.screenshot(path=str(out / "frontend_real_mobile.png"), full_page=True)
    print("API:", api)
    browser.close()
