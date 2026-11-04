# Prompts do agente (em construção)

Textos de prompt usados pelos fluxos em `agent/graph.py`, mantidos fora do
código para facilitar revisão e versionamento. Arquivos previstos:

| Arquivo | Uso |
|---|---|
| `sistema.md` | Prompt de sistema do treinador (português simples, só lances vindos das ferramentas, SAN, até 4 frases). |
| `tema.md` | Escolha do tema tático a partir de uma lista fechada (garfo, cravada, espeto, ataque descoberto, peça pendurada, mate, sobrecarga, desvio, atração, outro). |
| `explicacao.md` | Redação da explicação do erro: o que aconteceu, por que é ruim, o que deveria ter sido jogado e a lição geral. |
| `correcao.md` | Mensagem enviada ao LLM quando o validador encontra um lance inválido (até 2 novas tentativas). |
| `chat.md` | Prompt do agente livre (modo 2) para perguntas sobre a posição exibida. |
