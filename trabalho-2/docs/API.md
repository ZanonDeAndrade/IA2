# API e ferramentas MCP

A API segue o contrato dos mocks em [`frontend/src/mocks/`](../frontend/src/mocks/).
Respostas reais, geradas com `python -m backend.gerar_exemplos --usuario erik`,
ficam em [`docs/api/exemplos/`](api/exemplos/) e têm todos os campos dos mocks
(mais alguns extras, listados abaixo). Swagger: `http://localhost:8000/docs`.

## Convenções

- Cores: `"white"` / `"black"`.
- Classes: `"erro_grave"` (queda ≥ 30), `"erro"` (≥ 20), `"imprecisao"` (≥ 10),
  `"aceitavel"`; `null` nos lances do adversário. Limites em
  [`mcp_server/classificacao.toml`](../mcp_server/classificacao.toml).
- `cp_*`, `mate_*` e `chance_vitoria_*` são do ponto de vista do **jogador**;
  `curva_avaliacao[].cp` também (mate vira ±1500 no gráfico).
- Temas: `explicacao.tema` usa os ids da lista do agente (`peca_pendurada`,
  `garfo`...); `relatorio.temas_fracos[].tema` usa o nome da Lichess
  (`hangingPiece`, `fork`...), para cruzar com os puzzles. Os dois vêm com
  `tema_label` em português. Dicionário: [`mcp_server/tools/temas.py`](../mcp_server/tools/temas.py).
- Erros: `{"detail": "mensagem em português"}`. `400` entrada inválida (PGN, FEN,
  lance), `404` usuário/partida/tarefa inexistente, `422` corpo mal formado,
  `503` motor ou agente indisponível.

## Endpoints

| Método e rota | Corpo | Resposta (mock) | Extras em relação ao mock |
|---|---|---|---|
| `POST /api/partidas/importar` → 201 | `{usuario, max?, ritmo?}` ou `{pgn, cor_do_jogador?}` | `partidas.json` | `resultado_do_jogador`, `tarefa_id`, `origem` |
| `GET /api/partidas?usuario=x` | - | `partidas.json` | partidas já importadas, sem ir ao Chess.com |
| `POST /api/partidas/{id}/analisar` → 202 | `?refazer=true` opcional | `tarefa.json` | `tarefa_id`, `etapa` |
| `GET /api/tarefas/{id}` | - | `tarefa.json` | `etapa`: `analisando` → `explicando` (ou `cache`) |
| `GET /api/partidas/{id}` | - | `partida.json` | `todos_lances`, `uci`, `melhor_lance_uci`, `mate_*`, `status_analise` |
| `POST /api/explicar` | `{fen, lance_jogado}` | `explicacao.json` | `origem`, `cache` |
| `POST /api/chat` | `{fen, pergunta, historico?}` | `chat.json` | 503 até o agente existir |
| `GET /api/relatorio/{usuario}` | `?puzzles_por_tema=2` | `relatorio.json` | `puzzles_recomendados[]` com `fen_jogador`, `solucao_san` |
| `GET /api/saude` | - | `{api, mcp, erro_mcp, agente}` | - |

Observações para a interface:

- `status_analise`: `pendente` (ainda não analisada), `em_andamento`,
  `concluida` ou `erro`.
- `partida.lances` traz só os lances do jogador, como no mock. Para navegar pela
  partida inteira, use `todos_lances` (cada um com `fen_depois`, `uci` e `classe`).
- As setas do tabuleiro saem de `uci` (lance jogado, vermelha) e
  `melhor_lance_uci` (melhor lance, verde).
- `explicacao.origem = "motor"` indica a explicação-padrão, montada só com dados
  do motor (sem LLM): aparece enquanto o agente não está pronto ou quando ele
  esgota as tentativas. Nesse caso `ficha` é `null`.
- Puzzles: `fen` e `solucao` seguem a Lichess (o primeiro lance de `solucao` é o
  do adversário). `fen_jogador` já é a posição que o jogador resolve.

## Ferramentas MCP

| Ferramenta | Entrada | Saída |
|---|---|---|
| `analisar_posicao` | `fen`, `profundidade=18`, `multipv=3` | `avaliacao` `{cp, mate}` do lado a jogar, `avaliacao_brancas`, `melhores_lances` (`san`, `san_pt`, `uci`, `avaliacao`, `linha`), `linha_principal` |
| `analisar_partida` | `pgn`, `cor_do_jogador` | lista com um item por meio-lance (campos de `partida.lances` + `do_jogador`, `era_o_melhor`); envia progresso MCP |
| `validar_lances` | `fen`, `lances`, `em_sequencia=false`, `preferir="en"` | lista `{lance, legal, san, san_pt, uci}` |
| `descrever_posicao` | `fen` | material, peças atacadas/penduradas/sem defesa, cravadas, espetos, mate em 1, xeques, capturas e garfos possíveis, segurança dos reis |
| `buscar_partidas` | `usuario`, `max=10`, `ritmo=None` | lista de partidas com `pgn` (campos de `partidas.json`) |
| `buscar_puzzles` | `temas`, `rating_min`, `rating_max`, `quantidade=5` | lista de puzzles (campos de `relatorio.puzzles_recomendados`) |
| `buscar_conceitos` | `pergunta`, `k=4` | RAG (Zanon) |

`validar_lances` aceita `Nf3`, `Cf3`, `g1f3`, `12. Nf3!?` e `0-0`. Como "R" é rei
em português e torre em inglês, um lance legal nas duas leituras volta com
`"ambiguo": true`; a leitura escolhida segue `preferir`.

Cada chamada fica em `logs/mcp_tools.jsonl` (ferramenta, argumentos, duração,
resultado ou erro).

## Integração com o agente

[`backend/agente.py`](../backend/agente.py) chama as funções de
[`agent/graph.py`](../agent/graph.py) com as assinaturas do esqueleto:

- `explicar_erro(fen, lance_jogado, melhor_lance, linha_motor)` → `{tema, texto, ficha, ferramentas_usadas, tentativas, validada}`
- `responder_chat(fen, pergunta, historico)` → `{resposta, ferramentas_usadas, validada}`

As funções podem ser síncronas ou `async`. Enquanto lançarem
`NotImplementedError`, a API usa a explicação-padrão e o chat responde 503.
Para o LangGraph, o servidor MCP pode ser carregado com `langchain-mcp-adapters`
via stdio (`python -m mcp_server.server`) ou HTTP (`http://localhost:8001/mcp`).
