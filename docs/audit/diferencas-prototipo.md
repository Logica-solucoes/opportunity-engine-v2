# Diferenças entre o motor e o protótipo depois da auditoria (09/nov/2026)

As correções da auditoria matemática (`docs/audit/formulas-do-motor.md`, resumo em `docs/decisoes/engine.md` ›
"Auditoria matemática") mudam de propósito todos os blocos do resultado. Este documento registra o quanto o motor se
afastou do protótipo congelado. Daqui em diante a regressão é contra o próprio motor (`engine_snapshot.json`,
`real/gol_engine.json`, `mise run parity-golden`).

Medido em container Linux sob os pins de `mise.toml`, com o `make_engine_goldens.py`. Variação relativa é pouco útil
aqui: vários números do protótipo são próximos de zero (o máximo passa de 1e25 na curva da Gol), então a tabela traz os
valores.

## Sintético da paridade (`tests/engine/synthetic_data.py`, 728 dias, 5 canais)

| | Protótipo | Motor |
| --- | ---: | ---: |
| Eventos candidatos | 6 | 2 |
| Eventos que passam nos gates do evento | 4 | 2 |
| R² do MMM | 0,001 | 0,062 |
| CV R² (fora da amostra no motor) | 0,025 | 0,041 |
| Mídia em % do KPI | 0,1 | 110,8 |
| Contribuição DISPLAY / PMAX / SEARCH / SOCIAL / YOUTUBE (%) | 7,0 / 39,5 / 0,6 / 51,6 / 1,3 | 75,3 / 2,7 / 2,4 / 17,7 / 2,0 |
| Ponto atual: investimento diário / KPI | 3.005,1 / 8.092,6 | 3.004,9 / 8.086,9 |
| Máxima eficiência: investimento / KPI incremental | 3.688,1 / 77,1 | 3.687,9 / 219,5 |
| Limite estratégico: investimento / KPI incremental | 4.507,7 / 123,1 | 4.507,4 / 432,8 |

- Os 6 candidatos do protótipo eram dois degraus sustentados contados três vezes cada (causal-5); sobram 2, os mesmos
  ids do primeiro degrau.
- No run completo, o gate de skill (G3) rebaixa os 2 eventos (`high_oos_wmape`): o sintético não publica evento.

## Gol (`exemplo_csv/Gol`, confidencial: só agregados)

| | Protótipo | Motor |
| --- | ---: | ---: |
| Eventos candidatos | 52 | 31 |
| Passam nos gates do evento | 15 | 0 |
| Selecionados | 5 | 0 |
| R² do MMM | 0,27 | 0,45 |
| CV R² | 0,21 | 0,23 |
| Mídia em % do KPI | 7,7 | 88,9 |

- Menos candidatos: semanas de segunda a domingo sem pontas parciais (causal-6) e um evento por degrau sustentado
  (causal-5). Só 10 ids coincidem com os do protótipo.
- Nenhum evento passa e o run é rebaixado por `high_oos_wmape`; nenhum canal é identificável (dois com `hill_at_bound`).
  Os fixtures de `results` da Gol não têm mais evento publicado.

## O que pede atenção (A10)

1. **Mídia em % do KPI medida contra mídia zero.** Em dado cujo gasto nunca chega perto de zero, a parte abaixo da faixa
   observada é extrapolação pela forma do Hill: 110,8% no sintético e 88,9% na Gol, contra 10–13% e um valor
   desconhecido de verdade. Os canais saem não identificáveis, mas `elasticity.metrics.media_contribution_pct` e a
   contribuição por canal são publicados. Decidir: medir contra o menor nível observado quando nenhum canal é
   identificável, suprimir o número agregado nesse caso, ou outra regra.
2. **Gate de skill (G3) com limiar provisório.** `oos_skill_min` = 0,10 rebaixa todos os eventos da Gol e do sintético.
   Calibrar com a Data Science; sem evento publicado, a aba Causal só mostra rejeições.
3. **Caso `late_launch` do MMM.** Sob os pins do Linux o otimizador para fora do limite do Hill e o guarda
   `hill_at_bound` não dispara: a mídia sai ~2,7× a verdadeira (`test_audit_mmm.py`, marcado `xfail`, passa no Windows).
4. **EP acumulado do causal.** Calibrado em 5,5–8,5% de falso positivo a 5% nominal, ainda levemente anticonservador
   (parâmetros do MLE tratados como conhecidos).
5. **Respostas reais do Gemini da Gol.** Sem evento publicado, as narrativas de evento gravadas não têm job; regravar
   com chave (`LLM_LIVE=1`).
