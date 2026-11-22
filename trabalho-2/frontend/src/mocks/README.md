# Mocks da API

Exemplos sincronizados em 21/11/2026 com as respostas da API local real para
uma partida sintética curta de `alice` contra `bob`. A análise usou Stockfish
19 via MCP; a explicação é fallback validado e o chat está indisponível porque
nenhum LLM foi configurado neste ensaio. Esses arquivos documentam os
contratos, sem representar uma avaliação experimental da IA.

A interface já usa chamadas HTTP reais por `src/lib/api.js` e não importa
estes arquivos. Os testes de contrato usam fixtures isoladas em `tests/`.
O modo de demonstração didática é separado, em `src/lib/demo.js`, com aviso
visível na tela.

| Arquivo | Endpoint simulado |
|---|---|
| `partidas.json` | `POST /api/partidas/importar` (resposta: lista de partidas importadas) |
| `tarefa.json` | `POST /api/partidas/{id}/analisar` e `GET /api/tarefas/{id}` |
| `partida.json` | `GET /api/partidas/{id}` |
| `explicacao.json` | `POST /api/explicar` |
| `chat.json` | `POST /api/chat` |
| `relatorio.json` | `GET /api/relatorio/{usuario}` |

Os modelos de `backend/schemas.py`, o `/openapi.json` e o guia
`docs/integracao-frontend.md` são as referências para alterações no contrato.
