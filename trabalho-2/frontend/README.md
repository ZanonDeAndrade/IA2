# Interface do Lance a Lance

Aplicativo React + Vite integrado ao FastAPI. A interface oferece importação por Chess.com/PGN, tabuleiro navegável, avaliação clicável, explicações validadas, chat por posição e relatório com puzzles.

## Visual de vidro

O tema em `src/glass.css` usa superfícies translúcidas, `backdrop-filter`, bordas
suaves e cores compartilhadas em `src/index.css`. A navegação, os painéis e os
diálogos recebem o efeito; o tabuleiro preserva suas cores opacas. Os modos
claro e escuro incluem uma versão sólida para navegadores sem suporte a blur
e para a preferência de acessibilidade `prefers-reduced-transparency`.

O pacote [expo-glass-effect](https://docs.expo.dev/versions/latest/sdk/glass-effect/)
renderiza vidro nativo do iOS e usa uma View comum em plataformas sem suporte.
Este aplicativo é web, por isso usa o equivalente em CSS e não depende do Expo.

## Executar no Windows

Na pasta `trabalho-2`:

```powershell
.\preparar.ps1
.\iniciar.ps1
```

O preparo cria o ambiente Python, instala o perfil mínimo da API, baixa Stockfish 19 do repositório oficial, prepara 73 puzzles e instala/compila o frontend. O aplicativo abre em `http://127.0.0.1:5173`. O terminal de inicialização mantém os serviços ativos e Ctrl+C encerra os processos iniciados por ele. Configurações existentes no `.env` são preservadas.

Para IA com a base de conceitos, execute `./preparar.ps1 -ComRag`, configure o modelo autorizado no `.env` e reinicie. O perfil mínimo funciona com análise real e explicação de apoio validada, sem chat de IA. O contato real em `CHESSCOM_USER_AGENT` habilita a importação pública. A importação por PGN funciona sem esse contato.

## Desenvolvimento manual

Com a API em `http://127.0.0.1:8000`, nesta pasta:

```sh
npm ci
npm run dev
```

O Vite encaminha `/api` e `/healthz` para a API. Defina `VITE_API_PROXY_TARGET`
no `.env.local` desta pasta para alterar o destino do proxy. Se optar por
`VITE_API_URL` diretamente no navegador, autorize a origem em `CORS_ORIGENS`
no backend. Chaves de IA ficam apenas no backend.

## Docker

Na raiz de `trabalho-2`, execute `docker compose up --build`. O serviço `frontend` compila com Node e serve pelo Nginx em `http://127.0.0.1:5173`. O proxy acessa `backend:8000`. A porta pode mudar por `FRONTEND_PORT` no `.env` da raiz. O transporte usa a mesma origem, sem expor configuração de IA ao navegador.

## Navegação

- `/#/`: importação e lista de partidas deste navegador.
- `/#/analise/<id>`: revisão da partida persistida na API.
- `/#/relatorio/<usuario>`: temas, evolução e puzzles.
- `/#/jogar`: configuração da partida contra o Stockfish. Define a cor, a
  dificuldade, se o treinador está ativo e o modo de assistência (Livre,
  Treinador ou Aprendizado intensivo). A página também abre as partidas
  recentes vinculadas à sessão deste navegador.
- `/#/jogar/<id>`: partida em andamento ou encerrada, com tabuleiro, histórico,
  classificação, treinador, dicas, chat e, no fim, o relatório.
- `/#/demo/analise/demo` e `/#/demo/relatorio`: exemplos didáticos offline, identificados na tela.

Os botões de lance, os controles do tabuleiro e as setas esquerda/direita navegam pela partida. O painel do erro abre a posição **antes** do lance para desenhar corretamente as setas. É possível alternar para **depois**. O chat recebe o FEN exibido e a referência ao lance selecionado. A conversa reinicia quando esse contexto muda.

A análise consulta a tarefa a cada dois segundos, permite explorar resultados parciais e apresenta erros da tarefa mesmo quando o HTTP retorna 200. A explicação é solicitada sob demanda. Textos com `validada:false` não aparecem como orientação ao jogador. `fallback:true` recebe indicação de explicação de apoio. No relatório, erros sem tema e recomendações gerais ficam identificados.

### Componentes do modo de jogo

`src/play/` reúne a página (`PlayPage.jsx`), o tabuleiro jogável
(`GameBoard.jsx`), os painéis de partida, classificação, histórico e resultado
(`GamePanels.jsx`), o treinador (`GameCoach.jsx`), as dicas em etapas
(`GameHints.jsx`), o chat (`GameChat.jsx`) e o relatório (`GameReport.jsx`). O
hook `useCoach` em `coach.js` consulta a fila a cada 2 s apenas quando há
explicação pendente. `belongsTo` só aceita uma explicação cujo `lance_id` e
FENs coincidam com o lance exibido. **Posição da pergunta** permite consultar um
lance anterior e cada resposta de chat identifica a posição usada. O histórico
de dicas exibe as etapas salvas por posição. No desktop, o tabuleiro e o histórico ficam
à esquerda e os painéis de ajuda à direita. No celular, tudo vira uma coluna,
com o tabuleiro primeiro.

`playApi` envia `X-Sessao-Jogo` ao iniciar ou listar partidas recentes. A API
deriva desse token o identificador de progresso do treino. Uma
jogada envia o UCI e a última `versao` confirmada. O tabuleiro usa o `fen`
retornado. Em caso de conflito ou falha de rede, o cliente busca o estado atual
antes de aceitar outra jogada. O botão **Analisar partida** abre
`/#/analise/{partida_analise_id}` ao fim. [Contratos HTTP](../docs/JOGAR_CONTRA_IA.md#api-http)

## Dados salvos e modo offline

O backend usa SQLite. O navegador guarda a lista de partidas e o último resultado consultado, separados pela URL da API. Se uma consulta falhar, mostra o dado salvo com aviso e desabilita novas chamadas de chat/explicação nessa revisão. A demonstração usa dados locais separados e não simula importação, inferência ou medições reais.

O modo offline exige que a interface esteja servida localmente ou já aberta. Não há service worker nem promessa de carregar uma página remota nova sem conexão. As fontes e as peças são distribuídas junto do build.

## Testes

```sh
npx playwright install chromium
npm test -- tests/app.spec.js tests/play.spec.js
npm run build
```

Os testes de contrato cobrem desktop e celular, demo, importação, polling, falha do motor, validação, FEN do chat, cache offline, relatório vazio e puzzles indisponíveis. Com o Compose em execução e o Ollama configurado:

```bash
LANCE_E2E_BASE_URL=http://127.0.0.1:5173 LANCE_E2E_REAL=1 npm run test:real
```

O teste real usa o Chess.com e o PGN público da Lichess para verificar o motor,
as posições do tabuleiro, a geração, a ficha RAG, o chat, os puzzles e os
dados após recarregar a página. Em um ambiente sem modelo, use também
`LANCE_E2E_SEM_LLM=1` para testar o apoio do motor e a mensagem do chat.

O modo de jogo tem `tests/play.spec.js` (contratos simulados), além de
`tests/play-real-api.spec.js` e `tests/jogo-real.spec.js` (API real, com
`LANCE_E2E_JOGO_REAL=1`). O treinador tem `tests/treinador-real.spec.js`
(Compose e Ollama reais, com `LANCE_E2E_TREINADOR=1`). Esse teste joga de
brancas no desktop e de pretas no celular. Com `LANCE_E2E_SEM_LLM_URL`, também
joga numa pilha sem LLM. [Comandos e resultados](../docs/TREINADOR.md#testes)
[Condições e resultados do ensaio](../docs/verificacao-integracao.md)

## Prints e GIF

Com a interface em execução:

```sh
npm run capture
python -m pip install Pillow
python scripts/make-gif.py
```

Os arquivos ficam em `../docs/img/`. As capturas de análise e relatório e o GIF usam o modo didático, com aviso na tela. O GIF não substitui a gravação da demonstração real.

## Fechamento

- [Tarefas restantes do Milton](../docs/pendencias-milton.md)
- [Formulário de registro do SUS](../docs/sus.html)
- [Roteiro do pitch](../docs/roteiro-pitch.md)
- [Contratos e integração HTTP](../docs/integracao-frontend.md)
