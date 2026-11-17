# Mocks da API

JSONs de exemplo com o contrato de cada endpoint do backend, para o frontend ser
construído sem depender da API real. Na integração, troque a leitura destes
arquivos pelas chamadas reais (`VITE_API_URL`).

| Arquivo | Endpoint simulado |
|---|---|
| `partidas.json` | `POST /api/partidas/importar` (resposta: lista de partidas importadas) |
| `tarefa.json` | `POST /api/partidas/{id}/analisar` e `GET /api/tarefas/{id}` |
| `partida.json` | `GET /api/partidas/{id}` |
| `explicacao.json` | `POST /api/explicar` |
| `chat.json` | `POST /api/chat` |
| `relatorio.json` | `GET /api/relatorio/{usuario}` |

Os campos ainda podem mudar: o contrato JSON é fechado pelo grupo no dia 1 e
deve ser refletido aqui e em `backend/main.py`.
