# Assistente Inteligente de Receitas · RAG

O RAG usa os PDFs da pasta [data/raw/](data/raw/), embeddings MiniLM multilíngues e um índice ChromaDB local. Cada resultado cita o arquivo e a página física do PDF.

## Adicionar PDFs e gerar embeddings

A partir da raiz do repositório, entre em `trabalho-3/` para executar os comandos desta página. Coloque os PDFs em `trabalho-3/data/raw/`:

```sh
.venv/bin/python -m rag.ingest --offline
```

O comando encontra os PDFs automaticamente, atualiza o manifesto e indexa a versão atual da pasta. Os PDFs e os arquivos gerados ficam na cópia local. Para remover uma fonte da busca, retire o PDF da pasta e execute a ingestão novamente. O índice fica em `data/chroma/`, com as contagens e as páginas sem texto em `data/chroma/report.json`.

### Primeira instalação

Use Python 3.11+ e Poppler. Instale o Poppler com `brew install poppler` no macOS ou `sudo apt install poppler-utils` no Ubuntu. Depois rode:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './rag[test]'
python -m rag.ingest
```

A primeira execução baixa a revisão fixada do modelo. Com o modelo em cache, use `--offline`. Páginas sem camada de texto são registradas e puladas. Um PDF inteiro sem texto extraível precisa passar por OCR antes da ingestão.

## Consultar e validar

```sh
.venv/bin/python -m rag.retrieve 'Como fazer bacalhau ao forno?' --offline
.venv/bin/python -m rag.retrieve 'O que posso fazer com ovos e leite?' --offline
.venv/bin/python -m rag.retrieve --topics --offline
.venv/bin/python -m rag.retrieve --document pdf-d4cc78647a8e0926-p9 --offline
HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -q
```

Para regenerar o relatório com os cinco PDFs da avaliação original, execute `python -m rag.evaluate --offline --output tests/evidence/rag-evaluation.json` no ambiente virtual. Para outro corpus, passe um gabarito atualizado com `--cases`.

A busca retorna trechos e as páginas correspondentes. Uma receita distribuída em várias páginas pode ter seus trechos retornados separadamente. Quando você informa ingredientes, o RAG mostra os nomes encontrados no texto da página. Para abrir a página inteira no terminal, passe o `recipe_id` retornado pela busca como argumento de `--document`.

[Corpus e manifesto](docs/04-rag/corpus.md) · [Pipeline](docs/04-rag/pipeline.md) · [Estado da implementação](IMPLEMENTATION_STATUS.md)

## Integração com MCP

O RAG está disponível pela CLI e pela classe `Retriever`. O adaptador MCP existente espera uma função `retrieve` e registros de receitas estruturadas com URLs HTTP(S). Para consumir este corpus, ele precisa aceitar páginas de PDF e suas referências locais.
