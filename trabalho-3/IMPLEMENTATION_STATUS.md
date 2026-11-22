# Estado da implementação

O corpus ativo contém somente os PDFs presentes em `data/raw/`. A ingestão descobriu cinco documentos, extraiu texto de 614 das 648 páginas e gravou 2.606 embeddings de 384 dimensões. As 34 páginas sem texto extraível estão identificadas no manifesto local `data/sources/manifest.json` e em `data/chroma/report.json`, ambos disponíveis após a ingestão.

A busca cita o PDF e a página física. A unidade recuperada é uma página, portanto receitas em páginas diferentes podem aparecer em resultados separados.

- [Instruções de uso](README.md)
- Relatório local de avaliação em `tests/evidence/rag-evaluation.json`.
- A integração do formato PDF com o servidor MCP está pendente.

## Aplicação integrada (atualizado em 17/11/2026: revisão do sistema de recomendação)

| Componente | Situação | Evidência |
|---|---|---|
| Corpus estruturado | **312 páginas reais do Wikilivros** (10 sementes + amostra uniforme de 16 categorias "X, receitas com"; CC BY-SA 4.0, revid registrado) → **470 receitas** (uma por variante), 10 categorias da navegação do próprio Wikilivros | `data/raw/wikibooks/` (+ `_manifest.json`), `data/normalized/recipes.json` |
| Embeddings + ChromaDB | 940 chunks (ingredientes com categoria; preparo), MiniLM multilíngue 384d, persistente | `data/chroma_wikibooks/report.json` |
| Normalização de ingredientes | plural, acentos, modificadores de estado/tamanho, sinônimos; partes (ovo→gema) e variedades (parmesão→queijo) sem substituições | `rag/ingredients.py`, `rag/tests/test_culinary_normalization.py` |
| Servidor MCP | compatibilidade com chaves culinárias; recuperação híbrida (semântica ∪ critério estruturado) e ranking lexicográfico documentado; parâmetro opcional `ranking` | `mcp-server/tools.py`, `mcp-server/tests/test_recommendation.py` |
| Intenção e seleção | intenção classificada pelo LLM e validada; `list_topics` só para perguntas de categorias; seleção/ordem programáticas; situações A/B/C | `backend/app/inference/intent.py`, `recommend.py`, `tests/test_intent_and_selection.py` |
| LLM | **Ollama 0.40.16 + `qwen3:1.7b`** (CPU); function calling real | `tests/evidence/real_eval_*.json` |
| API e frontend | contrato preservado (+ `topic_label`/`subcategory` opcionais); resultados agrupados em "Você pode preparar agora" / "Com ingredientes adicionais" | `backend/tests/test_api.py`, `frontend/src/**/*.test.tsx` |

Diagnóstico, critérios e limitações: [docs/recomendacao.md](docs/recomendacao.md).

### Testes (17/11/2026)

| Suíte | Tipo | Resultado |
|---|---|---|
| backend `pytest -m "not real_llm"` | LLM **roteirizado** + MCP real + corpus de fixture | 210 aprovados |
| mcp-server `pytest` | protocolo real + lógica de ranking/compatibilidade com **fixture** | 40 aprovados |
| rag `pytest` | parser e normalização (sem rede) | 52 aprovados |
| frontend `npm test` + `npm run build` | componentes com fetch **simulado** | 38 aprovados, build ok |
| `scripts/real_eval.py` | **REAL**: Ollama + MCP stdio + Chroma + corpus Wikilivros, casos A–H + 3 exemplos | 12/12 (`tests/evidence/real_eval_20261117_000953.json`) |
| `scripts/real_frontend_check.py` | **REAL** no Chromium: café da manhã com pão, manteiga, ovo e queijo | aprovado (receitas agrupadas, sem categorias) |

A avaliação real revelou e corrigiu: receita falsamente `COMPLETE` ("se quiser" da alternativa tornava a sardinha
opcional), nomes perdidos no modelo `{{w|...}}` e ruído de unidades.

Limitações: sem metadado de refeição/tempo no corpus (adequação ao café da manhã depende do LLM); ~2,5% de nomes
de ingrediente com ruído; "pão" não satisfaz "pão francês" (regra conservadora); 1 a 2 min por consulta em CPU;
o RAG de PDFs (`rag.retrieve`) continua fora do MCP; design visual de referência não aplicado.
