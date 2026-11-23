# Treinador inteligente em tempo real

O modo **Jogar contra IA** junta três papéis com responsabilidades separadas:

| Papel | Quem executa | O que faz | Onde está |
| --- | --- | --- | --- |
| Stockfish adversário | `jogar_stockfish` no MCP | Escolhe a resposta da IA com limites de força por dificuldade | `mcp_server/tools/jogo.py`, `backend/jogo/servico.py` (`jogar_ia`) |
| Stockfish avaliador | `analisar_partida` e `analisar_posicao` no MCP | Avalia o lance do jogador, calcula a perda de chance, a classe, a melhor alternativa e a variante. Também alimenta as dicas | `backend/jogo/servico.py` (`avaliar`), `backend/jogo/treinador.py` (dicas) |
| Qwen3 treinador | LangGraph com RAG e validador | Explica, comenta e responde perguntas usando só as evidências do motor, das regras e das fichas | `agent/graph.py` (reutilizado), `agent/treinador.py`, `backend/jogo/treinador.py` |

O LLM não escolhe lances, não valida jogadas e não inventa posições. Cada jogada
citada passa pelo validador (`validar_lances` e a variante do Stockfish) antes
de chegar ao jogador.

## Fluxo de um lance

1. O jogador move. `POST /api/jogo/{id}/mover` aplica o lance, chama o avaliador
   e o adversário e confirma o turno no SQLite. A **classificação volta nesta
   resposta**, antes de qualquer explicação.
2. A transação que confirma o turno salva também a tarefa de explicação
   quando prevista pelo modo de assistência. O turno espera apenas o Stockfish.
3. Um único trabalhador assíncrono (`FilaTreinador`) consome a fila persistida
   em `explicacoes_jogo`, verifica se o Ollama responde e executa o agente.
4. A interface consulta `GET /api/jogo/{id}/treinador` a cada 2 s, apenas
   enquanto houver tarefa pendente.

Cada tarefa guarda o vínculo completo: ID da partida, ID e índice do lance,
FEN anterior e posterior, jogada, melhor alternativa, classe, perda de chance e
versão da partida. Antes de gerar, o trabalhador confere que o lance gravado
ainda tem o mesmo ID e os mesmos FENs. A interface só exibe uma explicação se o
`lance_id` e os dois FENs coincidirem com o lance mostrado. Uma resposta
atrasada fica associada ao lance de origem e aparece em **Explicações
anteriores**. Nunca aparece no lance atual.

### Prioridade, cancelamento e retentativas

- Ordem: pedidos manuais, depois erro grave, erro, imprecisão e comentários.
  Dentro da mesma classe, o lance mais recente vem primeiro.
- Comentários automáticos de lances aceitáveis são descartados como
  `ignorada` quando o jogador já fez dois lances depois deles. Explicações de
  erros nunca são descartadas.
- O prazo de 150 s por tarefa inclui as ferramentas e a espera pela vaga do
  modelo. Ao excedê-lo, o sistema tenta publicar o apoio determinístico. Falhas
  transitórias têm até duas tentativas. O jogador pode repetir tarefas com estado `erro`.
- `POST /api/jogo/{id}/explicacoes/{indice}/cancelar` cancela uma tarefa
  pendente ou em andamento. Um resultado que chegue depois do cancelamento é
  descartado.
- Uma geração interrompida por reinício volta para a fila na próxima
  inicialização da API.
- O semáforo `fila_llm`, compartilhado com o modo de análise, limita as
  gerações simultâneas. O motor tem fila própria no MCP. O turno repete a
  chamada ao motor até duas vezes se ela coincidir com uma consulta do
  treinador.

### Cache e persistência

As explicações validadas do Qwen3 ficam no SQLite. Um novo pedido para o mesmo
lance devolve o registro salvo. Só `{"forcar": true}` gera outra versão. As
explicações de erros reaproveitam o cache do agente (`explicacoes`), com perfil
que inclui a análise exibida e a orientação de linguagem. Os comentários de
bons lances também incluem os prompts de `agent/prompts/treinador/` na assinatura.

## Modos de assistência

| Modo | Classificação | Explicações automáticas | Ajuda manual |
| --- | --- | --- | --- |
| Livre | Sim, se “Avaliar meus lances automaticamente” estiver ligado | Nenhuma | Explicação, dicas e chat sob pedido |
| Treinador | Sempre | Imprecisões, erros e erros graves | Também para lances aceitáveis |
| Aprendizado intensivo | Sempre | Todos os lances. Bons lances recebem um comentário | Opção de ocultar a melhor alternativa até o clique |

O modo pode ser trocado durante a partida em **Assistência**
(`POST /api/jogo/{id}/configuracoes`). No modo intensivo, o mesmo painel permite
alterar a exibição da melhor alternativa. A troca usa a mesma reserva de versão do
turno e vale a partir do próximo lance. No modo intensivo, lances sem fato
pedagógico além da avaliação, como um lance de peão lateral sem efeito, e
posições repetidas ficam como `ignorada`, com a explicação do motivo. Assim não
há geração desnecessária. Se o jogador quiser, pode pedir o comentário.

## Explicações

A dificuldade escolhida dá ao Qwen3 uma referência para o vocabulário e a
escolha da lição. Ela só indica a preferência para esta partida. Os campos
verificados continuam sujeitos ao mesmo validador.

- **Imprecisão, erro e erro grave**: reutilizam o grafo de explicação existente
  (`explicar_erro_async` via `services.explicacao`). O grafo recupera fatos com
  `descrever_posicao`, procura o motivo tático na variante do Stockfish, busca
  a ficha do tema no RAG, gera os três campos e valida o texto. Depois
  acrescenta a melhor alternativa confirmada. Se não houver evidência de tema,
  usa `outro`, sem forçar um rótulo.
- **Bom lance**: `agent/treinador.py` calcula fatos verificáveis com
  `python-chess`: roque, desenvolvimento, controle do centro, captura com
  ganho, xeque, fuga de ataque, promoção e mate. O Qwen3 escolhe o fato mais
  útil e uma lição da ficha do tema (roque, promoção, mate). Sem tema
  específico, a lição é geral e também passa pelo validador. A coincidência com
  o primeiro lance do motor é informada, mas sozinha não dispara geração.

## Dicas em etapas

`POST /api/jogo/{id}/dica` com `{"versao": n, "nivel": 1 | 2 | 3}`:

1. **Objetivo**: xeque a resolver, mate disponível, tema tático com evidência
   forte na variante (força ≥ 85, até o segundo meio-lance), peça própria
   ameaçada, material a ganhar, desenvolvimento ou plano. Inclui a situação
   (favorável, equilibrada ou difícil) e, havendo tema, a ficha do RAG.
2. **Onde olhar**: a peça e a casa do lance sugerido ou a peça ameaçada.
3. **Lance do Stockfish**: só nesta etapa, depois de uma confirmação na
   interface. O texto passa pelo validador.

As etapas são sequenciais e ficam registradas por versão da partida. Depois de
um lance, a posição muda e as dicas recomeçam. Abra **Histórico de dicas** para
rever o texto, a etapa e a ficha consultada nas posições anteriores. As dicas usam o
Stockfish e as regras, sem texto gerado pelo LLM. A opção “Mostrar sempre o
melhor lance” continua disponível na configuração para quem a escolher.

## Chat durante a partida

`POST /api/jogo/{id}/chat` recebe `pergunta`, `versao`, `historico`, `indice`
opcional e `posicao` (`atual` por padrão ou `apos_lance` com um lance do jogador).
Escolha **Posição da pergunta** para revisar um lance específico. O servidor
obtém o FEN da partida salva e retorna `409` para uma versão desatualizada.
Cada resposta devolve FEN, versão, índice e lance. A interface confere essas
referências e mostra a posição da pergunta em cada resposta.

| Tipo de pergunta | Fonte | Exemplo |
| --- | --- | --- |
| Histórico da partida, verificado pelo validador | `historico` | “Qual foi meu maior erro até agora?”, “Qual é a melhor alternativa?”, “Por que perdi material?” |
| Regras do xadrez | `regras` | “Minha dama está ameaçada?”, “Como posso desenvolver melhor minhas peças?” |
| Stockfish | `motor` | “Estou em uma posição favorável?” (avaliação na cor do jogador) e “Existe alguma oportunidade tática?” (diagnóstico da dica, sem revelar o lance) |
| Conceito com RAG e Qwen3 | `qwen3` ou `ficha` | “O que significa cravada?” |
| Demais perguntas | `qwen3` | Grafo de chat existente com `descrever_posicao`, `analisar_posicao` e `buscar_conceitos`, com o lance selecionado como contexto |

## Sem Ollama

O treinador consulta `{LLM_BASE_URL}/models` com prazo de 3 s, com cache de
10 s. Se o modelo não responder:

- a partida, o adversário, a classificação, as dicas e o histórico continuam;
- as explicações viram mensagens limitadas aos dados do Stockfish, com
  `fonte: "motor"` e a etiqueta “Apoio do Stockfish · sem IA generativa”;
- o painel mostra “Treinador indisponível”;
- perguntas abertas no chat recebem o status `indisponivel`, e as respostas de
  histórico e regras continuam.

## Relatório da partida

`GET /api/jogo/{id}/relatorio` usa somente dados gravados: resultado, lances,
classes, precisão, lances críticos com o estado da explicação, temas
confirmados por explicações validadas do Qwen3, evolução por terços dos seus
lances, dicas usadas por etapa, contagem de explicações por fonte,
recomendações derivadas dessas evidências e puzzles da base local pelos temas
e pela faixa da dificuldade. Sem tema confirmado, o relatório não atribui
dificuldade: informa os lances com erro ainda sem tema e oferece puzzles gerais.

Ao terminar, a API inicia a análise completa da partida (`partida_analise_id`)
pelo mesmo cache de posições. A interface permite revisar cada lance crítico
com sua explicação, abrir a análise e consultar os puzzles.

## Meu progresso e identificação

O navegador guarda um token aleatório de 32 bytes e o envia no cabeçalho
`X-Sessao-Jogo`. O servidor usa o hash do token na lista **Partidas recentes** e
deriva um identificador `treino-…` para **Meu progresso**. O nome informado na
importação do Chess.com ou de PGN é um filtro de consulta. A identidade de treino
pertence ao navegador que conserva o token. Pessoas que compartilham o mesmo
perfil do navegador compartilham a mesma sessão. Partidas de API sem token
podem ser revistas pelo ID. Seus resultados ficam fora dos perfis de progresso.

Cada treino concluído com lances gera uma única partida de revisão. O relatório
geral reaproveita essa análise e, quando disponível, os temas validados pelo
treinador. A regra de identificação se aplica a partidas novas. Os registros
anteriores continuam disponíveis pelos IDs e perfis já gravados.

## Desempenho medido

Medição com `python -m data.scripts.benchmark_treinador`, Compose com
Stockfish 15.1 e Qwen3 1.7B Q4_K_M no Ollama 0.40.16, CPU local, 3 partidas,
24 lances sorteados e 6 explicações geradas sem cache. O cache de posições
do Stockfish estava ativo.

| Etapa | Média | Mediana | Máximo |
| --- | ---: | ---: | ---: |
| Turno completo no cliente | 443 ms | 393 ms | 883 ms |
| Adversário, Iniciante | 41 ms | 41 ms | 48 ms |
| Adversário, Intermediário | 79 ms | 82 ms | 109 ms |
| Adversário, Avançado | 472 ms | 491 ms | 579 ms |
| Avaliação do lance | 224 ms | 230 ms | 363 ms |
| Explicação do Qwen3, fora do turno | 8,35 s | 8,40 s | 8,78 s |

Nos testes E2E, explicações e conceitos levaram de 8 a 33 s. O tempo do Qwen3
não entra no turno: a explicação chega depois da classificação. Os tempos de
avaliação e adversário ficam em `lances[].tempos`, as durações das explicações
na fila, e os agregados em `GET /api/treinador/metricas`.

## API do treinador

| Método e rota | Uso |
| --- | --- |
| `POST /api/jogo/iniciar` | Cria a partida e, quando recebe `X-Sessao-Jogo`, devolve o perfil de treino em `usuario` |
| `GET /api/jogo/{id}/treinador` | Estado do modelo, explicações vinculadas a cada lance, dicas por versão e fila |
| `POST /api/jogo/{id}/explicacoes/{indice}` | Pede a explicação de um lance seu (`202`). `{"forcar": true}` gera de novo |
| `POST /api/jogo/{id}/explicacoes/{indice}/cancelar` | Cancela a tarefa |
| `POST /api/jogo/{id}/dica` | Dica em etapas para a versão atual |
| `POST /api/jogo/{id}/chat` | Pergunta sobre a posição confirmada ou o histórico |
| `POST /api/jogo/{id}/configuracoes` | Troca o modo de assistência e as preferências |
| `GET /api/jogo/{id}/relatorio` | Relatório da partida |
| `GET /api/treinador/status` | Verifica o provedor do LLM agora |
| `GET /api/treinador/metricas` | Tempos agregados de adversário, avaliação, explicação e dicas |

Estados de uma explicação: `pendente`, `em_andamento`, `concluida`,
`cancelada`, `ignorada` e `erro`. Em `resultado.fonte`, `qwen3` indica texto do
modelo validado e `motor` indica apoio determinístico do Stockfish.

## Testes

```bash
# Unidade e integração HTTP do treinador. O motor é controlado, a fila e o SQLite são reais.
python -m pytest -q agent/tests/test_treinador.py backend/tests/test_treinador.py
# Comentário real do Qwen3 (requer o .env com Ollama)
LANCE_TESTE_LLM_REAL=1 python -m pytest -q agent/tests/test_treinador.py -k llm_real
# Navegador real contra o Compose com Ollama, sem mocks HTTP
cd frontend
LANCE_E2E_BASE_URL=http://127.0.0.1:5173 LANCE_E2E_TREINADOR=1 npx playwright test tests/treinador-real.spec.js
# Cenário sem Ollama, numa pilha com LLM_BASE_URL inacessível
LANCE_E2E_BASE_URL=http://127.0.0.1:5173 LANCE_E2E_TREINADOR=1 \
  LANCE_E2E_SEM_LLM_URL=http://127.0.0.1:5174 npx playwright test tests/treinador-real.spec.js -g "sem Ollama"
```

O E2E percorre os 20 passos do roteiro de brancas no desktop e de pretas no
celular. O roteiro abre o sistema, configura, inicia, move, recebe a resposta
do Stockfish e a classificação, recebe a explicação do Qwen3 de um erro
verificável e joga outro lance antes de ela chegar. Depois confere o vínculo, pede
dicas, pergunta ao chat, recarrega, encerra, abre o relatório e a análise e
compara PGN e lances.
[Resultados da verificação](verificacao-treinador.md)

As versões A, B e C do experimento e seus checkpoints não foram alterados. Os
prompts do treinador ficam em `agent/prompts/treinador/`, fora da assinatura
`perfil_explicacao` e da impressão digital de `evaluation/run_eval.py`, que
leem apenas `agent/prompts/*.md`.
