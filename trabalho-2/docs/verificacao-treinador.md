# Verificação do treinador em tempo real

Ensaio em Linux, em 23/11/2026, com o código final do treinador.

## Ambiente

- Docker Compose com Stockfish 15.1, Python 3.12, FastMCP via Streamable HTTP,
  SQLite, ChromaDB e as 30 fichas indexadas com MiniLM multilíngue.
- Ollama 0.40.16 com `qwen3:1.7b` Q4_K_M no endereço da bridge Docker, perfil
  `LLM_RACIOCINIO=none`, `LLM_MAX_TOKENS=384`, `LLM_TIMEOUT=60` e `LLM_JSON_MODE=1`.
- Uma segunda pilha com as mesmas imagens e `LLM_BASE_URL` apontando para uma
  porta fechada, para o cenário sem Ollama.
- Chromium 159 pelo Playwright 1.56, em desktop 1440×1000 e em emulação de iPhone 13.

## Resultados

| Suíte | Resultado |
| --- | --- |
| `python -m pytest` com Stockfish, embeddings e RAG reais | 177 aprovados e 1 teste opcional do LLM, executado à parte |
| `agent/tests/test_treinador.py -k llm_real` com Qwen3 real | 1 aprovado |
| Playwright de contratos (`app.spec.js`, `play.spec.js`) | 35 aprovados e 1 ignorado de propósito (o arraste é verificado só no desktop) |
| `treinador-real.spec.js`, brancas no desktop e pretas no celular | 2 aprovados |
| `treinador-real.spec.js`, sem Ollama | 1 aprovado |
| `play-real-api.spec.js` e `jogo-real.spec.js` (modo de jogo) | 8 aprovados |
| `real-api.spec.js` com LLM, desktop e celular | 6 aprovados |
| `real-api.spec.js` com Ollama inacessível, desktop | 3 aprovados |
| `oxlint` e `vite build` | Lint aprovado e build concluído. O Vite sinalizou o tamanho do bundle JS de 760 kB (229 kB gzip) |
| Reinício do backend no Compose | Estado, 7 lances, 1 explicação do Qwen3 e 2 dicas idênticos antes e depois |
| HTTP real | Chat confirmou a versão e o FEN histórico. A terceira dica revelou um lance legal após duas etapas sem revelação |

Os testes de backend do treinador cobrem: explicação de bom lance, imprecisão,
erro e erro grave; seleção temática sem forçar ficha; recuperação RAG;
referência do lance (ID e FENs); validação dos lances citados; respostas
atrasadas; lances consecutivos com prioridade; mudança de FEN em dicas e chat;
chat contextual; dicas em etapas; modelo indisponível e fallback; cache e
pedido explícito de nova geração; cancelamento; persistência com reinício;
relatório e integração com Meu progresso. Também cobrem a exclusão de
repetições com contadores diferentes no FEN e a reversão do turno se a
gravação da tarefa falhar antes do commit.

## Cenário E2E

Nos dois cenários com Qwen3, o roteiro de 20 passos foi percorrido no
navegador com HTTP real. Para acionar a explicação automática do modo
Treinador, o segundo lance do jogador deixa uma peça ao alcance de um peão
adversário.

| Cenário | Erro jogado | Classe | Explicação | Tempo da explicação | Tema e ficha |
| --- | --- | --- | --- | ---: | --- |
| Brancas, desktop | `Ba6` | erro grave | Qwen3 validada | 9,4 s | Peça pendurada |
| Pretas, celular | `Qg5` | erro grave | Qwen3 validada | 7,6 s | Peça pendurada |

Texto publicado no cenário de brancas:

> O lance da partida deslocou um bispo das brancas. Na variante, a resposta
> imediata captura o bispo com ganho na troca dessa casa. Antes de confirmar o
> lance, veja o que a peça movida defendia e o que ficará atacado. O Stockfish
> indicou `Nf3` como alternativa e, na linha analisada, a resposta imediata do
> adversário vem sem captura ou xeque.

Nos dois cenários, o jogador fez outro lance antes de a explicação ficar
pronta. Ela apareceu apenas em **Explicações anteriores**, presa ao `lance_id` e
aos FENs do erro. O roteiro consultou a ficha de cravada e avaliou a posição após
o lance selecionado. A explicação das pretas apontou que a resposta imediata na
variante capturava a dama e indicou `Nf6` como alternativa. O chat confirmou o
mesmo motivo após `Qg5` via MCP em 3,6 s, com o FEN da posição após o lance.
O relatório apontou o tema peça pendurada, um erro grave, as dicas usadas e
três puzzles. O PGN e os lances da análise coincidiram com os da partida.

Sem Ollama, a explicação do erro veio com `fonte: "motor"` e a etiqueta de
apoio do Stockfish. O chat aberto respondeu como indisponível e as respostas
de histórico, as dicas e o relatório continuaram funcionando.

## Desempenho

Medido com `python -m data.scripts.benchmark_treinador` no Compose, com 3
partidas, 24 lances sorteados (`--semente 23`) e 6 explicações geradas sem cache.
O cache de posições do Stockfish estava ativo.

| Etapa | Média | Mediana | Máximo |
| --- | ---: | ---: | ---: |
| Turno completo visto pelo cliente | 443 ms | 393 ms | 883 ms |
| Adversário Iniciante / Intermediário / Avançado | 41 / 79 / 472 ms | 41 / 82 / 491 ms | 48 / 109 / 579 ms |
| Avaliação do lance do jogador | 224 ms | 230 ms | 363 ms |
| Explicação do Qwen3, fora do turno | 8,35 s | 8,40 s | 8,78 s |

Em uma rodada anterior na mesma máquina, houve turnos de 0,9 s a 1,7 s
enquanto o modelo e o Stockfish disputavam a CPU. O jogador pôde continuar
movendo enquanto o modelo gerava a explicação.

## Limitações observadas

- O texto das explicações de erros vem do grafo existente. Quando a variante
  não confirma um tema, ele usa a ficha “outro” e frases gerais. As frases são
  corretas, mas pouco específicas.
- No modo intensivo, um comentário de lance aceitável leva cerca de 10 a 15 s.
  Se o jogador fizer dois lances nesse intervalo, o comentário é descartado e
  pode ser pedido depois.
- A resposta conceitual do Qwen3 1.7B é validada quanto ao formato, aos lances
  e aos números, mas não quanto à precisão de cada afirmação sobre o conceito.
  Ela é identificada como texto do modelo, com a ficha usada.
- Perguntas abertas no chat dependem do grafo de chat existente. Numa
  execução, “Existe alguma oportunidade tática?” recebeu uma resposta vaga. Por
  isso essa pergunta e a de desenvolvimento passaram a usar o diagnóstico do
  Stockfish e as regras.
- Na primeira execução do E2E de brancas, uma verificação do painel do
  treinador falhou em 2 ms, sem erro de página registrado. Ela não se repetiu
  nas nove execuções seguintes do E2E (seis de brancas e três de pretas). A
  causa não foi identificada.
- O cenário sem Ollama foi testado com a porta do provedor fechada. Um host
  que aceite conexão e não responda depende do prazo `LLM_TIMEOUT` no grafo.
- Duas verificações do fluxo de análise falharam no celular porque exigiam
  visibilidade do indicador de conexão da barra lateral, oculto nesse layout.
  A suíte passou no celular após verificar HTTP 200 em `/healthz` e o estado
  do indicador, mantendo a verificação de visibilidade no desktop.
