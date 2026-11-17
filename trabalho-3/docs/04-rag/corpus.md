# Corpus em PDF

Coloque os documentos em [data/raw/](../../data/raw/). A ingestão seleciona os arquivos com extensão `.pdf`, incluindo extensões em maiúsculas. O manifesto gerado em `data/sources/manifest.json` registra nome do arquivo, identificador, SHA-256, contagem de páginas e posição das páginas sem texto extraível. O manifesto é renovado a partir da pasta a cada ingestão.

A numeração de origem segue o visualizador de PDF, começando em 1. A numeração impressa no livro pode começar depois da capa. Por exemplo, `data/raw/50_receitas.pdf#page=20` identifica a vigésima página física do arquivo.

Os textos vêm dos arquivos fornecidos localmente. Autoria e licenças devem ser verificadas nos livros antes de redistribuir os documentos ou o corpus derivado.
