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
- Use o identificador da coluna `Themes` da Lichess quando houver um equivalente.
  Em conceitos sem equivalente direto, `tema` usa o identificador local.
  O campo `tema_pt` identifica a ficha para o agente.
- A lista fechada de temas usada pelo agente (garfo, cravada, espeto, ataque
  descoberto, peça pendurada, mate, sobrecarga, desvio, atração, outro) deve
  ter uma ficha cada.
- Escreva com as próprias palavras; cite a referência no fim da ficha.

## Criar o índice

Na raiz do projeto, com as dependências Python instaladas:

```bash
python -m knowledge_base.index
python -m knowledge_base.index --reconstruir
```

O primeiro comando atualiza apenas os trechos modificados. O segundo recalcula
todos os vetores. Ambos removem trechos de fichas excluídas. As configurações
`CHROMA_PATH` e `EMBEDDING_MODEL` são opcionais. Por padrão, o índice fica em
`data/chroma` e o modelo é o [MiniLM multilíngue](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
Na primeira execução o modelo pode precisar ser baixado. Para uso offline,
`EMBEDDING_MODEL` também aceita o caminho de uma cópia local do modelo.

`buscar_conceitos(pergunta, k=4, tema=None)` consulta esse índice no servidor MCP
existente. A busca devolve o texto e a origem de cada trecho. Sem índice ou sem
resultados para o tema informado, devolve uma lista vazia.
