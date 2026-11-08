# Retrieval-Ablation (93 Fragen aus dev,synthetic)

MRR-Differenz: gepaarter Bootstrap gegen die Referenz (Boost 1,5 ohne Zusätze); besser nur, wenn das Intervall über 0 liegt.

| Variante | Recall@5 | Precision@5 | MRR | Beleg@5 | Δ MRR [95 %] | Suche p50 | Rewriting p50 |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| Boost 1,0 (aus) | 100 % [100–100] | 78 % [73–83] | 0.93 [0.88–0.96] | 88 % [80–93] | -0.011 [-0.027; +0.000] (kein messbarer Unterschied) | 57 ms | 0 ms |
| Boost 1,25 | 100 % [100–100] | 79 % [74–84] | 0.94 [0.90–0.97] | 88 % [80–93] | +0.000 [+0.000; +0.000] (kein messbarer Unterschied) | 60 ms | 0 ms |
| Boost 1,5 (Vorgabe) | 100 % [100–100] | 79 % [74–84] | 0.94 [0.90–0.97] | 88 % [80–93] | +0.000 [+0.000; +0.000] (Referenz) | 57 ms | 0 ms |
| Boost 2,0 | 100 % [100–100] | 79 % [74–84] | 0.94 [0.90–0.97] | 88 % [80–93] | +0.000 [+0.000; +0.000] (kein messbarer Unterschied) | 60 ms | 0 ms |
| Boost 1,5 + BM25 | 98 % [95–100] | 76 % [71–81] | 0.95 [0.90–0.98] | 66 % [56–75] | +0.010 [-0.039; +0.059] (kein messbarer Unterschied) | 62 ms | 0 ms |
| Boost 1,5 + Reranker | 99 % [97–100] | 72 % [67–77] | 0.89 [0.84–0.94] | 79 % [70–86] | -0.045 [-0.095; +0.003] (kein messbarer Unterschied) | 1088 ms | 0 ms |
| Boost 1,5 + Rewriting (Regeln) | 99 % [97–100] | 78 % [73–83] | 0.95 [0.91–0.98] | 89 % [81–94] | +0.011 [-0.011; +0.035] (kein messbarer Unterschied) | 49 ms | 0 ms |
| Boost 1,5 + Rewriting (LLM) | 68 % [59–78] | 45 % [37–53] | 0.56 [0.48–0.66] | 37 % [28–47] | -0.372 [-0.475; -0.267] (schlechter) | 2546 ms | 2487 ms |

## Entscheidung nach docs/abstimmungsregeln.md (R1-R3)

- Boost: 1.5 (Boost 1,5 (Vorgabe))
- BM25: aus
- Reranker: aus
- Rewriting: aus
