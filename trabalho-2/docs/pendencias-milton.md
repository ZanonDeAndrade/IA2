# Tarefas para concluir a entrega do Milton

A interface e sua integração HTTP estão implementadas. Esta lista reúne as ações que dependem de configuração do grupo, participantes reais ou apresentação. Prazo da proposta: 23/11/2026 às 12h, com revisão final em 22/11.

## Antes da demonstração com IA

- [ ] Preencher `CHESSCOM_USER_AGENT` no `.env` com o nome do aplicativo e um contato real. A importação por PGN já funciona sem isso.
- [ ] Confirmar com o grupo o provedor/modelo de IA e preencher `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` e, se necessário, `LLM_BASE_URL` no `.env` local.
- [ ] Para usar explicações com RAG, executar `./preparar.ps1 -ComRag` e conferir a indexação das fichas. Isso baixa dependências e o modelo de embeddings. O perfil local mínimo já executa Stockfish, MCP, análise, explicação de apoio validada e relatório.
- [ ] Reiniciar o aplicativo e conferir uma explicação sem fallback e uma conversa com resposta validada. Os testes de contrato cobrem esse comportamento, mas a inferência com modelo real não foi executada neste computador.
- [ ] Se a apresentação usar Docker, instalar/iniciar Docker Desktop e executar `docker compose up --build`. O frontend e seu proxy já estão incluídos; a execução Docker não foi validada neste ambiente sem Docker.

## Teste com cinco colegas

- [ ] Abrir `docs/sus.html` para o roteiro, registro das dez respostas e cálculo automático.
- [ ] Aplicar as tarefas do roteiro com cinco pessoas, usando identificadores P01 a P05. Registrar celular/notebook e se o teste usou API real ou demo.
- [ ] Aplicar a versão do questionário SUS em português adotada pelo grupo. O formulário de registro aponta para a fonte original e preserva a ordem dos itens.
- [ ] Exportar as respostas reais em JSON e guardar junto aos resultados da equipe. Não publicar nomes nem informações pessoais.
- [ ] Corrigir as dificuldades observadas e incluir no README a média, as cinco notas e os ajustes realizados. Nenhuma nota foi inventada.

## Apresentação

- [ ] Usar o roteiro em `docs/roteiro-pitch.md` para montar os slides finais com o grupo.
- [ ] Confirmar com Zanon os números finais da avaliação A/B/C. Não apresentar as metas da proposta como resultados atingidos.
- [ ] Escolher uma partida real que já esteja pública desde a véspera, com pelo menos um erro grave fácil de explicar.
- [ ] Importar, analisar e abrir as explicações dessa partida no navegador da apresentação. Isso prepara os caches do servidor e do navegador.
- [ ] Conferir chat e relatório com puzzles nessa mesma partida.
- [ ] Gravar um vídeo da demonstração real completa. O GIF em `docs/img/demo.gif` ilustra a interface com dados didáticos e não substitui esse vídeo.
- [ ] Fazer dois ensaios de até sete minutos com todos. Milton apresenta o problema no primeiro minuto e conduz a demonstração entre 2:00 e 5:00.

## Entrega com a equipe

- [ ] Executar o projeto em outra máquina seguindo apenas o README.
- [ ] Revisar as alterações e abrir PR. Manter commits de contribuição real e revisão por outro integrante.
- [ ] Confirmar que `.env`, binário Stockfish, bancos locais, dependências e dados grandes continuam fora do Git.
- [ ] Conferir RF01–RF08, os resultados experimentais e os materiais no README.
- [ ] Entregar o link do repositório antes de 23/11/2026 às 12h.

## Materiais já preparados

- Três telas em português, modos claro/escuro e layout para notebook/celular.
- Cliente de todos os endpoints, importação por usuário/PGN, progresso a cada dois segundos, navegação e setas, gráfico clicável, explicação sob demanda, chat por posição e relatório com puzzles.
- Estados de erro/vazio/carregamento, prevenção de respostas antigas ao mudar de posição e ocultação de explicações não validadas.
- Consulta do último estado salvo no navegador, com indicação de cache e demonstração offline separada dos dados reais.
- Dockerfile/Nginx e serviço de frontend no Compose.
- Scripts de preparação e inicialização no Windows.
- Prints, GIF didático, formulário de registro SUS e roteiro de pitch.
- Testes automatizados em desktop/celular e fluxo HTTP real com Stockfish/MCP.
