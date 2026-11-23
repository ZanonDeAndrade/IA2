# Prompts do treinador do modo Jogar contra IA

| Arquivo | Uso |
|---|---|
| `comentario.md` | Comentário de lances aceitáveis: o modelo escolhe um fato verificado e uma lição da ficha. |
| `conceito.md` | Explicação de um conceito perguntado no chat, a partir da ficha recuperada pelo RAG. |

Esta pasta fica fora da assinatura `perfil_explicacao`, que lê apenas os
arquivos `.md` do nível acima. Assim, mudanças aqui não invalidam as
explicações persistidas nem afetam o experimento A/B/C. Os comentários têm
assinatura própria, `perfil_comentario`, que inclui estes arquivos.
