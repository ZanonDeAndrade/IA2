# Estado da implementação

O corpus ativo contém somente os PDFs presentes em `data/raw/`. A ingestão descobriu cinco documentos, extraiu texto de 614 das 648 páginas e gravou 2.606 embeddings de 384 dimensões. As 34 páginas sem texto extraível estão identificadas no manifesto local `data/sources/manifest.json` e em `data/chroma/report.json`, ambos disponíveis após a ingestão.

A busca cita o PDF e a página física. A unidade recuperada é uma página, portanto receitas em páginas diferentes podem aparecer em resultados separados.

- [Instruções de uso](README.md)
- Relatório local de avaliação em `tests/evidence/rag-evaluation.json`.
- A integração do formato PDF com o servidor MCP está pendente.

## Aplicação integrada (16/11/2026)

| Componente | Situação | Evidência |
|---|---|---|
| Corpus estruturado | **10 páginas reais do Wikilivros** (Livro de receitas, CC BY-SA 4.0, revid registrado) → **34 receitas** (uma por variante) | `data/raw/wikibooks/`, `data/normalized/recipes.json` |
| Embeddings + ChromaDB | 68 chunks (ingredientes e preparo por receita), MiniLM multilíngue 384d, persistente | `data/chroma_wikibooks/report.json` (`python -m rag.wikibooks build`) |
| Retriever do MCP | `rag.wikibooks:retrieve`: top-k cosseno + filtro híbrido (o trecho precisa citar um termo da consulta; sem isso o MiniLM trazia receitas sem relação) | `rag/wikibooks.py`, `rag/tests/test_wikibooks.py` |
| Servidor MCP + 3 tools | Real, stdio, com o corpus acima (`corpus_ready=true`) | `/ready` |
| LLM | **Ollama 0.40.16 + `qwen3:1.7b`** (CPU, 12 núcleos, ~6 GB livres); function calling real | `tests/evidence/real_e2e_*.json`, logs `tool=search_knowledge`/`get_document` |
| API FastAPI | `POST /api/v1/consultations`, `/health`, `/ready`, CORS | `backend/tests/test_api.py` + `scripts/real_e2e.py` |
| Frontend | React/TS/Vite; consulta só com ingredientes; cards, faltantes, preparo, fontes, estados | `npm test`, `npm run build`, Chromium headless contra a API real |

Pendências e limitações: latência de 1 a 4 min por consulta em CPU; o parser de ingredientes do wikitext é
heurístico (alguns nomes ruidosos, ex. "(sopa) achocolatado em pó"); o RAG de PDFs (`rag.retrieve`) não está ligado
ao MCP (não expõe `retrieve()` e não tem receitas estruturadas); design visual de referência não aplicado.
