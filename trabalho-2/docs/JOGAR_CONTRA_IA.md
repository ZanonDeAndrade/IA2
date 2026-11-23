# Jogar contra IA

O modo Jogar contra IA usa o Stockfish pelo servidor MCP existente. O backend
aplica as regras com `python-chess`, grava o turno no SQLite e usa a mesma
análise de PGN das partidas importadas para avaliar cada lance do jogador.

## Arquitetura

- `backend/jogo/api.py` e `modelos.py` definem as rotas e os contratos Pydantic.
- `servico.py` orquestra o turno. `tabuleiro.py` aplica as regras de encerramento
  e exporta PGN. `repositorio.py` reserva a versão do jogo e confirma o turno no SQLite.
- `mcp_server/tools/jogo.py` configura o adversário UCI. `engine.py` usa o perfil
  pedagógico compartilhado pela análise de PGN e chama `agent/classifier.py`.
- `frontend/src/play/` integra o tabuleiro, o histórico, o treinador e a lista de
  partidas recentes. O tabuleiro principal adota o FEN confirmado pela API.

## Rodar

Na pasta `trabalho-2`, com o ambiente do projeto configurado:

```bash
docker compose up --build -d --wait
```

Abra `http://127.0.0.1:5173/#/jogar`. A API e o Swagger ficam em
`http://127.0.0.1:8000` e `http://127.0.0.1:8000/docs` por padrão.
O Stockfish funciona com `LLM_MODEL` vazio. Configure Ollama para gerar
explicações em português com o treinador. [Guia de execução](EXECUCAO_COMPLETA.md)

## API HTTP

| Método e rota | Corpo | Retorno |
| --- | --- | --- |
| `POST /api/jogo/iniciar` | Configuração abaixo e cabeçalho opcional `X-Sessao-Jogo` | `201` com estado e abertura da IA se o jogador escolher pretas |
| `GET /api/jogo/partidas` | Cabeçalho `X-Sessao-Jogo` e parâmetros `limite` (1–100, padrão 20) e `deslocamento` (padrão 0) | `200` com `{ "partidas": [...] }` em ordem decrescente de criação |
| `GET /api/jogo/{id}` | — | `200` com estado completo |
| `POST /api/jogo/{id}/mover` | `{"lance":"e2e4","versao":0}` | `200` com turno confirmado e avaliação do jogador, se habilitada |
| `GET /api/jogo/{id}/historico` | — | `200` com `id`, `versao` e `lances` |
| `GET /api/jogo/{id}/posicao?versao=0&recomendar=true` | — | `200` com `versao`, `avaliacao` e `dica` opcional contendo `san` e `uci` |
| `POST /api/jogo/{id}/desistir` | `{"versao":1}` | `200` com partida encerrada |
| `POST /api/jogo/{id}/reivindicar-empate` | `versao` e `lance` UCI opcional | `200` com empate confirmado quando válido |
| `GET /api/jogo/{id}/resultado` | — | `200` com resultado, motivo, PGN, estatísticas e ID para revisão |
| `POST /api/jogo/{id}/historico/{indice}/avaliar` | `versao` | `200` com a avaliação persistida no estado |
| `POST /api/jogo/{id}/historico/{indice}/explicar` | — | `200` com o contrato padrão de explicação, de forma síncrona |
| `POST /api/jogo/{id}/configuracoes` | `versao` e campos a alterar | `200` com o estado; vale a partir do próximo lance |
| Treinador | — | Fila de explicações, dicas, chat e relatório em [TREINADOR.md](TREINADOR.md#api-do-treinador) |

```json
{
  "cor_do_jogador": "white",
  "dificuldade": "iniciante",
  "modo_treinador": true,
  "modo_assistencia": "treinador",
  "analise_automatica": true
}
```

`modo_assistencia` aceita `livre`, `treinador` e `intensivo` e define
`frequencia_explicacoes` (`sob_demanda`, `erros` e `todos`). O campo antigo
continua aceito e, sem o modo, determina o modo equivalente. Com o treinador
habilitado nos modos `treinador` e `intensivo`, a avaliação automática fica
sempre ligada. `modo_treinador: false` desativa explicações, dicas e chat e
permite escolher entre avaliação automática ou sob demanda. As funções de
treinador estão detalhadas no [guia do treinador](TREINADOR.md).

Também é possível iniciar com `cor_do_jogador:"random"`, usar `X-Sessao-Jogo`
para o progresso de treino e salvar as preferências `mostrar_avaliacao` e
`mostrar_melhor_lance`. Essas duas preferências usam a consulta de posição atual.

O estado contém `id`, `versao`, `fen`, `fen_inicial`, `cor_do_jogador`,
`cor_da_ia`, `cor_da_vez`, `vez`, `status`, `em_xeque`, `processando`,
`dificuldade`, `configuracoes`, `lances`, `lances_legais`, `empate_reivindicavel`,
`resultado`, `motivo`, `estatisticas`, `pgn` e `partida_analise_id`.
Cada item de `GET /api/jogo/partidas` contém `id`, `criado_em`,
`cor_do_jogador`, `dificuldade`, `status`, `resultado` e `partida_analise_id`.

- Envie o UCI com sufixo explícito nas promoções, por exemplo `a7a8n`.
  As opções confirmadas pelo servidor aparecem em `lances_legais`.
- Use `fen` retornado pela API para atualizar o tabuleiro. Se `processando`
  estiver ativo, consulte `GET` até a versão se estabilizar. Em `409` ou erro
  de rede, consulte o estado antes de reenviar. Cada turno aceito incrementa
  `versao` uma vez. Gravar uma nova avaliação sob demanda também incrementa
  o contador. A abertura do Stockfish ao jogar de pretas já vem na versão 0.
- `lances[].indice` conta meios-lances a partir de 1. Cada registro tem
  `id`, `autor`, `cor`, `san`, `uci`, `numero`, `fen_antes` e `fen_depois`.
  `avaliacao` segue o modelo `Movimento` da análise de PGN, com melhor lance,
  variante SAN, avaliações na perspectiva do jogador, chance e classe.
  `perfil_avaliacao` identifica o perfil de análise devolvido pelo MCP.
  Os lances do Stockfish trazem `selecao_motor`, com nome e opções UCI efetivas.
  `tempos` registra `avaliacao_ms` no lance do jogador e `adversario_ms` no da IA.
- `frequencia_explicacoes` admite `sob_demanda`, `erros` e `todos`. Fora de
  `sob_demanda`, o backend agenda a explicação na fila do treinador logo depois
  do turno. A API marca `sugerir_explicacao` na jogada. A interface acompanha a
  fila por `GET /api/jogo/{id}/treinador`.
  `analise_automatica:false` deixa a avaliação disponível sob demanda.
- `404` indica partida ou lance ausente. `422` indica entrada inválida,
  lance ilegal ou empate indisponível. `409` indica conflito de versão,
  turno em processamento ou ação incompatível com o estado. `503` indica
  indisponibilidade do motor. `504` indica que o processamento ultrapassou
  o prazo do turno, de 45 s.

## Dificuldade e avaliação

| Nível | Controle solicitado | Profundidade máxima | Tempo-alvo máximo |
| --- | --- | ---: | ---: |
| Iniciante | Skill 0, ou Elo 1350 quando só houver limitação por Elo | 4 | 0,12 s |
| Intermediário | Elo 1600, ou Skill 6 | 8 | 0,25 s |
| Avançado | Elo 2000, ou Skill 14 | 12 | 0,50 s |
| Mestre | Força integral, Skill 20 quando disponível | 18 | 0,80 s |

Os perfis ficam em `mcp_server/tools/jogo.py`. O adaptador lê as opções do
binário e limita os valores ao intervalo anunciado. Em versões sem opções
de força, o perfil usa os limites de profundidade e tempo. Os valores de Elo
são parâmetros UCI e a força efetiva depende do motor, do tempo e do hardware.
O Stockfish 15.1 usado na verificação anunciou `UCI_Elo` entre 1350 e 2850,
`Skill Level` entre 0 e 20 e `UCI_LimitStrength` desligado por padrão.
O Stockfish pode escolher jogadas diferentes entre partidas enfraquecidas.
As opções do adversário são aplicadas apenas à chamada UCI de jogo. A avaliação
usa `ANALISE_PROFUNDIDADE`, MultiPV 1 e o classificador da análise tradicional.

## Resultado, revisão e acesso

Xeque-mate, afogamento, material insuficiente, repetição quíntupla e a regra
dos 75 lances encerram automaticamente. Três repetições e a regra dos 50
lances abrem uma reivindicação para o jogador. `empate_reivindicavel.agora`
é o motivo na posição atual, e `por_lance` mapeia UCI para os motivos que
dependem de declarar a próxima jogada. O lance declarado fica fora do
histórico porque a reivindicação encerra a partida antes de executá-lo.
A análise usa o histórico do PGN para atribuir avaliação neutra a um empate
automático. A detecção de material insuficiente segue o `python-chess`.

Uma partida encerrada com jogadas recebe `partida_analise_id` e pode ser
aberta em `/#/analise/{partida_analise_id}`. A API inicia essa análise
automaticamente ao fim da partida para que ela entre em Meu progresso. A tarefa
reutiliza as avaliações salvas no jogo quando o perfil coincide e consulta o
MCP para os índices restantes. Uma avaliação sob demanda pode aproveitar a
revisão concluída e acrescenta o comentário ao mesmo PGN. A interface pode
retomar uma tarefa interrompida pelo botão de análise da partida. A desistência
sem jogadas deixa o ID de revisão vazio. Ao atingir o limite técnico de 600
meios-lances do importador, o treino é arquivado com `resultado:"*"` e
`motivo:"limite_de_lances"`.

O ID aleatório funciona como referência de acesso. Quem tiver o ID pode
consultar ou jogar pela API local. O navegador guarda o último jogo ativo e
gera um token de sessão de 32 bytes aleatórios em hexadecimal. Novos jogos
iniciados com o token no cabeçalho `X-Sessao-Jogo` aparecem em **Partidas recentes**.
O SQLite guarda o hash do token. A API também deriva do token o perfil de
treino retornado em `usuario`. O campo de entrada `usuario` de versões
anteriores está obsoleto. Jogos criados sem o cabeçalho continuam acessíveis
pelo ID. Limpar o armazenamento do navegador remove o token e o acesso à sua lista.
Após um reinício, o estado confirmado continua disponível. Se o processo
cair no meio de um turno, a reserva expira em até 60 s, permitindo reenviar
a jogada sobre o estado confirmado.

## Exemplo HTTP

Com os serviços ativos, `jq` e `openssl` disponíveis:

```bash
lance_api=http://127.0.0.1:8000
sessao_jogo=$(openssl rand -hex 32)
jogo_id=$(curl -fsS "$lance_api/api/jogo/iniciar" \
  -H 'Content-Type: application/json' -H "X-Sessao-Jogo: $sessao_jogo" \
  -d '{"cor_do_jogador":"white","dificuldade":"intermediario","modo_treinador":false}' | jq -er '.id')

curl -fsS "$lance_api/api/jogo/$jogo_id/mover" \
  -H 'Content-Type: application/json' -d '{"lance":"e2e4","versao":0}' \
  | jq '{versao, fen, lances: [.lances[] | {san, autor, classe: .avaliacao.classe}]}'

curl -fsS "$lance_api/api/jogo/$jogo_id/mover" \
  -H 'Content-Type: application/json' -d '{"lance":"g1f3","versao":1}' \
  | jq '{versao, fen, lances: [.lances[] | {san, autor, classe: .avaliacao.classe}]}'

curl -fsS "$lance_api/api/jogo/$jogo_id/desistir" \
  -H 'Content-Type: application/json' -d '{"versao":2}' \
  | jq '{resultado, motivo, partida_analise_id}'

curl -fsS "$lance_api/api/jogo/$jogo_id/resultado" | jq -r '.pgn'
curl -fsS "$lance_api/api/jogo/partidas" -H "X-Sessao-Jogo: $sessao_jogo" | jq '.partidas'
```

Em um ensaio HTTP com Stockfish 15.1 e o Ollama inacessível, uma partida de
nível Intermediário retornou `1. e4 Nf6 2. Nf3 Nxe4 0-1` após a desistência.
O sistema classificou `e4` como aceitável e `Nf3` como imprecisão, com perda
estimada de 10,64 pontos percentuais e `e5` como melhor alternativa. A revisão
concluiu com os mesmos índices e avaliações dos lances do jogador. Os lances
do adversário podem variar entre execuções.
