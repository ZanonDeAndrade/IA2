# Avaliação A/B/C

A revisão que usa evidências das variantes tem protocolo e resultados próprios.
[Auditoria de qualidade da versão C](QUALIDADE.md)

## Dataset e protocolo de seleção

O [dataset](dataset.jsonl) reúne 70 posições da base aberta da Lichess. As 30
posições anotadas do grupo ou de colegas estão pendentes. A busca no
repositório, no histórico e no Drive acessível não encontrou PGNs da equipe.
Cada linha contém o FEN anterior ao erro, a jogada realizada em SAN, a melhor
alternativa do Stockfish nesse FEN, o tema, a origem e os dados do motor.

Na [base oficial de puzzles](https://database.lichess.org/#puzzles), o FEN
precede a primeira jogada de `Moves`. Esta jogada foi realizada pelo oponente
na partida de origem. Após aplicá-la, o segundo movimento inicia a solução do
puzzle. O gerador valida toda a trilha UCI com python-chess. Ele só inclui a
primeira jogada como erro se a melhor opção do Stockfish for diferente e a
perda estimada for de pelo menos 20 pontos percentuais. O motor analisa o mesmo
FEN duas vezes, em busca aberta e com a jogada realizada forçada na raiz. As
pontuações usam a perspectiva de quem cometeu o erro. A resposta do puzzle é
guardada para rastreabilidade. A alternativa avaliada pertence ao lado que errou e
é calculada antes do erro.

A seleção usa os primeiros 16.000 registros do snapshot indicado em
[`dataset.meta.json`](dataset.meta.json), com rating de puzzle entre 800 e
2000. Em cada estrato, os candidatos são ordenados pelo SHA-256 de
`semente:tema_lichess:PuzzleId`. Um puzzle multitema entra no primeiro estrato
em que é aceito. Também deduplicamos FENs por posição, turno, roque e en passant.
A amostra tem nove posições por tema para garfo, cravada, espeto, ataque
descoberto, peça pendurada e mate, e oito para desvio e atração. Os temas da
Lichess descrevem a tática que aparece após a jogada e podem admitir mais de
um rótulo. O acerto automático usa o rótulo primário do estrato.

As referências publicadas foram calculadas com [Stockfish 11](https://github.com/official-stockfish/Stockfish/releases/tag/sf_11),
profundidade 16, MultiPV 1, uma thread, hash de 16 MiB e uma nova busca por consulta.
A inicialização UCI tem timeout de 30 s. A busca de referência é limitada por
profundidade, sem `movetime`. As pontuações são da perspectiva do jogador que
executou o lance, inclusive na busca com o movimento forçado.
O arquivo [`lichess_candidatos.jsonl`](lichess_candidatos.jsonl) guarda apenas
as linhas examinadas, suficiente para reexecutar a seleção sem baixar a base
inteira. Com o mesmo Stockfish, na raiz do repositório:

```bash
python -m evaluation.dataset --candidatos evaluation/lichess_candidatos.jsonl \
  --stockfish /caminho/stockfish --saida /tmp/lance-dataset.jsonl
cmp evaluation/dataset.jsonl /tmp/lance-dataset.jsonl
```

O Stockfish 11 disponível localmente reproduziu os 70 registros byte a byte
(`71161d23…`). Seu binário tem SHA-256 `3b190c18…`, diferente do executável
histórico em `dataset.meta.json` (`29a08e68…`). Os metadados históricos foram
preservados. Ao acrescentar PGNs com `--base`, o importador verifica o hash,
a versão do Stockfish e o perfil de busca da referência.

| Motor e busca em `lichess:00ldC` | Primeiro lance e avaliação das pretas |
| --- | --- |
| Stockfish 11, profundidade 16, MultiPV 1 | `Qd4`, +432 cp |
| Stockfish 15.1, profundidade 16, MultiPV 1 | `Rd7`, +363 cp |
| Stockfish 11, profundidade 18, MultiPV 1 | `Qd4`, +430 cp |
| Stockfish 11, profundidade 18, MultiPV 3 | `e5`, +487 cp |
| Stockfish 15.1, profundidade 18, MultiPV 3 | `Rd7`, +373 cp |

O teste fixou uma thread e 16 MiB de hash. Acrescentar o limite de 10 s no
perfil 18/MultiPV 3 não mudou as saídas: ambos os motores terminaram a busca
antes do limite. Nesse FEN, tanto a versão quanto o MultiPV explicam diferenças.
O pré-teste interativo usa a análise ao vivo. B e C usam a mesma variante
congelada no dataset para a avaliação comparativa.

Para selecionar candidatos a partir de outra edição da base, use
`--lichess /caminho/lichess_db_puzzle.csv.zst`, `--limite 16000` e
`--salvar-candidatos /tmp/candidatos.jsonl`. Registre a edição com
`--snapshot-lichess`. Uma edição diferente pode produzir posições diferentes.

### Acrescentar as 30 posições do grupo

Com os PGNs de partidas reais, gere um manifesto de candidatos. A busca percorre
a linha principal do PGN, compara a melhor opção com a jogada da partida no
mesmo FEN e inclui perdas de pelo menos 20 pontos percentuais. Posições já
presentes no dataset versionado ou repetidas no lote são descartadas.

```bash
python -m evaluation.dataset --pgn /caminho/lote1.pgn /caminho/lote2.pgn \
  --stockfish /caminho/stockfish --saida /caminho/candidatas.jsonl
```

Crie `partidas.jsonl` no mesmo diretório do manifesto, com as posições
aprovadas pelo revisor e o rótulo tático preenchido. Sem Stockfish, também é
possível montar o manifesto manualmente e analisá-lo quando houver motor.
O manifesto usa os seguintes campos.

| Campo | Valor |
| --- | --- |
| `pgn` | Arquivo PGN relativo ao manifesto |
| `partida` | Índice da partida dentro do PGN, começando em 1 |
| `meio_lance` | Índice do lance que gerou o erro na linha principal, começando em 1 |
| `id_partida`, `url` | Identificador e referência rastreável da partida |
| `tema_esperado`, `rotulo_por` | Um dos oito temas e identificador do revisor |
| `rating` | Rating documentado do jogador entre 800 e 2000 quando o PGN não informa o valor |
| `pgn_sha256` | Hash opcional preenchido na triagem para detectar alterações no PGN |

Use partidas que possam ser incluídas no trabalho. Mantenha a referência da
partida no campo `url`. Preencha esse campo quando os cabeçalhos `Link` e `Site`
não contiverem uma URL. Use a mesma versão e profundidade do motor das referências publicadas.
A importação reanalisa as posições rotuladas, valida os registros e conserva
os 70 registros originais com `--base`. Confira `por_origem` no arquivo de
metadados e complete a cota com outras partidas se alguma posição for rejeitada.

```bash
python -m evaluation.dataset --base evaluation/dataset.jsonl \
  --partidas /caminho/partidas.jsonl --stockfish /caminho/stockfish \
  --saida /tmp/lance-dataset-com-grupo.jsonl
python -m evaluation.run_eval --dataset /tmp/lance-dataset-com-grupo.jsonl --versoes A B C
```

## Executar

Na raiz, com Python 3.12 recomendado:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Configure LLM_MODEL, LLM_PROVIDER e a credencial do provedor quando exigida.
python -m knowledge_base.index
python -m pytest agent/tests evaluation/tests
python -m evaluation.run_eval
```

### Primeira explicação com ferramentas reais

Use `LLM_PROVIDER=openai` ou `LLM_PROVIDER=ollama` e informe `LLM_MODEL`.
Para OpenAI ou outro endpoint compatível configurado nesse modo, o cliente
lê `LLM_API_KEY` ou `OPENAI_API_KEY` e aceita `LLM_BASE_URL` opcional. Para
Ollama, o endereço padrão é `http://localhost:11434/v1` e o cliente usa
uma credencial local de preenchimento se nenhuma chave tiver sido definida.
O pré-teste pode ser executado com o LLM ainda sem configuração:

```bash
python -m knowledge_base.index --reconstruir
python -m evaluation.primeira_explicacao --id lichess:00ldC
```

O comando usa o FEN e a jogada `Rd2` da posição `lichess:00ldC`. Ele checa a
análise ao vivo via `analisar_posicao`, a descrição antes e depois da jogada,
`validar_lances` e a recuperação de uma ficha real. Se alguma etapa falhar,
devolve o nome da etapa e encerra com código 2. Os endpoints do FastAPI não
participam desse teste. O servidor MCP é acessado via stdio por padrão ou por
`MCP_URL` quando configurado. Configure `STOCKFISH_PATH` no ambiente do servidor
MCP para habilitar a análise UCI. No modo stdio, o cliente também repassa o
valor definido no `.env` do projeto.

Após o pré-teste passar e o provedor ser configurado, autorize a geração para
uma única posição:

```bash
python -m evaluation.primeira_explicacao --id lichess:00ldC --executar
```

### Perfil local usado para Qwen3

Com Ollama e `qwen3:1.7b` já disponíveis, inicie o servidor em loopback.
O ensaio usou Ollama 0.40.16, modelo Q4_K_M com digest `8f68893c685c…`,
contexto 6144 e iGPU Intel via Vulkan. Omita `OLLAMA_IGPU_ENABLE` para executar
em CPU. O prazo maior atende à latência de inferência local. Na execução
longa, o cache de prompts foi limitado a 512 MiB para caber na memória
disponível. O servidor processou uma requisição de cada vez.

```bash
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=6144 \
  OLLAMA_IGPU_ENABLE=1 OLLAMA_NUM_PARALLEL=1 LLAMA_ARG_CACHE_RAM=512 ollama serve
```

Em outro terminal, com o MCP e o índice já disponíveis:

```bash
export LLM_PROVIDER=ollama LLM_MODEL=qwen3:1.7b LLM_BASE_URL=http://127.0.0.1:11435/v1
export LLM_REVISAO=8f68893c685c LLM_RACIOCINIO=none LLM_MAX_TOKENS=384 LLM_TIMEOUT=60 LLM_JSON_MODE=1
export LLM_TEMPERATURA=0
python -m evaluation.primeira_explicacao --id lichess:00ldC --executar
```

O cliente usa Chat Completions. O modo JSON por esquema se aplica à seleção
de tema e às redações estruturadas e fica desativado por padrão para
compatibilidade com outros provedores. O chat usa as chamadas de ferramentas
do grafo. A explicação resume diferenças factuais do tabuleiro e envia só
o conteúdo conceitual da ficha ao modelo e ao juiz.

Nesse perfil, o LangGraph pede ao Stockfish a melhor variante após o erro,
com profundidade 16 e MultiPV 1. A revisão temática confirma `garfo` quando a
peça que dá xeque captura o outro alvo em sua próxima jogada na variante. Um
anúncio positivo de mate pelo Stockfish tem prioridade. O esquema restringe
os dois rótulos a essas evidências. As frases sobre a posição usam fatos
verificáveis e o LLM redige a lição em português. O sistema acrescenta a
melhor alternativa e confere os lances. Garfos sem xeque ou sem captura na
variante principal podem ficar sem esse rótulo no perfil estruturado.

A saída JSON registra as chamadas do pré-teste, as chamadas do agente e, em
caso de sucesso, a ficha usada e a explicação validada. Se a descrição, a ficha
do tema identificado ou o validador ficar indisponível durante o grafo, o piloto
para e registra a ferramenta. Um fallback deixa o piloto incompleto. O piloto
fica fora do checkpoint e das métricas A/B/C.

[Pré-teste local](results/qwen3-local/preflight.json) e
[geração real revisada](results/qwen3-local/piloto-revisado.json) registram o erro `Rd2`, a fonte
`knowledge_base/garfo.md` e a alternativa interativa `e5`. A primeira variante
após `Rd2` contém `Rxg6+ fxg6 Qe7+`. Depois de `Qe7+`, a dama branca dá xeque
e captura a torre preta em f8 na jogada seguinte das brancas. O modelo usou
1.853 tokens de entrada e 113 de saída em duas chamadas. A explicação foi
aprovada na primeira redação. Também foi validado um caso de mate forçado
em `lichess:02ChS`, em que a frase factual usa a sequência indicada pelo
Stockfish e respeita a regra de omitir avaliações numéricas.
[Piloto de mate](results/qwen3-local/piloto-mate.json)

Com a API iniciada sob o mesmo perfil, é possível repetir o caso HTTP:

```bash
fen='3r1r2/pp3pk1/2p1pRp1/6Qp/2P5/P7/1q4PP/5R1K b - - 1 31'
curl -fsS http://127.0.0.1:8000/api/explicar -H 'Content-Type: application/json' \
  -d "{\"fen\":\"$fen\",\"lance_jogado\":\"Rd2\"}"
curl -fsS http://127.0.0.1:8000/api/chat -H 'Content-Type: application/json' \
  -d "{\"fen\":\"$fen\",\"pergunta\":\"Consulte o Stockfish. Qual o melhor lance?\"}"
```

Repita a primeira requisição para verificar `cache:true`. O caso da partida
pública usou 81 meios-lances, gerou quatro explicações armazenadas e retornou
cinco puzzles recomendados. O relatório revisado contou duas ocorrências de
`fork` e duas de `pin`. A triagem PGN também produziu duas candidatas sem
rótulo nessa partida pública, fora do dataset oficial.
[Contratos HTTP](../docs/integracao-frontend.md) ·
[Explicações e relatório revisado](results/qwen3-local/http-revisado.json) · [Chat](results/qwen3-local/chat.json) ·
[MCP, Docker, SQLite e triagem](results/qwen3-local/infra.json)

Para verificar a reconstrução e recuperação real pelo MCP, execute
`LANCE_TESTE_MCP_RAG=1 python -m pytest evaluation/tests/test_primeira_explicacao.py`.
O teste usa o modelo configurado em `EMBEDDING_MODEL` ou o MiniLM multilíngue
padrão e cria o índice em uma pasta temporária.

### Avaliação A/B/C

A invocação sem escopo apenas valida as posições e mostra o plano de execução.
`--limite N` autoriza um piloto com 1 a 10 posições escolhidas pela semente.
`--completa` autoriza todas as posições do dataset selecionado. Cada par
posição/versão corresponde a uma explicação. A e B fazem uma chamada cada. C
pode fazer a classificação do tema e até três tentativas de redação.

Use um modelo que aceite a temperatura configurada e instruções estruturadas em
texto. As três versões usam o mesmo modelo e temperatura (padrão 0), as mesmas
posições e uma ordem de versões por posição fixada pela semente. A versão A
recebe somente FEN e lance como dados da posição. B recebe também a avaliação,
a melhor alternativa e a variante do Stockfish. A e B registram a primeira
resposta. C executa o grafo real com ferramentas MCP, fatos anteriores e
posteriores, RAG, validação, correções e fallback. B e C compartilham a análise
Stockfish registrada no dataset. C precisa de `descrever_posicao` funcional
no MCP, além do índice e de `validar_lances`.

```bash
python -m evaluation.run_eval --versoes A --limite 3 --resultados evaluation/results/execucao-piloto
python -m evaluation.run_eval --versoes A B C --completa
python -m evaluation.run_eval --versoes A B C --completa --repetir-falhas
python -m evaluation.run_eval --somente-relatorio
python -m evaluation.run_eval --somente-relatorio --ragas --limite-ragas 3
```

Para reproduzir o ensaio local em pastas novas e verificar a retomada:

```bash
python -m evaluation.run_eval --versoes A --limite 5 --timeout 150 --resultados /tmp/lance-piloto
python -m evaluation.run_eval --versoes A B C --limite 5 --timeout 150 --resultados /tmp/lance-piloto
RAGAS_MODEL=qwen3:1.7b RAGAS_RACIOCINIO=none RAGAS_DO_NOT_TRACK=true \
  python -m evaluation.run_eval --somente-relatorio --ragas --limite-ragas 3 --timeout 210 \
  --resultados /tmp/lance-piloto
python -m evaluation.run_eval --versoes A B C --completa --timeout 150 --resultados /tmp/lance-70
```

O checkpoint mantém cada tentativa em JSONL. Para retomar, use a mesma pasta,
mesmo conjunto de posições e mesmas configurações. `--repetir-falhas` tenta
também os casos incompletos. Use uma pasta de resultados por processo. Se uma
versão não passar na verificação de disponibilidade, o executor gera o
relatório e sinaliza o bloqueio com código de saída 2.
`--somente-relatorio` reutiliza as posições e a semente guardadas no checkpoint.
Registre `--precos ENTRADA SAIDA` em USD por milhão
de tokens com a tabela de preços do provedor utilizada na data do experimento.
Sem preço ou com contadores parciais do provedor, o custo fica vazio. Para
reproduzir o piloto local de cinco posições, use `--limite 5 --timeout 150`.
Use uma pasta separada para o conjunto completo com `--completa`.

Para o juiz [RAGAS Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/),
configure `RAGAS_MODEL` e, se for outro endpoint, `RAGAS_BASE_URL` e
`RAGAS_API_KEY`. Para o mesmo Qwen3 local, use `RAGAS_RACIOCINIO=none`
e um prazo adequado à geração estruturada, como `--timeout 210`.
Um juiz que usa a mesma família do explicador mede fidelidade automática
com dependência do modelo e deve ser interpretado com essa limitação.
O juiz recebe o texto final e o trecho efetivamente entregue
ao agente. A métrica não se aplica a A/B e fica sem valor em C quando a resposta
foi produzida pelo fallback ou sem ficha. O arquivo `ragas_config.json`
registra a versão da biblioteca, o modelo, a temperatura, o endpoint e o
timeout. O tempo e custo do juiz não entram no tempo e custo do explicador.
`--ragas` seleciona até três respostas pendentes por padrão. Ajuste o piloto
com `--limite-ragas` ou autorize toda a fila com `--ragas-completo`.

O teste de CLI em `evaluation/tests/test_cli.py` usa duas posições reais e
respostas de fixture para verificar A, B, C e a retomada. Seus arquivos ficam
em uma pasta temporária e suas medições não entram no relatório experimental.

## Resultados do piloto de cinco posições

O piloto local gerou 15 explicações completas com Qwen3 `qwen3:1.7b`. A primeira
execução registrou cinco respostas de A. A retomada preservou essas cinco
linhas e acrescentou as dez de B e C. As três versões compartilharam modelo,
temperatura e conjunto de posições. [Relatório do piloto](results/qwen3-piloto-5/relatorio.md) ·
[CSV](results/qwen3-piloto-5/metricas.csv) · [Gráfico](results/qwen3-piloto-5/comparacao.png)

| Versão | Explicações | Com lance ilegal | Melhor lance | Tema | Tempo médio | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 5/5 | 80% | 0% | 60% | 11,86 s | 2.038 |
| B | 5/5 | 80% | 100% | 0% | 10,68 s | 2.366 |
| C | 5/5 | 0% | 100% | 20% | 11,15 s | 9.922 |

RAGAS 0.4.3 obteve fidelidade média **0,25** em três explicações de C, com
o próprio Qwen3 como juiz. Cada uma teve nota 0,25. O juiz recebeu a ficha
recuperada como contexto. Assim, fatos de tabuleiro confirmados separadamente
pelo MCP podem aparecer como sem suporte nessa métrica. A taxa de acerto do
tema ficou abaixo da meta no piloto. Os tokens incluem a classificação
temática de C. A inferência local não gerou cobrança de provedor e o campo
de custo em USD ficou vazio. As notas dos três avaliadores ainda estão
pendentes. [Amostra cega](results/qwen3-piloto-5/amostra_cega.csv) ·
[Formulário](results/qwen3-piloto-5/formulario_humano.csv)

## Rodada principal em 70 posições

Foram concluídas as **210 tentativas** e **208 explicações completas**. A teve
uma resposta sem todos os campos exigidos. C usou um fallback após três
tentativas de redação em uma posição. Cada incompleta fica visível no relatório
e fora dos denominadores de legalidade, melhor lance e tema.
[Relatório](results/qwen3-70/relatorio.md) · [CSV](results/qwen3-70/metricas.csv) ·
[Gráfico](results/qwen3-70/comparacao.png)

| Versão | Explicações | Com lance ilegal | Melhor lance | Tema | Tempo médio | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 69/70 | 71,01% | 0% | 14,49% | 9,27 s | 27.364 |
| B | 70/70 | 21,43% | 100% | 12,86% | 10,34 s | 33.257 |
| C | 69/70 | 0% | 100% | 11,59% | 12,86 s | 168.295 |

O melhor lance em B e C mede a aderência à referência do motor entregue às
duas versões. C escolheu `garfo` nas 69 respostas completas, inclusive em 41
casos em que a heurística do ensaio não encontrou o motivo. O resultado levou
à revisão do esquema e das evidências para o rótulo. O checkpoint original
mantém as respostas e o SHA-256 do código usado. Para reproduzir esse perfil
histórico, reverta o [patch da revisão temática](results/qwen3-70/revisao-tematica.patch)
em uma cópia dos arquivos antes de executar o protocolo. Se a cópia já incluir
a revisão de qualidade posterior, reverta primeiro o
[patch de qualidade](results/qualidade/revisao-agente.patch).

A fidelidade RAGAS **0,175** foi medida nas primeiras dez posições elegíveis
pela ordem de ID. O Qwen3 foi usado como juiz sob temperatura 0 e timeout de
210 s. A amostra usa o trecho RAG entregue ao agente como única fonte da nota.
[Configuração do juiz](results/qwen3-70/ragas_config.json)

A avaliação cega tem 90 respostas de 30 posições pareadas. Cada um dos três
avaliadores recebe 90 campos de nota. As notas ainda estão pendentes.
[Amostra cega](results/qwen3-70/amostra_cega.csv) ·
[Formulário](results/qwen3-70/formulario_humano.csv)

### Reexecução de C após a revisão temática

A primeira reexecução expôs um conflito entre o fato numérico sobre mate e
a regra de redação do grafo. Ela foi interrompida com 48 registros, que
ficaram disponíveis para auditoria. A redação factual final preserva a
sequência forçada de mate sem indicar sua distância, e foi validada em um
piloto com Stockfish e LLM reais. [Diagnóstico intermediário](results/qwen3-c-revisada/relatorio.md) ·
[Piloto de mate](results/qwen3-local/piloto-mate.json)

O perfil final de C gerou **70/70 explicações completas, sem fallback**.
Teve **0% de lances ilegais**, **100% de acerto da melhor alternativa** e
**28,57% de acerto do tema**. O tempo médio foi 11,71 s e o consumo foi de
154.014 tokens. O rótulo mais frequente foi `cravada` em 31 respostas, seguido
de `mate` em 14. A meta temática de 60% segue pendente. Esta reexecução usa
as mesmas posições da rodada principal. Seus resultados medem a revisão
nesse conjunto conhecido. A amostra cega da seção anterior pertence à rodada
A/B/C original. [Relatório da revisão final](results/qwen3-c-final/relatorio.md) ·
[CSV](results/qwen3-c-final/metricas.csv) · [Gráfico](results/qwen3-c-final/comparacao.png)

RAGAS obteve **0,25** nas primeiras três respostas elegíveis da revisão pela
ordem de ID. A cobertura é menor que a da rodada principal. A amostra mede
fidelidade à ficha recuperada e usa Qwen3 como juiz, com a mesma configuração
do ensaio original. [Configuração do juiz](results/qwen3-c-final/ragas_config.json)

```bash
python -m evaluation.run_eval --versoes C --completa --timeout 150 --resultados /tmp/lance-c-final
RAGAS_MODEL=qwen3:1.7b RAGAS_RACIOCINIO=none RAGAS_DO_NOT_TRACK=true \
  python -m evaluation.run_eval --somente-relatorio --ragas --limite-ragas 3 --timeout 210 \
  --resultados /tmp/lance-c-final
```

## Relatórios e avaliação humana

`por_posicao.csv` inclui texto, referência, citações verificadas, status,
tempo, uso e erros. `metricas.csv`, `comparacao.png` e `relatorio.md` mostram
cobertura, resultados agregados e até três exemplos pareados. Na falta de
observações, os valores ficam vazios. As porcentagens usam somente respostas
completas como denominador. Incompletas e fallbacks aparecem nas contagens
de cobertura e os rascunhos continuam auditáveis. Os totais de tokens e
custo incluem tentativas incompletas quando o provedor informa todos os
contadores. As falhas sem explicação são contabilizadas separadamente.
Variantes explícitas são verificadas em posições sucessivas. Uma citação
legal diferente da recomendação de referência é desacerto, mas não é ilegal.

O relatório compara apenas posições com as três respostas completas. A amostra
humana seleciona 30 dessas posições, uma mesma posição para cada tríade, e
embaralha as respostas com códigos opacos. Distribua `amostra_cega.csv` e o
formulário para três avaliadores, mantendo `gabarito_privado.csv` com a equipe.
O texto original pode conter pistas da versão, como a menção ao Stockfish.

Cada avaliador atribui uma nota inteira de 1 a 5, usando juntos clareza,
correção e valor didático. Nota 1 equivale a uma resposta incorreta ou
inutilizável, 3 a uma resposta compreensível mas incompleta, e 5 a uma
explicação correta, clara e com uma orientação aplicável. As notas 2 e 4
representam níveis intermediários. Salve uma cópia preenchida do formulário
e agregue com `--somente-relatorio --avaliacoes-humanas /caminho/notas.csv`.

O desenho permite comparar B e A sobre o benefício de informar a análise
do motor. A comparação C versus B envolve mudanças simultâneas de ferramenta,
RAG, redação e validação. Uma futura ablação de C com e sem RAG seria necessária
para estimar o efeito causal do RAG. A taxa final de C deve ser lida junto aos
rascunhos rejeitados, aos fallbacks e à taxa de respostas incompletas.
