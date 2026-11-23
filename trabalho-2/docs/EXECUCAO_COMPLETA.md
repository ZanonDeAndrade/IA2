# Executar e apresentar o Lance a Lance

## Obter o projeto

Use Docker com Compose v2.17 ou superior. Em um novo checkout, a branch `main`
contém as três partes do projeto. Use a árvore com as correções desta entrega
para repetir os testes registrados neste guia. O ensaio foi feito na árvore
local de trabalho com essas correções. A branch remota foi conferida com
`git ls-remote`, e os pesos já estavam disponíveis na máquina.

```bash
git clone --branch main https://github.com/ZanonDeAndrade/IA2.git
cd IA2/trabalho-2
cp -n .env.example .env
```

Na pasta `trabalho-2`, preencha `CHESSCOM_USER_AGENT` no `.env` com o nome do
aplicativo e um contato real da equipe. O ensaio usou o endereço público do
repositório como contato. A importação por PGN aceita o texto da partida mesmo
sem acesso ao Chess.com.

## Habilitar Ollama local

Se o Ollama já estiver disponível, confira o modelo com `ollama list`. Prepare
`qwen3:1.7b` uma vez com `ollama pull qwen3:1.7b`, caso ainda não o tenha. O
ensaio reutilizou o modelo 1.7B Q4_K_M já baixado, no Ollama 0.40.16. Configure
estes campos no `.env` para usar a geração local na interface:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:1.7b
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_TEMPERATURA=0
LLM_RACIOCINIO=none
LLM_MAX_TOKENS=384
LLM_TIMEOUT=60
LLM_JSON_MODE=1
```

Use a porta em que o Ollama estiver acessível a partir do contêiner. O nome
`host.docker.internal` resolve o host a partir da rede do Compose. Depois de
subir o backend, confirme a conexão e o modelo desde o contêiner:

```bash
docker compose exec -T backend python -c 'import json,os,urllib.request; url=os.environ["LLM_BASE_URL"]; print([m["id"] for m in json.load(urllib.request.urlopen(url+"/models",timeout=5))["data"]])'
```

### Ollama e Docker no Linux

Se o Ollama escuta apenas no loopback, o contêiner Linux precisa de um
endereço acessível na bridge Docker. O ensaio iniciou o Ollama diretamente
nesse endereço, com o modelo já presente. Em outro terminal, rode:

```bash
gateway=$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')
OLLAMA_HOST="$gateway:11436" OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=6144 \
  OLLAMA_NUM_PARALLEL=1 LLAMA_ARG_CACHE_RAM=512 ollama serve
```

No `.env`, use `LLM_BASE_URL=http://host.docker.internal:11436/v1`. O ensaio
também usou `OLLAMA_IGPU_ENABLE=1` para usar a GPU integrada Intel com Vulkan.
Mantenha o servidor aberto durante a demonstração. Com `LLM_MODEL` vazio, a
análise usa Stockfish, as novas explicações exibem o apoio do motor e o chat
indica indisponibilidade.

## Subir e abrir o sistema

Em outro terminal na pasta `trabalho-2`:

```bash
docker compose up --build -d --wait
docker compose ps
curl -fsS http://127.0.0.1:5173/healthz
```

| Serviço | Endereço |
| --- | --- |
| Aplicação web | `http://127.0.0.1:5173` |
| FastAPI e Swagger | `http://127.0.0.1:8000/docs` |
| MCP dentro do Compose | `http://mcp_server:8001/mcp` |

O Nginx atende a interface e encaminha `/api` e `/healthz` ao backend na mesma
origem. A API aguarda o MCP e o MCP prepara o recorte de puzzles e as 30 fichas
no primeiro início. Os três serviços têm health checks. Na configuração padrão,
os pesos do modelo de embeddings são baixados no primeiro início. Use
`HF_HUB_OFFLINE=1` somente se os pesos já estiverem no volume `modelos`.

Para usar outras portas, defina `FRONTEND_PORT` e `BACKEND_PORT` no `.env` ou
no ambiente do comando. O ensaio usou **18752** para a interface e **18753**
para a API porque as portas padrão já estavam ocupadas. No Vite, use
`VITE_API_PROXY_TARGET=http://127.0.0.1:18753 npm run dev` na pasta `frontend`
para apontar o proxy de desenvolvimento para essa API. O Playwright aceita
`LANCE_E2E_BASE_URL` para testar um serviço já em execução.

## Demonstrar em até sete minutos

A amostra é a partida pública **kopano2019 × Stonewall_BoyRivers**, com 81
meios-lances e o erro `31...Rd2` usado no piloto `lichess:00ldC`. O PGN incluído
permite importar a partida sem depender da rede. [PGN para colar](../data/demos/xdFXCpYF.pgn) ·
[Partida na Lichess](https://lichess.org/game/xdFXCpYF)

| Tempo | Ação |
| --- | --- |
| 0:00–1:00 | Abra a tela inicial. Mostre usuário, quantidade, ritmo e opção de PGN. Para importar ao vivo pelo Chess.com, busque `hikaru`, escolha **1 partida** e ritmo **Blitz**. |
| 1:00–2:00 | Em **Colar PGN**, use o arquivo acima, o identificador `Stonewall_BoyRivers` e **Pretas**. Importe, entre na análise e acione **Analisar partida** quando necessário. |
| 2:00–3:20 | Navegue com os controles e clique no gráfico. A lista abre o contexto antes do lance e o gráfico usa a posição depois do mesmo índice. As avaliações são das brancas. Os traços verticais indicam mate. |
| 3:20–4:30 | Selecione `31...Rd2` marcado como erro grave. Use **Explicar este lance** e mostre alternativa, tema, ficha e validação. |
| 4:30–5:30 | Pergunte ao chat **Por que esse movimento foi ruim?** Em seguida, use **Depois do lance** e pergunte sobre a torre preta em d2. A mudança de FEN inicia uma nova conversa. |
| 5:30–6:30 | Clique em **Ver meu progresso**. Confira o tema classificado, a partida e os puzzles. Mostre o rating e o link para a Lichess. |
| 6:30–7:00 | Apresente a comparação A/B/C e as pendências acadêmicas. Abra o protocolo se houver perguntas sobre a amostra. |

Antes de apresentar, faça a importação e a explicação uma vez. SQLite guarda a
partida, os resultados do motor e a explicação validada. Em um retorno ao mesmo
volume, a partida de demonstração tem o endereço previsível
`/#/analise/22adcf954fc8fbbe7041a7a9` com os dados acima. O endereço só funciona
após importar a partida. Informe na apresentação quando a explicação aparece
do cache. Se a internet falhar, use o PGN, a análise salva e o **Explorar puzzle**
do relatório. Os links externos da Lichess dependem de rede. Se o Ollama falhar,
mantenha o mesmo perfil de `.env`, abra a explicação validada previamente e
mostre o status de indisponibilidade do chat. A rota **Demonstração offline**
oferece um exemplo didático independente. [Evidências do ensaio real](verificacao-integracao.md)

## Repetir testes e encerrar

Com o serviço já em execução e os comandos na raiz de `trabalho-2`:

```bash
cd frontend
npm ci
npm run build
LANCE_E2E_BASE_URL=http://127.0.0.1:5173 npm test -- tests/app.spec.js
LANCE_E2E_BASE_URL=http://127.0.0.1:5173 LANCE_E2E_REAL=1 npm run test:real
cd ..
docker compose restart
docker compose ps
```

O Playwright precisa de Chromium. `npx playwright install chromium` prepara o
navegador exigido pelo pacote. Se houver Chromium compatível já instalado, use
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` com o caminho do executável. O ensaio usou
essa opção para reutilizar o Chromium disponível. `LANCE_E2E_SEM_LLM=1` permite
executar o cenário de disponibilidade com a configuração sem provedor.

Para testar o Python no ambiente local, com dependências e Stockfish instalados:

```bash
STOCKFISH_PATH=/caminho/do/stockfish LANCE_TESTE_EMBEDDINGS=1 LANCE_TESTE_MCP_RAG=1 python -m pytest -q
```

Encerre os serviços com `docker compose down` no mesmo projeto. O comando
preserva os volumes de SQLite, Chroma e modelos. Encerre também o processo do
Ollama em seu terminal quando tiver sido iniciado para o ensaio. O encerramento
do Compose foi conferido com `--dry-run`, e a instância da demonstração ficou
ativa. O guia foi verificado no Linux com os pesos de embeddings já disponíveis. Os scripts
PowerShell oferecidos pela equipe permanecem descritos no README do frontend.
