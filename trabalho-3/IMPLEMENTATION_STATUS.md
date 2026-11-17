# Estado da implementação

O corpus ativo contém somente os PDFs presentes em `data/raw/`. A ingestão descobriu cinco documentos, extraiu texto de 614 das 648 páginas e gravou 2.606 embeddings de 384 dimensões. As 34 páginas sem texto extraível estão identificadas no manifesto local `data/sources/manifest.json` e em `data/chroma/report.json`, ambos disponíveis após a ingestão.

A busca cita o PDF e a página física. A unidade recuperada é uma página, portanto receitas em páginas diferentes podem aparecer em resultados separados.

- [Instruções de uso](README.md)
- Relatório local de avaliação em `tests/evidence/rag-evaluation.json`.
- A integração do formato PDF com o servidor MCP está pendente.
