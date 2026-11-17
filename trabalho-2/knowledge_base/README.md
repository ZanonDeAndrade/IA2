# Base de conceitos (fichas do RAG)

Fichas em Markdown sobre temas táticos e estratégicos, escritas pelo grupo em
português e indexadas no ChromaDB. São a fonte usada pelo agente nas
explicações (ferramenta `buscar_conceitos`) e o título da ficha é mostrado na
interface como fonte (RF09).

Meta: cerca de **30 fichas, uma por tema**, com as próprias palavras e citando
a referência consultada no fim.

## Formato de cada ficha

Um arquivo por tema, nomeado pelo identificador do tema em `snake_case`
(ex.: `garfo.md`, `peca_pendurada.md`, `ataque_descoberto.md`), com
metadados em YAML no topo e seções fixas:

```markdown
---
id: garfo
titulo: Garfo
tema: fork            # nome do tema na base de puzzles da Lichess (inglês)
tema_pt: garfo        # nome usado pelo agente e pela interface
nivel: iniciante      # iniciante | intermediario
tags: [tatica, cavalo, peao]
---

## Definição
Um lance que ataca duas ou mais peças ao mesmo tempo...

## Como reconhecer
Sinais na posição: peças desprotegidas na mesma cor de casa do cavalo...

## Como evitar
Antes de cada lance, verifique...

## Exemplo
FEN: <posição>
Lances: 1. Nxe5 ... (explicar o que acontece)

## Referências
- Autor, *Título da obra*, capítulo/página.
```

## Regras

- Uma ficha = um trecho na base vetorial. Fichas com mais de ~500 palavras
  devem ser divididas por subtítulo.
- O campo `tema` deve bater com os nomes da coluna `Themes` da Lichess
  (`fork`, `pin`, `skewer`, `hangingPiece`, `discoveredAttack`, ...), para
  cruzar com os puzzles recomendados.
- A lista fechada de temas usada pelo agente (garfo, cravada, espeto, ataque
  descoberto, peça pendurada, mate, sobrecarga, desvio, atração, outro) deve
  ter uma ficha cada.
- Escreva com as próprias palavras; cite a referência no fim da ficha.
