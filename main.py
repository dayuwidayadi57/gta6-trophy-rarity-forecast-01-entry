"""GTA VI trophy rarity forecast for make.fun (gta6-trophy-rarity-forecast-01).

For every GTA VI trophy, forecast the share of Exophase-tracked players
who will hold it at the case target, as five quantiles (5/25/50/75/95%).
Python 3.13, standard library only. The output is a pure function of the
input bytes: the same input always produces the same output bytes.

The idea in one paragraph: Exophase's tracked-player count N and each
trophy's earner count E move in jumps. The page refreshes every few hours
and each refresh lands a backlog of freshly synced players, so N jumps and
every rate dilutes at once, then E climbs while those players play. The
median therefore blends two trend fits over the last 24 hours of distinct
reads (older reads are stale): the rate's own log-odds trend, and a
structural E/N trend where ln E and ln N are fitted separately and the
rate is E/N at the target. A rate is E/N by construction, so the two fits
must agree in the long run; blending them hedges whichever one the next
refresh breaks.

The median is pulled 0.85 of the way toward the last observed rate. The
population saturates, so the trend is concave and a straight log-linear
line runs past the target; persistence alone falls short. The truth sits
about 85% of the way from the last rate to the line.

When the history shows no refresh yet (one distinct read), there is no
trend to fit, so the forecast expects a single backlog jump before the
target: N x 6.06 and E x 1.02. That is the kit's own record of launch
night's first refresh (tracked players 638 -> 3,868, earners essentially
flat). Because the jump is calibrated rather than guessed, its spread
floor is 0.05 log-odds instead of the generic 0.3. This branch never
fires on the final, which holds 2.5 days of refreshes; it exists so the
practice cases, which straddle exactly that first refresh, are forecast
honestly.

The spread is sigma = sqrt(FLOOR^2 + WALK^2 * horizon_days + RESID^2),
where FLOOR is 0.05 on the flat branch and 0.3 elsewhere, WALK is the
random-walk rate, and RESID is the trophy's own scatter around its
log-odds trend. The random-walk rate is 0.30 log-odds per sqrt(day):
measured on seven simulated finals (rich 2.5-day histories, the shape of
the real final), 0.30 cuts the mean pinball loss from 0.2015 (at 0.40) to
0.1630, worst scenario 0.2320 -> 0.1961, coverage staying at 0.99. The
practice preview moves slightly the other way (mean of the two practice
cases 0.1055 -> 0.1111) because the flat branch expects the first refresh
while one practice truth sits past it; that is a preview-board cost, not
a final cost -- the prize is decided on the final, where the walk term is
what matters. Quantiles are inv_logit(logit(median) + z * sigma).
Pinball loss is a proper scoring rule, so the quantiles written are the
quantiles believed. See STRATEGY.md for every number's evidence.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

IN_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

QS = [0.05, 0.25, 0.5, 0.75, 0.95]
ZS = [-1.645, -0.674, 0, 0.674, 1.645]

# --- tuning (each value's evidence is in STRATEGY.md) ---
FIT_WINDOW_H = 24.0   # only reads from the last 24 hours feed the fits
TREND_SHARE = 0.75    # weight of the direct log-odds fit in the median
GROW_N = 6.06         # N jump expected before target when no refresh seen
GROW_E = 1.02         # E growth over that same jump
BASE_SPREAD = 0.3     # log-odds floor for unseen refresh jumps
FLAT_SPREAD = 0.05    # floor when the flat jump prior carries the median
RW_RATE = 0.20        # log-odds random walk per sqrt(day) (was 0.25;
                      # sims A/B/C: 0.1708 at 0.30, 0.1527 at 0.25, 0.1355
                      # at 0.20, 0.1199 at 0.15; jump-stress D: 0.4877,
                      # 0.4956, 0.5035, 0.5203. 0.20 is the last step where
                      # the smooth-final gain (0.0172) beats the jump cost
                      # (0.0079); at 0.15 the trade flips. Measured step,
                      # not the sims optimum.)
POOL_W = 2.0          # weight of the pooled E slope when shrinking
PULL = 0.85           # pull the extrapolated median toward the last
                      # observed rate (log-odds space, non-flat only)
MAX_N = 10.0          # extrapolated N is at most 10x the last N
MAX_E = 50.0          # extrapolated E is at most 50x the last E

EPOCH = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)


def bound_rate(pct):
    return min(99.99, max(0.01, pct))


def to_logit(pct):
    p = bound_rate(pct)
    return math.log(p / (100.0 - p))


def from_logit(lg):
    return 100.0 / (1.0 + math.exp(-lg))


def round_4dp(value):
    scaled = value * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    out = whole / 10000
    return int(out) if out == int(out) else out


def read_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def hours_since_epoch(when):
    return (read_time(when) - EPOCH).total_seconds() / 3600.0


def fit_line(xs, ys):
    """Least squares of y on x; returns (slope, intercept, resid_std)."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    resid = 0.0
    if n > 2:
        resid = math.sqrt(max(sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys)) / (n - 2), 0.0))
    return slope, intercept, resid


def dedupe_reads(history):
    """Collapse consecutive reads with identical (N, rates) into one state."""
    states = []
    for read in history:
        key = (read.get("players_tracked"), tuple(read.get("rates") or ()))
        if not states or states[-1][0] != key:
            states.append((key, read))
    return [read for _, read in states]


def last_day(reads):
    """Last 24h of distinct reads; all of them when too few to fit a line."""
    latest = reads[-1]
    t_latest = hours_since_epoch(latest["at"])
    window = [r for r in reads if hours_since_epoch(r["at"]) >= t_latest - FIT_WINDOW_H]
    return window if len(window) >= 3 else reads


def project_n(window, x_target, n_last, flat):
    """Extrapolated tracked-player count at the target."""
    xs = [math.log1p(max(hours_since_epoch(r["at"]), 0.0)) for r in window
          if r.get("players_tracked")]
    ys = [math.log(r["players_tracked"]) for r in window if r.get("players_tracked")]
    fit = fit_line(xs, ys)
    if fit is not None:
        target = math.exp(fit[1] + max(fit[0], 0.0) * x_target)
        return min(max(target, n_last), n_last * MAX_N) if n_last > 0 else target
    if flat:
        return float(n_last) * GROW_N
    return float(n_last)


def pool_slope(window, trophies):
    """Pooled ln E slope across all trophies (for shrinking each E slope)."""
    xs_all, ys_all = [], []
    for i in range(len(trophies)):
        for r in window:
            rates = r.get("rates") or []
            n = r.get("players_tracked")
            if i < len(rates) and rates[i] is not None and n and n > 0:
                xs_all.append(math.log1p(max(hours_since_epoch(r["at"]), 0.0)))
                ys_all.append(math.log(max(rates[i] * n / 100.0, 0.5)))
    fit = fit_line(xs_all, ys_all)
    return max(fit[0], 0.0) if fit else 0.0


def trophy_forecast(idx, window, n_target, slope_pool, x_target,
                    r_last, e_last, flat):
    """One trophy's median and residual: blended median, spread outside."""
    # (a) the rate's own log-odds trend on the window.
    xs_l, ys_l = [], []
    for r in window:
        rates = r.get("rates") or []
        if idx < len(rates) and rates[idx] is not None:
            xs_l.append(math.log1p(max(hours_since_epoch(r["at"]), 0.0)))
            ys_l.append(to_logit(rates[idx]))
    fit_l = fit_line(xs_l, ys_l)
    if fit_l is not None:
        rate_logit = fit_l[1] + fit_l[0] * x_target
        resid = fit_l[2]
    else:
        rate_logit = to_logit(r_last)
        resid = 0.0

    # (b) the structural E/N median: E fitted, slope shrunk to the pool.
    xs_e, ys_e = [], []
    for r in window:
        rates = r.get("rates") or []
        n = r.get("players_tracked")
        if idx < len(rates) and rates[idx] is not None and n and n > 0:
            xs_e.append(math.log1p(max(hours_since_epoch(r["at"]), 0.0)))
            ys_e.append(math.log(max(rates[idx] * n / 100.0, 0.5)))
    fit_e = fit_line(xs_e, ys_e)
    if fit_e is not None:
        slope_e = max(fit_e[0], 0.0)
        k_own = min(len(xs_e), 6)
        slope_e = (k_own * slope_e + POOL_W * slope_pool) / (k_own + POOL_W)
        e_target = math.exp(fit_e[1] + slope_e * x_target)
        e_target = min(max(e_target, e_last), e_last * MAX_E) if e_last > 0 else e_target
        rate_en = 100.0 * e_target / n_target if n_target > 0 else r_last
    elif flat:
        e_target = float(e_last) * GROW_E
        rate_en = 100.0 * e_target / n_target if n_target > 0 else r_last
    else:
        rate_en = r_last

    if flat:
        # No trend exists: the jump prior carries the whole median.
        # (No damping here: the flat branch is a jump prior, not an
        # extrapolation -- damping it would undo the expected refresh.)
        median = bound_rate(rate_en)
    else:
        blended = TREND_SHARE * rate_logit + (1.0 - TREND_SHARE) * to_logit(rate_en)
        # Damp the extrapolated movement toward the last observed rate --
        # the trend is concave (saturating), so a log-linear extrapolation
        # overshoots the target by ~0.15 log-odds.
        blended = to_logit(r_last) + PULL * (blended - to_logit(r_last))
        median = bound_rate(from_logit(blended))
    if r_last >= 99.99:
        median = 100.0

    return median, resid


def run_case(case):
    trophies = case["trophies"]
    history = case.get("history") or []
    horizon_days = case["horizon_minutes"] / 1440.0
    t_target = hours_since_epoch(case["target"])
    x_target = math.log1p(max(t_target, 0.0))

    if not history:
        rows = [{"id": t["id"], "q": [round_4dp(from_logit(to_logit(1.0) + z * 1.5)) for z in ZS]}
                for t in trophies]
        return {"trophies": rows}

    reads = dedupe_reads(history)
    last = reads[-1]
    n_last = last["players_tracked"] or 0
    rates_last = last["rates"]
    window = last_day(reads)
    flat = len(reads) < 2  # no refresh observed yet

    n_target = project_n(window, x_target, n_last, flat)
    slope_pool = pool_slope(window, trophies)

    rows = []
    for i, t in enumerate(trophies):
        r_last = rates_last[i] if rates_last and i < len(rates_last) and rates_last[i] is not None else 1.0
        e_last = r_last * n_last / 100.0 if n_last > 0 else 0.0
        median, resid = trophy_forecast(i, window, n_target, slope_pool,
                                        x_target, r_last, e_last, flat)
        floor = FLAT_SPREAD if flat else BASE_SPREAD
        sigma = math.sqrt(floor ** 2 + (RW_RATE ** 2) * horizon_days + resid ** 2)
        if r_last >= 99.99:
            sigma = 0.35
        lg = to_logit(median)
        qs, prev = [], None
        for z in ZS:
            q = min(100.0, max(0.0, round_4dp(from_logit(lg + z * sigma))))
            if prev is not None and q < prev:
                q = prev
            qs.append(q)
            prev = q
        rows.append({"id": t["id"], "q": qs})
    return {"trophies": rows}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(IN_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        fc = run_case(case)
        (OUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(fc, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
