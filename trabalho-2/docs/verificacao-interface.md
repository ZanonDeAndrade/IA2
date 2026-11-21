# Verificação da interface e integração

Verificação local em 21/11/2026, no Windows, com Node.js 22.23.2, Python 3.11 e Stockfish 19 oficial. O frontend usa React 19.3.1, Vite 8.3.8, react-chessboard 5.10.0 e chess.js 1.4.0. As versões do frontend estão fixadas em `package.json` e `package-lock.json`.

## Resultados

| Verificação | Resultado |
| --- | --- |
| Build de produção (`npm run build`) | Aprovado |
| Testes de interface/contrato em desktop e celular | 12 aprovados |
| Fluxo no navegador com API, Stockfish e MCP reais | 1 aprovado |
| Backend, ferramentas MCP e agente (`pytest backend/tests mcp_server/tests agent/tests -q`) | 102 aprovados, 3 ignorados |
| Exemplos JSON contra os seis modelos Pydantic da API | Aprovados |
| Sintaxe dos scripts PowerShell e leitura do YAML Compose | Aprovadas |
| Inicialização via `iniciar.ps1` e encaminhamento de `/healthz` pelo frontend | Aprovados |
| Capturas das três telas, modo claro e celular | Inspeção visual concluída |
| Layout do início em celular no modo claro | Sem transbordamento horizontal |
| Cálculo do formulário SUS com resposta de teste | 100 para itens positivos 5 e negativos 1; contexto temporário descartado |

O teste real usou uma partida sintética de quatro meios-lances, importada pelo HTTP. A análise e a explicação de apoio usaram Stockfish/MCP/validador reais. O chat retornou indisponibilidade porque nenhum modelo de IA foi configurado. O relatório devolveu puzzles da base local. Os testes de contrato usam respostas controladas para cobrir os demais estados da interface.

Os três testes ignorados dependem de embeddings ou RAG real opcionais. Não há validação de inferência com LLM real neste computador. A suíte acadêmica completa de avaliação A/B/C não foi executada como parte da implementação da interface.

## Ajuste do backend

A ferramenta `buscar_conceitos` verifica se existe um índice antes de carregar ChromaDB. Isso evita o timeout da primeira consulta no perfil sem RAG. A regressão verifica a consulta sem `site-packages`, assegurando que a ausência do índice não exija a instalação de Chroma.

## Limites e pendências

- Docker não está disponível neste computador: o Compose e a configuração do proxy foram preparados, mas não executados.
- A importação real do Chess.com depende do contato em `CHESSCOM_USER_AGENT` e não foi exercitada externamente nesta verificação. O contrato e a integração HTTP da interface foram testados.
- O SUS com cinco pessoas, o vídeo real e os ensaios ainda precisam acontecer. O teste automático do formulário não entra nos resultados de usabilidade.
- O build emite aviso sobre o tamanho do bundle JavaScript principal, aproximadamente 700 kB sem compressão. Isso não impediu a compilação nem os testes locais.

Consulte `pendencias-milton.md` para a sequência de fechamento.
