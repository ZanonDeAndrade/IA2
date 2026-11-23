# Integração do frontend com a API Lance a Lance

A interface consome apenas HTTP/JSON. A base local é `http://127.0.0.1:8000`.
A documentação interativa fica em `/docs` e os modelos de entrada e saída
descrevem-se em `/openapi.json`.

A API de partidas interativas tem um contrato próprio, com operação
versionada por turno. [Contratos do modo Jogar contra IA](JOGAR_CONTRA_IA.md#api-http) ·
[Fila de explicações, dicas, chat e relatório do treinador](TREINADOR.md#api-do-treinador)

A interface está em `frontend/`. No desenvolvimento, o Vite em
`http://127.0.0.1:5173` encaminha `/api` e `/healthz` para essa API. No Compose,
o Nginx do serviço `frontend` encaminha para `backend:8000`. Para a execução
local no Windows, `preparar.ps1` prepara o ambiente e `iniciar.ps1` inicia os
serviços. Veja o [guia da interface](../frontend/README.md).

## Execução local

1. Copie `.env.example` para `.env` se o arquivo ainda não existir.
2. Rode `docker compose up --build`. A API espera o MCP ficar saudável.
3. Confira `curl -fsS http://127.0.0.1:8000/healthz`.
4. Configure `CORS_ORIGENS` com as origens da interface, separadas por vírgula.
   Os padrões permitem Vite em `http://localhost:5173` e
   `http://127.0.0.1:5173`. Reinicie a API após alterar.
5. Configure `CHESSCOM_USER_AGENT` para importação pública. Configure o LLM
   autorizado em `.env` para explicações completas e chat. As chaves ficam
   no backend. A interface precisa somente da URL da API.

Sem Docker, instale as dependências com Python 3.12, configure
`STOCKFISH_PATH`, rode `python -m knowledge_base.index` e
`python -m data.scripts.download_puzzles --recorte-versionado`. Inicie
`python -m uvicorn backend.main:app --port 8000`. A API inicia o MCP via stdio
quando `MCP_URL` está vazio. Para um processo separado, execute
`python -m mcp_server.server --http` e aponte a API para
`MCP_URL=http://127.0.0.1:8001/mcp`. O Compose já usa HTTP entre seus serviços.

## Rotas e códigos

| Método e rota | Corpo ou parâmetro | Sucesso | Erros específicos |
| --- | --- | --- | --- |
| `POST /api/partidas/importar` | Usuário e filtros ou PGN | 201, lista de partidas | 404 usuário ausente, 422 entrada/PGN inválido, 502 Chess.com, 503 dependência/configuração |
| `POST /api/partidas/{id}/analisar` | ID da partida, sem corpo | 202, ID da tarefa | 404 partida ausente, 429 fila cheia |
| `GET /api/partidas/{id}` | ID da partida | 200, partida e análise disponível | 404 partida ausente |
| `GET /api/tarefas/{id}` | ID da tarefa | 200, progresso e referência do resultado | 404 tarefa ausente |
| `POST /api/explicar` | FEN e lance jogado | 200, explicação ou fallback com status de validação | 422 FEN/lance inválido, 503 motor, 504 prazo |
| `POST /api/chat` | FEN, pergunta, histórico e referência opcional ao lance | 200, resposta e status | 422 corpo, FEN ou referência inválida, 504 prazo |
| `GET /api/relatorio/{usuario}` | Usuário importado, associado ao PGN ou perfil de treino retornado ao iniciar a partida | 200, contagens, evolução e puzzles | 422 identificador inválido |

Erros operacionais retornam `{"detail":"mensagem"}`. Em validações de esquema,
o FastAPI devolve `detail` com uma lista de campos. Todo POST acima de
1 MiB retorna 413. Uma análise cujo trabalho falhou continua consultável
com HTTP 200 e `status:"erro"`.

## Importar

```http
POST /api/partidas/importar
Content-Type: application/json

{"usuario":"hikaru","max":1,"ritmo":"blitz"}
```

`max` aceita 1 a 50 e omite para buscar 10. `ritmo` aceita `bullet`, `blitz`,
`rapid` e `daily`. Para importar um PGN, envie o texto no campo `pgn`.
`cor_do_jogador` aceita `white` e `black`. Se omitida, a API tenta
encontrar a cor pelo `usuario` e usa brancas como padrão. `usuario` é
opcional em PGN e permite agrupar partidas no relatório.

```bash
curl -fsS 'https://lichess.org/game/export/xdFXCpYF?clocks=false&evals=false' -o /tmp/lance-publica.pgn
python -c 'import json,pathlib; print(json.dumps({"pgn":pathlib.Path("/tmp/lance-publica.pgn").read_text(),"usuario":"Stonewall_BoyRivers","cor_do_jogador":"black"}))' \
  | curl -fsS http://127.0.0.1:8000/api/partidas/importar \
    -H 'Content-Type: application/json' --data-binary @-
```

Exemplo de resposta da importação real pelo Chess.com, com o nome da
abertura sujeito aos dados disponíveis no PGN da origem.

```json
{"usuario":"hikaru","partidas":[{"id":"26452423fefdf901ea5065fc","url":"https://www.chess.com/game/live/187698958386","data":"2026-11-21","ritmo":"blitz","cor_do_jogador":"white","adversario":"Talibov_Shiroghlan","resultado":"1/2-1/2","abertura":"B01","total_lances":108,"status_analise":"pendente","jogadores":{"white":{"nome":"Hikaru","rating":3459,"resultado":"insufficient"},"black":{"nome":"Talibov_Shiroghlan","rating":3135,"resultado":"insufficient"}},"erros_graves":0}]}
```

Exiba a lista em `partidas`. `id` é estável para o mesmo jogo e perfil.
Campos desconhecidos como URL de PGN manual, rating e abertura vêm como
`null`. `resultado` segue o PGN, com `*` para partida sem resultado.

## Iniciar e acompanhar análise

```http
POST /api/partidas/22adcf954fc8fbbe7041a7a9/analisar
```

```json
{"tarefa_id":"c23f3278e8754a61a6ce4cfb31ae51a3"}
```

```http
GET /api/tarefas/c23f3278e8754a61a6ce4cfb31ae51a3
```

```json
{"id":"c23f3278e8754a61a6ce4cfb31ae51a3","partida_id":"22adcf954fc8fbbe7041a7a9","status":"concluida","progresso":{"lance_atual":81,"total_lances":81,"percentual":100.0},"iniciada_em":"2026-11-21T14:55:31.209532+00:00","erro":null,"resultado":"/api/partidas/22adcf954fc8fbbe7041a7a9"}
```

Consulte aproximadamente a cada dois segundos. Os estados são `pendente`,
`em_andamento`, `concluida` e `erro`. `lance_atual` conta meios-lances
persistidos. Uma chamada repetida reutiliza a tarefa em andamento ou concluída
com o mesmo perfil do motor. Ao concluir, siga a URL relativa de `resultado`.

## Consultar partida e navegar

```http
GET /api/partidas/22adcf954fc8fbbe7041a7a9
```

Trecho de uma resposta real, com o lance 62 e seu ponto na curva.

```json
{
  "id":"22adcf954fc8fbbe7041a7a9",
  "fen_inicial":"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
  "lances":[{
    "indice":62,"numero":31,"cor":"black","san":"Rd2","uci":"d8d2",
    "fen_antes":"3r1r2/pp3pk1/2p1pRp1/6Qp/2P5/P7/1q4PP/5R1K b - - 1 31",
    "fen_depois":"5r2/pp3pk1/2p1pRp1/6Qp/2P5/P7/1q1r2PP/5R1K w - - 2 32",
    "avaliacao_antes":{"tipo":"cp","valor":370},"avaliacao_depois":{"tipo":"cp","valor":-552},
    "perspectiva":"black","cp_antes":370,"cp_depois":-552,
    "chance_vitoria_antes":79.61445,"chance_vitoria_depois":11.58318,
    "queda":68.03127,"classe":"erro_grave","melhor_lance":"Rd7","melhor_lance_uci":"d8d7",
    "linha_motor":["Rd7","h3","Qc3","R1f3","Qxc4","Qe5","Kg8","Kh2","Qd5"],"explicacao":null
  }],
  "curva_avaliacao":[{"lance":62,"cp":552,"avaliacao":{"tipo":"cp","valor":552},"perspectiva":"white"}]
}
```

A resposta completa inclui `pgn`, jogadores, resultado, abertura, resumo
e os lances de ambos os lados. Abra o tabuleiro em `fen_inicial`. Use
`indice` para navegação e `numero` para o número SAN exibido. No painel de
erro, mostre `fen_antes` e use `uci` e `melhor_lance_uci` para as setas.
Para avançar, use `fen_depois`. As classes são `aceitavel`, `imprecisao`,
`erro` e `erro_grave`. `queda` é em pontos percentuais.

A curva começa no índice 0 e mantém perspectiva das brancas. Mate aparece
como `{"tipo":"mate","valor":0,"a_favor":false}`, com `cp:null`; exiba a
indicação de mate separadamente. Em `lances`, as avaliações são do lado que
fez o lance. `resumo` usa os lances da cor selecionada e `precisao` é
100 menos a perda média não negativa de chance de vitória, arredondada.

## Pedir uma explicação

```http
POST /api/explicar
Content-Type: application/json

{"fen":"3r1r2/pp3pk1/2p1pRp1/6Qp/2P5/P7/1q4PP/5R1K b - - 1 31","lance_jogado":"Rd2"}
```

Trecho da resposta real obtida sem LLM, com fallback validado.

```json
{
  "lance_jogado":"Rd2","melhor_lance":"Rd7","melhor_lance_uci":"d8d7",
  "classe":"erro_grave","tema":"outro","tema_label":"Outro","ficha":null,
  "ferramentas_usadas":["analisar_posicao","validar_lances"],
  "tentativas":0,"validada":true,"fallback":true,"cache":false
}
```

A API também retorna `fen`, `queda` e `texto`. A fonte, quando presente,
é um objeto com `id`, `titulo` e `arquivo`, um caminho relativo no
repositório. Use `titulo` para a exibição. `validada:false` sinaliza que
a resposta ficou indisponível ou que a variante falhou na validação.
`fallback:true` indica texto determinístico validado. `cache:true`
indica uma explicação completa recuperada do banco. Abra a explicação
sob demanda quando `lances[].explicacao` estiver vazio.

## Perguntar ao chat

```http
POST /api/chat
Content-Type: application/json

{"fen":"3r1r2/pp3pk1/2p1pRp1/6Qp/2P5/P7/1q4PP/5R1K b - - 1 31","pergunta":"Por que Rd2 foi um erro?","historico":[]}
```

```json
{"fen":"3r1r2/pp3pk1/2p1pRp1/6Qp/2P5/P7/1q4PP/5R1K b - - 1 31","pergunta":"Por que Rd2 foi um erro?","resposta":"Não foi possível confirmar uma resposta para esta posição.","ferramentas_usadas":[],"validada":false,"status":"indisponivel","fallback":false}
```

Envie o FEN exibido e, se houver, até 12 mensagens com `role` `user`
ou `assistant` e `content`. A API registra a lista de ferramentas como
objetos `{"nome":"descrever_posicao","argumentos":{"fen":"..."}}`.
Mostre o status `indisponivel` junto do texto de serviço. Perguntas podem
ter até 2.000 caracteres.

Durante a revisão de um lance, envie `lance_selecionado` com `partida_id`
e `indice` para contextualizar perguntas como “Por que esse movimento foi
ruim?”. A API verifica se o FEN é o de antes ou depois desse lance na base
persistida. Uma pergunta sobre a consequência pode consultar a posição
resultante, e as consultas sobre o tabuleiro partem do FEN exibido. O chat
reinicia o histórico quando muda o FEN ou o lance referenciado. Exiba
`fallback:true` como resposta de apoio do Stockfish, mesmo quando os lances
da variante foram confirmados.

## Relatório e puzzles

```http
GET /api/relatorio/stonewall_boyrivers
```

Exemplo real abreviado para um puzzle.

```json
{
  "usuario":"stonewall_boyrivers","partidas_analisadas":1,"rating_estimado":1828,
  "temas_fracos":[],"erros_sem_tema":2,
  "evolucao":[{"partida_id":"22adcf954fc8fbbe7041a7a9","data":"2022-11-27","imprecisoes":3,
    "erros":0,"erros_graves":2,"precisao":93.4,"lances_do_jogador_analisados":40}],
  "puzzles_recomendados":[{
    "id":"06e0K","fen":"5q2/pp2R1pk/2pP4/3nNB2/3P1P2/8/PP5P/6K1 b - - 0 31",
    "fen_origem":"5q2/pp2R1pk/2pP4/3nNp2/3P1P2/7B/PP5P/6K1 w - - 3 31","lance_preparatorio":"h3f5",
    "solucao":["f8f5","d6d7","f5b1"],"rating":1835,"temas":["crushing","endgame","hangingPiece","short"],
    "temas_label":["crushing","Final","Peça pendurada","short"],"url":"https://lichess.org/training/06e0K"
  }],
  "puzzles_personalizados_por_tema":false,"aviso_puzzles":null
}
```

`temas_fracos` contém objetos com `tema` (tag Lichess), `tema_label`
e `erros`, ordenados pela contagem de erros com explicação validada e
tema mapeado. `erros_sem_tema` cobre o restante. `rating_estimado` é
a média dos ratings conhecidos de partidas analisadas. Sem histórico,
as listas ficam vazias e o rating é `null`. Sem temas classificados,
os puzzles são recomendações gerais por faixa. Se a base de puzzles falhar,
o relatório ainda entrega as estatísticas e preenche `aviso_puzzles`. O
mesmo campo explica quando a faixa ou o tema fica vazio no recorte local.
Use `fen` para abrir o puzzle pronto para resolver e `url` para o link público.
