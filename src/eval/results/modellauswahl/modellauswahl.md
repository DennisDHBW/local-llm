# Modellauswahl (gemessen auf dieser Hardware)

## Agent (Tool-Calling, 14 Proben) und Extraktion (3 Verträge)

| Modell | natives Tool-Call | richtiges Werkzeug | Pflichtargumente | Latenz p50 | Tokens/s | RAM | JSON gültig | Feldgenauigkeit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen2.5:7b | 12/14 | 9/14 | 12/14 | 7.1 s | 5.8 | 5.46 GB | 3/3 | 100 % (29) |
| llama3.1:8b | 14/14 | 12/14 | 14/14 | 8.2 s | 5.1 | 6.25 GB | 3/3 | 100 % (29) |
| llama3.2 | 13/14 | 10/14 | 13/14 | 3.3 s | 10.5 | 3.12 GB | 3/3 | 97 % (29) |

## Query-Rewriting (Ziel < 500 ms)

| Modell | p50 | p95 | < 500 ms | Format ok | RAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| llama3.2 | 2668 ms | 3217 ms | 0/20 | 8/20 | 3.12 GB |
| qwen2.5:7b | 4369 ms | 6274 ms | 0/20 | 20/20 | 5.46 GB |
| gemma3:4b | 3244 ms | 4501 ms | 0/20 | 20/20 | 3.04 GB |

## Vision (Werte aus zwei Diagrammen)

| Modell | erkannte Werte | Latenz p50 | RAM |
| --- | ---: | ---: | ---: |
| gemma3:4b | 14/14 | 71 s | 3.04 GB |

Embedding: nomic-embed-text, Dimension 768.

## Auswahl nach docs/abstimmungsregeln.md (R4-R7)

- Agent: llama3.1:8b
- Extraktion: qwen2.5:7b
- Rewriting-Modell: keines erfüllt p95 < 500 ms (Regel-Rewriter oder aus)
- Vision: gemma3:4b
