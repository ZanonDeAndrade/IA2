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

O Vite encaminha `/api` e `/healthz` para a API. Para outro servidor, use `VITE_API_URL` no `.env.local` desta pasta e autorize a origem em `CORS_ORIGENS` no backend. Chaves de IA ficam apenas no backend.

## Docker

Na raiz de `trabalho-2`, execute `docker compose up --build`. O serviço `frontend` compila com Node e serve pelo Nginx em `http://127.0.0.1:5173`. O proxy acessa `backend:8000`. A porta pode mudar por `FRONTEND_PORT` no `.env` da raiz. O transporte usa a mesma origem, sem expor configuração de IA ao navegador.

## Navegação

- `/#/`: importação e lista de partidas deste navegador.
- `/#/analise/<id>`: revisão da partida persistida na API.
- `/#/relatorio/<usuario>`: temas, evolução e puzzles.
- `/#/demo/analise/demo` e `/#/demo/relatorio`: exemplos didáticos offline, identificados na tela.

Os botões de lance, os controles do tabuleiro e as setas esquerda/direita navegam pela partida. O painel do erro abre a posição **antes** do lance para desenhar corretamente as setas. É possível alternar para **depois**. O chat sempre recebe o FEN exibido e reinicia ao mudar de posição. Mensagens anteriores não contaminam o histórico de outra posição.

A análise consulta a tarefa a cada dois segundos, permite explorar resultados parciais e apresenta erros da tarefa mesmo quando o HTTP retorna 200. A explicação é solicitada sob demanda. Textos com `validada:false` não aparecem como orientação ao jogador. `fallback:true` recebe indicação de explicação de apoio. No relatório, erros sem tema e recomendações gerais ficam identificados.

## Dados salvos e modo offline

O backend usa SQLite. O navegador guarda a lista de partidas e o último resultado consultado, separados pela URL da API. Se uma consulta falhar, mostra o dado salvo com aviso e desabilita novas chamadas de chat/explicação nessa revisão. A demonstração usa dados locais separados e não simula importação, inferência ou medições reais.

O modo offline exige que a interface esteja servida localmente ou já aberta. Não há service worker nem promessa de carregar uma página remota nova sem conexão. As fontes e as peças são distribuídas junto do build.

## Testes

```sh
npx playwright install chromium
npm test -- tests/app.spec.js
npm run build
```

Os 12 cenários executados cobrem desktop/celular, contratos HTTP simulados, demo, importação, polling, falha do motor, validação, FEN do chat, cache offline, relatório vazio e puzzles indisponíveis. Para testar a API local com Stockfish/MCP reais e sem LLM configurado:

```powershell
$env:LANCE_E2E_REAL='1'
npm run test:real
```

O teste real importa uma partida sintética de quatro meios-lances, processa com o motor, pede explicação validada, confirma indisponibilidade do chat sem LLM e consulta puzzles. O teste de contrato da interface não comprova inferência com um modelo real.

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
