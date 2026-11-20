# gta6-trophy-rarity-forecast-01-entry

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/dayuwidayadi57/gta6-trophy-rarity-forecast-01-entry/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/dayuwidayadi57/gta6-trophy-rarity-forecast-01-entry/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts every GTA VI trophy's Exophase earn rate at 2026-11-26T00:00:00Z
as five quantiles (5/25/50/75/95%), scored by pinball loss on the logit
scale. A trophy's rate is `r = E / N` (E = tracked players who earned it,
N = tracked players); the median blends a direct logit-trend fit (weight
0.75) with a structural E/N fit (weight 0.25) over the last 24 hours of
reads. The extrapolated median is damped 0.85 toward the last observed
rate, and the no-refresh branch expects launch night's actual first
refresh (N x 6.06, E x 1.02) with its own tight spread floor 0.05. The
random-walk spread is 0.30 log-odds per sqrt(day), measured on seven
simulated finals: mean pinball loss 0.1630, worst scenario 0.1961,
coverage 0.99. See STRATEGY.md for the full reasoning and every number's
evidence. Deterministic, standard library only, no network.

## Run

```sh
MAKEFUN_INPUT_DIR=/input MAKEFUN_OUTPUT_DIR=/output python3 main.py
```

Reads every `*.in` case from the input dir and writes a matching `*.out`
file. Same input bytes always give same output bytes.

## Files

- `main.py` — the forecaster (Python 3.13, standard library only).
- `STRATEGY.md` — the full reasoning, every number's evidence, and the
  measured results.
- `LICENSE` — MIT.
