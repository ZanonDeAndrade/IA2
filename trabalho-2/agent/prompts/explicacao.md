# Explicar um erro

Devolva um objeto JSON com exatamente três campos textuais, sem delimitadores Markdown em torno do objeto.

- `aconteceu` contém uma frase sobre a mudança confirmada na posição.
- `motivo` contém uma frase simples sobre por que a mudança pode prejudicar o jogador. Se as ferramentas não indicarem uma consequência clara, explicite a limitação.
- `licao` contém uma frase prática para evitar o problema, embasada no conceito recuperado quando houver ficha.

O sistema acrescenta a alternativa do Stockfish. Nos três campos, use nomes de peças e escreva a ideia tática por extenso. Deixe lances, variantes e coordenadas exclusivamente para o sistema. Refira-se à jogada feita como “o lance da partida”.

Use somente as mudanças registradas. Uma peça atacada pode estar protegida e um ataque geométrico por si só não comprova uma captura forçada. Sem consequência certa, descreva a mudança observada e formule uma lição geral. Use uma frase por campo e responda em português.
