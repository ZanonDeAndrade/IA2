# Verificação da integração real

Ensaio de 22/11/2026 em Linux, na árvore local de `trabalho-2`. O Compose 5.3.1
subiu o frontend Nginx, a API FastAPI e o MCP com Stockfish 15.1. As explicações
e o chat usaram Ollama 0.40.16 e Qwen3 1.7B Q4_K_M. O índice ChromaDB foi
preparado com as 30 fichas do projeto e os pesos MiniLM multilíngue já
disponíveis. Foram usados os volumes nomeados do Compose. O primeiro download
dos pesos em uma máquina sem cache ficou fora do ensaio.

## Resultados

| Verificação | Resultado |
| --- | --- |
| `pytest -q -ra`, com Stockfish, embeddings e MCP reais habilitados | 132 aprovados, 0 falhas, 0 ignorados |
| Build e lint do frontend | Aprovados. O Vite emitiu aviso de tamanho do bundle |
| Contratos Playwright | 16 aprovados, em desktop e celular com respostas controladas |
| Playwright com API real | 3 aprovados, com Chess.com, PGN, Stockfish, explicação, chat, relatório e validação de PGN |
| Endpoints HTTP | As sete rotas do contrato foram exercitadas. Usuário, partida e tarefa ausentes retornaram 404. FEN, PGN e lance inválidos retornaram 422 |
| Layout no Chromium | 1440 × 900, 1280 × 800, 768 × 1024 e 390 × 844. Relatório e análise dentro da largura da janela |
| Console e rede no fluxo de sucesso | Zero erros registrados pelo Playwright. O cenário de entrada inválida recebeu o HTTP 422 esperado |
| Reinício do Compose | O ID da tarefa, a análise com 81 meios-lances, a explicação validada em cache e o relatório foram preservados |
| API sem LLM configurado | A explicação devolveu apoio do motor validado. O chat retornou `indisponivel` em uma instância com banco separado |

O ensaio com API real usou o projeto `lance-final-verificacao` em portas
livres da máquina. A interface ficou em `http://127.0.0.1:18752`, a API e
o Swagger ficaram em `http://127.0.0.1:18753` e `/docs`. O MCP respondeu
internamente em `http://mcp_server:8001/mcp`. O Vite foi verificado com
`VITE_API_PROXY_TARGET=http://127.0.0.1:18753` em outra porta local. Um toque
no gráfico, com emulação móvel, mudou o FEN sem erro de console.

A primeira execução simultânea de inferência, navegador e testes Python
registrou um timeout na busca RAG via stdio. A repetição da suíte completa
com o modelo de geração descarregado aprovou o mesmo teste com embeddings
habilitados. No Compose, o MCP carregou os embeddings antes de ficar saudável.

## Requisitos funcionais

| RF | Evidência |
| --- | --- |
| RF01 | A busca por `hikaru` importou uma partida Blitz da API pública do Chess.com e abriu a revisão |
| RF02 | O navegador colou e importou o PGN público da partida `xdFXCpYF`. Um PGN inválido manteve o campo preenchido e exibiu a mensagem da API |
| RF03 | O motor analisou 81 meios-lances. A barra de progresso avançou até 100% |
| RF04 | A lista abriu o FEN anterior a `31...Rd2`. O próximo lance mostrou a torre em `d2`. Os controles voltaram ao início e alcançaram o último FEN |
| RF05 | Qwen3 explicou `Rd2` em português, sem fallback. Stockfish forneceu `Rd7` e o validador confirmou os lances publicados |
| RF06 | Seis perguntas passaram com geração real. O chat descreveu a posição, identificou uma ameaça, recomendou `Rd7` e explicou o erro e o tema. O FEN mudou ao alternar para depois de `Rd2` |
| RF07 | O relatório de `Stonewall_BoyRivers` mostrou 1 partida, 3 imprecisões, 0 erros, 2 erros graves, 1 ocorrência de Desvio e 1 erro sem tema |
| RF08 | O relatório retornou cinco puzzles para o tema Desvio, com ratings do recorte. A API pública da Lichess confirmou os cinco IDs e o tema `deflection` |
| RF09 | O fluxo usou `knowledge_base/desvio.md`. A interface mostrou a ficha Desvio e o status de validação |
| RF10 | O gráfico trouxe 82 pontos na perspectiva das brancas. O clique em um ponto atualizou o tabuleiro. Os valores de mate mantiveram representação própria |
| RF11 | A repetição reutilizou o ID da tarefa. A explicação retornou `cache:true`. A seleção do lance persistiu no navegador ao recarregar |

A posição do erro corresponde à entrada `lichess:00ldC`. O grafo priorizou
**Desvio** na variante analisada. O rótulo primário da amostra experimental
é **Garfo**, e a divergência já está descrita na auditoria temática.
[Partida pública da Lichess](https://lichess.org/game/xdFXCpYF) ·
[Auditoria da versão C](../evaluation/QUALIDADE.md)

## Medições

| Medição local | Tempo |
| --- | ---: |
| Análise de 80 meios-lances por HTTP, Stockfish 15.1 profundidade 12 | 4,565 s |
| Repetição da tarefa com análise em cache | 0,002 s |
| Análise de 81 meios-lances da demonstração pelo navegador, incluindo polling | 12,59 s |
| Geração da explicação `31...Rd2` no último ensaio | 14,60 s |
| `DOMContentLoaded` da tela inicial no último ensaio | 95 ms |

O benchmark usou os primeiros 80 meios-lances de uma partida pública
do Chess.com sem tarefa prévia nesse SQLite. O tempo da explicação inclui as
ferramentas MCP, a geração e a validação. A meta de 60 s corresponde à etapa
determinística da análise. [Partida do benchmark](https://www.chess.com/game/live/189600953117)

## Correções da integração

| Gravidade | Problema observado | Correção |
| --- | --- | --- |
| Alta | Após abrir a posição anterior pela lista, avançar podia saltar uma posição e voltar podia repetir o FEN | Controles e teclado calculam o índice a partir da posição efetivamente exibida |
| Alta | Chat tinha somente o FEN para interpretar “esse movimento” e podia escolher uma descrição de turno para uma pergunta sobre ameaças | Referência validada ao lance persistido, consulta à variante da consequência e opções factuais específicas para a pergunta |
| Alta | Uma variante de apoio no chat podia parecer um resultado gerado | O contrato inclui `fallback` e a interface identifica o apoio do motor |
| Média | A tabela do relatório ampliava a grade a 409 px num celular de 390 px | A grade encolhe com a tela e a tabela pode rolar internamente |
| Média | Espera longa nas rotas curtas, erros críticos pouco visíveis no gráfico e ausência de motivo para recomendações vazias | Prazos por rota, indicadores para os erros e mensagens para temas ou faixas sem puzzles |

O link de treino abriu o endereço correto em outra aba. A página externa
apresentou o desafio do Cloudflare ao Chromium automatizado. Os cinco
destinos foram confirmados via API pública, e o treino local do relatório
abriu a posição e permitiu revelar a primeira jogada com os dados do recorte.
O rating publicado ao vivo pode variar em relação ao snapshot local.

## Demonstração e avaliação acadêmica

O PGN e a explicação real ficaram em cache no volume da demonstração. O guia
reúne o roteiro de sete minutos, o uso do Ollama e a contingência usando o
PGN e a explicação salvos. [Guia de execução](EXECUCAO_COMPLETA.md)

[Início](img/integracao-real/inicio.png) ·
[Análise](img/integracao-real/analise.png) ·
[Análise no celular](img/integracao-real/analise-celular.png) ·
[Ficha RAG e validação](img/integracao-real/ficha.png) ·
[Relatório](img/integracao-real/relatorio.png) ·
[Respostas e medições em JSON](img/integracao-real/evidencias.json)

A avaliação acadêmica continua com 70/100 posições. Faltam 30 jogadas de
partidas da equipe ou de colegas com rótulo humano, as notas cegas dos três
avaliadores e o SUS com cinco participantes. O acerto de tema de 73,33% foi
medido na validação interna reservada. A fidelidade RAGAS de 0,28125 com a
ficha isolada e de 0,50 com ficha e tabuleiro ficou abaixo da meta de 0,80.
[Protocolo de avaliação](../evaluation/README.md) ·
[Limites da avaliação de qualidade](../evaluation/QUALIDADE.md)
