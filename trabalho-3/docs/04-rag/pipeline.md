# Pipeline RAG para PDFs

1. Descobre os PDFs presentes em `data/raw/`, calcula o SHA-256 e extrai texto com o `pdftotext` do Poppler. O relatório aponta as páginas sem texto. Um documento inteiro sem texto gera erro com o nome do arquivo.
2. Mantém a numeração física e divide o texto de cada página em trechos de até 100 tokens, com sobreposição de aproximadamente 20 tokens ajustada às fronteiras das palavras.
3. Calcula embeddings locais de 384 dimensões com a revisão fixada do MiniLM multilíngue. Grava os trechos, vetores, arquivos e páginas no ChromaDB. A coleção é identificada pelo conteúdo do corpus e pela configuração do índice. Uma reingestão idêntica reutiliza os vetores.
4. Substitui atomicamente o JSON do corpus após conferir a contagem da coleção. O relatório e o manifesto registram o que a ingestão processou.
5. Consulta até oito candidatos por padrão, com filtro opcional por PDF, e retorna até cinco páginas. O resultado carrega o trecho recuperado, o número físico da página e a referência relativa `data/raw/arquivo.pdf#page=N`.

O campo `recipe_id` identifica a página para a interface de busca e para `Retriever.get_document()`. O retorno integral da página está em `recipe.text`. Os tópicos correspondem aos PDFs indexados. O campo `mentioned_ingredients` indica ocorrências no texto. A lista completa de ingredientes e a classificação de compatibilidade exigiriam uma etapa específica de estruturação das receitas dos PDFs.
