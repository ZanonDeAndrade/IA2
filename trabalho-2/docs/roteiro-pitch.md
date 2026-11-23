# Roteiro do pitch do Lance a Lance

Apresentação de sete minutos. Milton apresenta o problema e conduz o aplicativo; Marcelo explica a arquitetura; Zanon narra a demonstração e apresenta os resultados. A demonstração principal deve usar a API e o modelo reais. A rota `/#/demo/analise/demo` é uma alternativa didática explicitamente identificada.

## 0:00 a 1:00 — Problema, Milton

Slide sugerido: **Entender o erro no xadrez**.

“Quando um motor mostra uma avaliação e recomenda um lance, o jogador ainda precisa entender por que errou. O Lance a Lance usa as partidas do próprio jogador para mostrar a posição, explicar a mudança e sugerir o que treinar.”

Mostrar uma posição real escolhida pelo grupo. Comparar a informação do motor com a explicação em português, sem atribuir ao exemplo didático uma inferência que não ocorreu.

## 1:00 a 2:00 — Solução e arquitetura, Marcelo

Slide sugerido: **Como a explicação chega ao jogador**.

A interface React envia solicitações ao FastAPI. O agente consulta o Stockfish e as regras pelo MCP. O RAG recupera fichas táticas e o validador verifica os lances antes da exibição. As análises e explicações completas validadas ficam no SQLite.

“O motor fornece avaliações e alternativas. A IA transforma esses fatos em explicações. A interface permite conferir cada posição.”

## 2:00 a 5:00 — Demonstração, Milton conduz e Zanon narra

| Tempo | Ação na interface | Ponto a explicar |
| --- | --- | --- |
| 2:00–2:30 | Importar a partida de um colega | Chess.com público ou PGN, com a cor correta |
| 2:30–3:00 | Abrir a análise e acompanhar progresso | O processamento acontece em segundo plano |
| 3:00–3:50 | Selecionar erro grave, alternar antes/depois e abrir explicação | Seta vermelha para lance jogado e verde para alternativa; tema e fonte quando disponíveis |
| 3:50–4:25 | Perguntar ao chat sobre essa posição | A pergunta leva o FEN atual e as ferramentas ficam visíveis |
| 4:25–5:00 | Abrir progresso e um puzzle | O treino acompanha temas identificados nas explicações |

Preparar a análise e as explicações antes da apresentação. Testar o caminho exato com o identificador do jogador da demo. Se o serviço estiver indisponível, informar o uso de cache ou do vídeo de reserva.

## 5:00 a 6:15 — Resultados, Zanon

Slide sugerido: **Avaliação das explicações**.

Usar o relatório real em `evaluation/results/qwen3-70/relatorio.md`, revisado pelo responsável. Explicar o conjunto efetivo de 70 posições, as três versões comparadas e as limitações. As 30 posições adicionais e a avaliação cega devem aparecer como pendências se ainda não foram concluídas. Não substituir resultados baixos pelas metas da proposta.

Incluir o resultado do SUS somente depois de aplicar aos cinco colegas. Os testes automatizados da interface verificam funcionamento e não substituem o teste de usabilidade com pessoas.

## 6:15 a 7:00 — Impacto e próximos passos, Marcelo

Slide sugerido: **Próximos passos do treinador**.

Retomar a utilidade para o jogador que quer entender os próprios erros. Citar comentário ao vivo, voz e leitura de tabuleiro por imagem como evolução futura. Concluir com o link do repositório e os nomes dos integrantes.

## Material de reserva

- Partida real analisada e explicações abertas no navegador da apresentação.
- Vídeo da demonstração real completa, gravado na véspera.
- Prints em `docs/img/` e GIF da interface para ilustrar o README.
- Rotas da demonstração offline claramente identificadas na tela.
