# Trabalho 1 – Portal de Notas com teste de segurança DAST (OWASP ZAP)

Aplicação web mínima em **FastAPI** usada como alvo de uma varredura dinâmica de
segurança (DAST). A cada push na `main` que altere esta pasta, o workflow
[`.github/workflows/dast.yml`](../.github/workflows/dast.yml) sobe a aplicação,
executa o **OWASP ZAP** (`zap-full-scan.py`) contra ela via Docker e publica o
relatório HTML como artefato da execução.

## O que o `main.py` faz

- **Middleware de cabeçalhos de segurança**: toda resposta recebe cabeçalhos de
  proteção contra cache (`Cache-Control`, `Pragma`, `Expires`), anti-clickjacking
  (`X-Frame-Options: DENY`), anti-MIME-sniffing (`X-Content-Type-Options: nosniff`),
  `Content-Security-Policy`, `Permissions-Policy` e as políticas cross-origin
  (`COEP`, `COOP`, `CORP`). Essas correções respondem aos alertas apontados no
  relatório do ZAP.
- **Banco SQLite** (`universidade.db`): na inicialização, cria a tabela `alunos`
  (`id`, `nome`, `nota`, `segredo`), limpa os dados e insere um registro de exemplo.
- **`GET /`**: página HTML "Portal de Notas" com um formulário de busca por nome de
  aluno. Aceita o parâmetro opcional `busca`, exibido na página.
- **`GET /buscar?aluno=<nome>`**: consulta a tabela `alunos` pelo nome e devolve um
  JSON com `nome` e `nota`. A resposta não expõe a query executada nem o stack
  trace do banco em caso de erro (retorna uma mensagem genérica).

> Observação: a consulta em `/buscar` ainda é montada por interpolação de string.
> Esse é um dos pontos observados nas varreduras DAST.

## Como executar

Requisitos: Python 3.10+.

```bash
cd trabalho-1
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000
```

Acesse `http://localhost:8000/` no navegador ou teste a busca:

```bash
curl "http://localhost:8000/buscar?aluno=Ana"
```

O arquivo `universidade.db` é criado automaticamente na pasta de execução e está
no `.gitignore`.

## Rodar a varredura DAST localmente (opcional)

Com a aplicação no ar e o Docker instalado:

```bash
touch report_html.html && chmod a+w report_html.html
docker run -v "$(pwd)":/zap/wrk/:rw --network=host -t ghcr.io/zaproxy/zaproxy:stable \
  zap-full-scan.py -t http://localhost:8000 -r report_html.html
```

O relatório fica em `report_html.html`.
