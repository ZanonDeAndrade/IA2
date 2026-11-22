"""Teste REAL no navegador: frontend -> API -> intenção -> LLM -> MCP -> RAG -> seleção -> tela.

Reproduz o cenário do problema relatado (café da manhã com pão, manteiga, ovo e queijo) e verifica que a tela
mostra receitas agrupadas por situação, com fontes, e não uma lista de categorias.

Pré-requisito: aplicação no ar (scripts/start.sh). Requer `pip install playwright` e `playwright install chromium`.
    python3 scripts/real_frontend_check.py [pasta_para_capturas]
    FRONTEND_URL=http://localhost:5174 python3 scripts/real_frontend_check.py
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("FRONTEND_URL", "http://localhost:5173/")
out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests" / "evidence")
ok = True
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    api = []
    page.on("response", lambda r: api.append(f"{r.request.method} {r.url} -> {r.status}") if "/api/" in r.url else None)
    page.goto(URL)
    page.get_by_label("Ingredientes que você tem").fill("pão, manteiga, ovo, queijo")
    page.get_by_label("Pergunta (opcional)").fill("O que posso fazer para o meu café da manhã?")
    page.get_by_role("button", name="Buscar receitas").click()
    page.get_by_text("Consultando a base de receitas…").wait_for(timeout=10_000)
    page.get_by_role("heading", name="Resposta fundamentada no nosso catálogo").wait_for(timeout=330_000)
    answer = page.locator(".results__answer").inner_text()
    groups = [h.inner_text() for h in page.locator(".results__group-header h3").all()]
    cards = page.get_by_role("article")
    print("resposta:", answer.replace("\n", " | ")[:400])
    print("grupos:", groups)
    print("cards:", cards.count())
    for i in range(cards.count()):
        print("  -", cards.nth(i).locator("h3").inner_text(), "|", cards.nth(i).locator(".badge").inner_text())
    print("fontes:", [a.get_attribute("href") for a in page.locator(".results__sources a").all()])
    if "Categorias disponíveis" in answer or cards.count() == 0:
        ok = False
        print("FALHA: resposta sem receitas ou com lista de categorias")
    notice = page.locator(".results__notice")
    if notice.count():
        print("aviso:", notice.inner_text())
    cards.first.get_by_role("button", name="Ver preparo").click()
    page.screenshot(path=str(out / "frontend_real_desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    horizontal = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    print("scroll horizontal no celular:", horizontal)
    ok &= not horizontal
    page.screenshot(path=str(out / "frontend_real_mobile.png"), full_page=True)
    print("API:", api)
    browser.close()
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
