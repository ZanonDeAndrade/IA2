# Recomendação de receitas: intenção, compatibilidade e ranking

Como o Chef IA transforma "ingredientes + pergunta" em recomendações fundamentadas. A IA não decide sozinha o
que pode ser preparado: a compatibilidade é calculada por código sobre os dados estruturados das receitas.

```
pergunta + ingredientes
  └─▶ guardrail de entrada
  └─▶ 1. intenção (LLM, saída estruturada) ─▶ validação pelo backend ─▶ plano
  └─▶ 2. LLM + ferramentas MCP permitidas pelo plano
         search_knowledge ─▶ RAG (Chroma, semântico) ∪ critério estruturado (ingredientes)
                          ─▶ compatibilidade programática ─▶ ranking documentado
  └─▶ 3. seleção programática (elegibilidade + ordem + situação A/B/C)
  └─▶ 4. guardrail de saída na narrativa (ou texto determinístico)
  └─▶ cards montados com get_document (ingredientes, preparo, fonte)
```

## 1. Diagnóstico do problema original

Pergunta "O que posso fazer para o meu café da manhã?" com pão, manteiga, ovo e queijo resultava em
"Categorias disponíveis na base: Bolos (16)…". Causas, em cadeia:

| Etapa | Problema |
|---|---|
| Orquestração | O LLM (`qwen3:1.7b`) recebia as três ferramentas e escolhia `list_topics`; nada impedia isso. |
| Argumentos | Quando buscava, inventava `topic_key` (ex.: "café da manhã") e o MCP rejeitava (`INVALID_TOOL_ARGUMENTS`). |
| Fallback | Rejeitada a resposta final, `_fallback` devolvia `topics_answer` sempre que `list_topics` tinha sido chamada. |
| Guardrail | `FOUND` sem receitas era aceito se houvesse categorias na evidência, qualquer que fosse o pedido. |
| Corpus | 10 páginas, 4 delas perdidas pelo parser (formato "Ingredientes e Preparo"); sem frango, arroz salgado, batata, tomate. |
| Compatibilidade | Igualdade exata do nome normalizado: "queijo" ≠ "queijo ralado", sem plural; "chocolate em pó" virava "chocolate". |
| Ranking | Só 8–10 trechos candidatos (~5 receitas); um filtro lexical no retriever impedia buscas por característica. |

## 2. Interpretação da consulta (`backend/app/inference/intent.py`)

O LLM classifica a intenção com `format` = JSON Schema (sem ferramentas): `receitas_por_ingredientes`,
`receita_por_nome`, `receitas_por_categoria`, `receitas_por_caracteristica`, `modo_de_preparo`, `listar_categorias`,
além de `prato`, `ingredientes` citados na pergunta e uma `consulta` de busca.

O backend valida a saída contra o texto do usuário (não são palavras-chave fixas):

- ingredientes e prato extraídos só valem se aparecerem na pergunta (anti-alucinação);
- quem informa ingredientes pede receitas: `listar_categorias` com ingredientes vira busca por ingredientes;
- busca por nome/preparo sem prato identificável vira busca por ingredientes ou característica;
- classificação inválida: plano padrão de busca de receitas (nunca categorias).

O plano define as ferramentas oferecidas ao LLM: `list_topics` **só** para `listar_categorias`;
nos demais casos `search_knowledge` e `get_document`. Uma chamada fora do plano recebe `TOOL_NOT_FOR_INTENT`.
Se o LLM não chamar a ferramenta exigida, recebe uma instrução; se insistir, o backend executa a chamada via MCP.

## 3. Normalização de ingredientes (`rag/ingredients.py`)

Mesma regra na ingestão e no servidor MCP:

1. minúsculas, sem acentos, sem observações entre parênteses;
2. singular por palavra (ovos→ovo, pães→pão, limões→limão, colheres→colher);
3. remoção de modificadores de estado/preparo/tamanho que não mudam o ingrediente
   (ralado, derretido, picado, cozido, maduro, grande, em cubos, em neve, a gosto…);
   compostos protegidos: coco ralado, pão ralado, carne moída, batata palha;
4. sinônimos curados (maisena→amido de milho, fermento químico→fermento em pó, mozzarella→queijo mussarela).

Ingredientes semelhantes continuam diferentes: leite ≠ leite condensado ≠ leite de coco ≠ creme de leite ≠
leite em pó; farinha de trigo ≠ farinha de arroz ≠ farinha de mandioca; chocolate ≠ chocolate em pó;
manteiga ≠ margarina.

`user_ingredient_keys` define o que um ingrediente informado satisfaz:

- partes do mesmo alimento: ovo → gema/clara de ovo; frango → peito/coxa/filé de frango;
- genérico de uma variedade: queijo parmesão satisfaz "queijo"; açúcar cristal satisfaz "açúcar";
- o inverso **não** vale (quem informa "queijo" não tem necessariamente "queijo parmesão"): sem substituições presumidas.

## 4. Compatibilidade (servidor MCP, `mcp-server/tools.py`)

Só ingredientes **obrigatórios** contam (opcionais, "a gosto", "para untar" ficam fora):

| Status | Regra |
|---|---|
| `COMPLETE` | todos os obrigatórios satisfeitos (presença, não quantidade) |
| `PARTIAL` | ao menos um satisfeito e há faltantes (listados em `missing_ingredients`) |
| `NO_MATCH` | ingredientes informados, nenhum obrigatório satisfeito |
| `NOT_EVALUATED` | usuário não informou ingredientes |

## 5. Recuperação híbrida e ranking (`search_knowledge`)

`ranking="compatibility"` (padrão quando há ingredientes):

- candidatos = receitas dos 60 trechos semanticamente mais próximos **∪** receitas do corpus que usam ao menos um
  ingrediente informado (critério estruturado; garante que uma receita compatível não fique de fora só por
  não estar entre os vizinhos semânticos);
- só entram `COMPLETE` e `PARTIAL` (receita sem ingrediente em comum não é recomendação por ingredientes);
- ordem lexicográfica, sem pesos arbitrários:
  1. `COMPLETE` antes de `PARTIAL` — o que dá para preparar agora vem primeiro;
  2. menos ingredientes faltantes — menos compras;
  3. mais ingredientes do usuário usados — aproveita o que ele tem;
  4. menor distância semântica — mais próxima do pedido;
- até 8 candidatas vão ao LLM, que julga a adequação ao pedido (ocasião, tipo de prato), informação que não
  existe nos metadados.

`ranking="relevance"` (busca por nome/preparo ou sem ingredientes): ordem pela distância semântica; a
compatibilidade é calculada e exibida, mas não exclui.

## 6. Seleção final e situações (`backend/app/inference/recommend.py`)

Elegibilidade conforme a intenção:

- com ingredientes (exceto busca por nome): só `COMPLETE`/`PARTIAL`;
- busca por nome/preparo: o título precisa conter a palavra principal do prato (e o maior número de palavras dele);
- sem ingredientes: qualquer receita devolvida neste turno, escolhida pelo LLM.

O LLM escolhe entre os elegíveis. Receitas `COMPLETE` elegíveis sempre entram. Se nenhuma escolha do LLM for válida
e houver critério estruturado (ingredientes ou título), o sistema apresenta os melhores candidatos ranqueados.
A ordem final segue a mesma ordem lexicográfica do item 5 (e, em empate, a ordem do LLM).

| Situação | Quando | Apresentação |
|---|---|---|
| A — `CAN_PREPARE` | há receita `COMPLETE` | "Você pode preparar agora" primeiro, depois "Com ingredientes adicionais" |
| B — `NEEDS_INGREDIENTS` | só `PARTIAL` | aviso "Nenhuma receita totalmente compatível…" + faltantes de cada uma |
| C — `NONE` | nada elegível | `INSUFFICIENT` com mensagem específica; nunca categorias, nunca receitas sem relação |

Se a seleção final difere da escolha do LLM, ou se a narrativa for rejeitada duas vezes pelo guardrail, a resposta
é um texto determinístico montado só com a evidência e a compatibilidade calculada. O guardrail de saída também
recusa "dá para preparar agora" quando nenhuma receita escolhida é `COMPLETE`.

## 7. Limitações conhecidas

- Não há metadado de refeição (café da manhã, almoço) nem de tempo no corpus: a adequação à ocasião depende do
  julgamento do LLM entre candidatos compatíveis.
- O parser do wikitext é heurístico: cerca de 3,5% dos nomes de ingrediente ainda têm ruído (frases de preparo
  dentro da lista, quantidades por extenso). Esses itens aparecem como faltantes, nunca como disponíveis indevidos.
- "pão" não satisfaz "pão francês" e "queijo" não satisfaz "queijo parmesão" (regra conservadora, sem substituição).
- Com `qwen3:1.7b` em CPU, cada consulta leva de ~1 a ~3 minutos (classificação + 2 a 4 rodadas do LLM).
