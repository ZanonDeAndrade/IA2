# Frontend: Assistente Inteligente de Receitas

React 19, TypeScript (strict) e Vite 8. Testes com Vitest e Testing Library. Cobre os prompts 29 a 33
(estrutura, tela única, cards, integração HTTP e estados).

> **Visual provisório.** `src/styles.css` só garante legibilidade, foco visível e layout mobile-first.
> A identidade visual (cores, tipografia, componentes do design "Chef IA") ainda **não** foi aplicada: falta o
> código ou as capturas do design de referência.

## Executar

```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL (padrão http://localhost:8000)
npm run dev                 # http://localhost:5173
```

O backend precisa estar no ar (`backend/README.md`, seção "API HTTP") e liberar a origem do frontend em
`CORS_ORIGINS`. O padrão já cobre `localhost:5173` e `127.0.0.1:5173`.

| Script | O que faz |
|---|---|
| `npm run dev` | servidor de desenvolvimento (porta 5173) |
| `npm run build` | `tsc --noEmit` + build de produção em `dist/` |
| `npm run preview` | serve `dist/` (porta 4173; inclua `http://localhost:4173` em `CORS_ORIGINS`) |
| `npm run typecheck` | só a checagem de tipos |
| `npm test` | testes unitários e de componentes (Vitest + jsdom) |

## Estrutura

```
src/
  types/api.ts             contrato HTTP (espelho de backend/app/schemas/query.py) e limites
  services/api.ts          única camada HTTP: postConsultation, ApiError tipado, URL base por env
  hooks/useConsultation.ts estados idle/validating/loading/success/empty/blocked/error (+ retrying),
                           validação local, AbortController (troca de consulta, desmontagem, 330 s)
  components/
    ConsultationForm.tsx   formulário (ingredientes + pergunta + "Buscar receitas")
    IngredientInput.tsx    chips: vírgula/Enter/colar lista, Backspace remove o último, botão remover
    QuestionInput.tsx      textarea com contador
    ResultList.tsx         resposta (texto puro), cards e "Fontes consultadas"
    RecipeCard.tsx         compatibilidade, Tenho/Faltam, ingredientes, "Ver preparo" (só se recuperado), fonte
    SourceLink.tsx         link http(s) com target=_blank e rel="noopener noreferrer"; outras referências viram texto
    StatusNotice.tsx       avisos de estado (role=status/alert) com ação opcional
  test/                    setup do Vitest e dados SINTÉTICOS só para testes
```

## Mapeamento de estados

| Resposta do backend | Estado | Tela |
|---|---|---|
| `FOUND` (200) | `success` | resposta, cards e fontes |
| `INSUFFICIENT` (200) | `empty` | aviso com a resposta e "Editar consulta"; nenhum card |
| `BLOCKED` (422) | `blocked` | mensagem do guardrail e "Editar consulta" |
| `ERROR` (502/503/504/500) | `error` | mensagem do backend, `request_id` e "Tentar novamente" |
| rede/tempo/formato inesperado | `error` | mensagem local e "Tentar novamente" |

O `status` do corpo vale mais que o código HTTP. O texto do LLM é renderizado como texto (React escapa), nunca
como HTML. Nada é salvo no navegador.

## Testes

`npm test` simula `fetch` **apenas** nos testes unitários (dados `[TESTE]` em `src/test/factories.ts`). A
aplicação não tem dados simulados. A integração real foi verificada com o backend em execução (uvicorn + MCP
stdio real) e Chromium headless: consulta → 503 `LLM_UNAVAILABLE` (Ollama desligado) e injeção → 422 `BLOCKED`.

## Pendências e dependências

- **Design visual:** aguardando o código ou as capturas do artifact de referência.
- **Pergunta obrigatória:** a documentação descreve a pergunta como opcional, mas o contrato exige
  `question` (3..500). O formulário segue o contrato e pede a pergunta.
- **Receitas reais na tela** dependem de Ollama com `qwen3:4b` e da integração do corpus PDF com o servidor
  MCP (pendente; hoje `list_topics` informa `corpus_ready=false`).
- **Sugestões/substituições** não fazem parte do contrato (`RecipeCard` não tem esse campo). Não foram
  implementadas.
