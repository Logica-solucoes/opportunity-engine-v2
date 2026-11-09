"""
This module contains the functions for running a Elasticity Analysis (Elasticity)
to determine the optimal budget allocation based on historical data.
"""

import json
import logging

import matplotlib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import MinMaxScaler

matplotlib.use("Agg")
import os

import holidays
import matplotlib.pyplot as plt

log = logging.getLogger(__name__)


def create_calendar_features(df, country_code="BR", period_days=1):
    """
    Creates various time-series features based on the 'Date' column.

    Args:
        df (pd.DataFrame): The input DataFrame containing a 'Date' column.
        country_code (str): The ISO country code for holiday detection.
        period_days (int): Days per reporting period (from cadence detection).
            Weekend/payday/holiday features only make sense on genuinely daily
            data -- on weekly-or-coarser data every row lands on the same day
            of week, so they'd be constant/degenerate columns. `month_*` stays
            useful at any granularity coarser than daily, so it's always
            generated.

    Returns:
        pd.DataFrame: The DataFrame with added calendar features.
    """
    df_featured = df.copy()

    if "Date" not in df_featured.columns:
        return df_featured

    df_featured["Date"] = pd.to_datetime(df_featured["Date"])
    df_featured.set_index("Date", inplace=True)

    # Month features (one-hot encoded)
    for month in range(1, 13):
        df_featured[f"month_{month}"] = (df_featured.index.month == month).astype(int)

    if period_days == 1:
        # Weekend feature
        df_featured["is_weekend"] = (df_featured.index.dayofweek >= 5).astype(int)

        # Payday period (typically 1st-5th and 15th-20th of the month)
        df_featured["is_payday_period"] = (
            ((df_featured.index.day >= 1) & (df_featured.index.day <= 5))
            | ((df_featured.index.day >= 15) & (df_featured.index.day <= 20))
        ).astype(int)

        # Holiday feature
        try:
            country_holidays = holidays.CountryHoliday(country_code)
            df_featured["is_holiday"] = df_featured.index.map(lambda date: date in country_holidays).astype(int)
        except Exception:
            df_featured["is_holiday"] = 0

    df_featured.reset_index(inplace=True)
    return df_featured


def geometric_adstock(spend, alpha, max_len=12):
    """
    Applies a geometric adstock transformation to a spend series.

    Args:
        spend (np.array): The input spend series.
        alpha (float): The adstock decay factor (0 to 1).
        max_len (int): The maximum length of the adstock effect.

    Returns:
        np.array: The adstocked spend series.
    """
    weights = alpha ** np.arange(max_len)
    adstocked_spend = np.convolve(spend, weights, mode="full")[: len(spend)]
    return adstocked_spend


def hill_transform(spend, k, s):
    """
    Applies the Hill saturation transformation to a spend series.

    Args:
        spend (np.array): The input spend series (usually adstocked).
        k (float): The shape parameter (steepness).
        s (float): The scale parameter (inflection point).

    Returns:
        np.array: The saturated spend series.
    """
    # Use a small epsilon to avoid division by zero or errors with non-positive values
    epsilon = 1e-9

    if isinstance(spend, (pd.Series, np.ndarray)):
        result = np.zeros_like(spend, dtype=float)
        non_zero_mask = spend > epsilon
        if np.any(non_zero_mask):
            # Safe calculation for series/array
            ratio = spend[non_zero_mask] / (s + epsilon)
            # Clip ratio to avoid extreme values before power operation
            safe_ratio = np.maximum(ratio, epsilon)
            result[non_zero_mask] = 1 / (1 + safe_ratio**-k)
        return result
    else:
        # Scalar version
        if spend <= epsilon:
            return 0.0
        ratio = spend / (s + epsilon)
        safe_ratio = max(ratio, epsilon)
        return 1 / (1 + safe_ratio**-k)


def predict_clipped_kpi(organic_baseline_mean, mkt_model, mkt_scaler, mkt_features):
    """
    Predicts KPI from Hill-transformed marketing features, flooring the scaled
    features at 0 before feeding the linear model.

    Simulated spend below the historically observed range (e.g. investment=0)
    extrapolates `mkt_scaler` below the range it was fit on -- MinMaxScaler
    does not clip, so this can produce a negative scaled feature which,
    combined with the model's non-negative coefficients, predicts a KPI below
    the organic baseline (even negative). Flooring at 0 fixes that.

    The upper bound is intentionally left unclipped: `mkt_features` is already
    a Hill-transform output, which asymptotically bounds itself to [0, 1) for
    any finite spend -- it never actually reaches 1. Simulating spend above
    the historical max (the whole point of scanning "how far could we scale")
    legitimately produces a scaled feature above 1 when the channel's true
    saturation point sits beyond what was ever spent historically; that is
    real signal, still finite (bounded by the Hill asymptote), not runaway
    extrapolation. Clipping it to exactly 1 used to erase all remaining
    marginal gain the instant one simulated point crossed the historical max,
    turning smooth diminishing returns into a hard, one-step wall to zero --
    see docs/superpowers/plans/2026-07-06-dashboard-inconsistencies-fix-design.md
    and the 2026-07-08 follow-up investigation.
    """
    scaled_features = np.clip(mkt_scaler.transform([mkt_features]), 0.0, None)
    return organic_baseline_mean + mkt_model.predict(scaled_features)[0]


def kpi_band(organic_baseline_mean, coef_samples, mkt_scaler, mkt_features) -> tuple[float, float]:
    """p5/p95 of the KPI over the bootstrap resamples of the Ridge (A8). Hill, adstock and scaler stay fixed, so the
    band is optimistic: it carries the uncertainty of the split, not of the curve shapes."""
    features = pd.DataFrame([mkt_features], columns=getattr(mkt_scaler, "feature_names_in_", None))
    scaled = np.clip(mkt_scaler.transform(features), 0.0, None)[0]
    lo, hi = np.percentile(organic_baseline_mean + np.asarray(coef_samples) @ scaled, [5, 95])
    return float(lo), float(hi)


def _transform_channels(df, spend_cols, alphas, ks, ss):
    """Adstock + Hill-saturate each channel's spend into a features DataFrame."""
    transformed_df = pd.DataFrame()
    for i, col in enumerate(spend_cols):
        adstocked_spend = geometric_adstock(df[col].values, alphas[i])
        transformed_df[col] = hill_transform(adstocked_spend, ks[i], ss[i])
    return transformed_df


CV_SPLITS = 3


def trusts_reallocation(cv_r2: float, config: dict) -> bool:
    """Whether the MMM's out-of-sample fit is good enough to move budget between channels (see run_response_curve)."""
    return cv_r2 >= config["reallocation_min_cv_r2"]


def cv_folds(n_rows: int, n_splits: int = CV_SPLITS) -> int:
    """Folds walk_forward_cv_score uses: one per 20 rows, at most n_splits. Under 2 it scores in-sample (A6 says so)."""
    return min(n_splits, max(1, n_rows // 20))


def walk_forward_cv_score(transformed_df, kpi_lift, n_splits=CV_SPLITS):
    """
    Walk-forward (expanding-window) CV for the Stage-2 marketing fit. Returns
    (mean_out_of_sample_mse, pooled_out_of_fold_r2).

    Selecting the adstock/Hill params by OUT-OF-SAMPLE error instead of in-sample
    MSE is the core fix for the identifiability problem: the flexible saturation
    transform (3 params/channel) could drive in-sample MSE down by overfitting
    noise, which pinned params on their bounds and reported an R^2 that didn't
    generalize. The scaler is refit on each training fold so test folds stay
    genuinely out of sample. Falls back to in-sample when there is too little
    data to split.
    """
    X = np.asarray(transformed_df.values, dtype=float)
    y = np.asarray(kpi_lift, dtype=float)
    n = len(y)
    usable_splits = cv_folds(n, n_splits)
    if usable_splits < 2:
        scaler = MinMaxScaler()
        Xs = scaler.fit_transform(X)
        model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(Xs, y)
        pred = model.predict(Xs)
        return float(np.mean((y - pred) ** 2)), float(r2_score(y, pred))

    tscv = TimeSeriesSplit(n_splits=usable_splits)
    fold_mses, oof_true, oof_pred = [], [], []
    for train_idx, test_idx in tscv.split(X):
        scaler = MinMaxScaler().fit(X[train_idx])
        model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(scaler.transform(X[train_idx]), y[train_idx])
        pred = model.predict(scaler.transform(X[test_idx]))
        fold_mses.append(float(np.mean((y[test_idx] - pred) ** 2)))
        oof_true.extend(y[test_idx].tolist())
        oof_pred.extend(pred.tolist())

    r2 = r2_score(oof_true, oof_pred) if len(set(oof_true)) > 1 else 0.0
    return float(np.mean(fold_mses)), float(r2)


def elasticity_objective_function(params, df, kpi_lift, spend_cols):
    """
    Objective for the Two-Stage Elasticity optimization: minimize the
    walk-forward CV MSE of the Stage-2 fit (not in-sample MSE -- see
    walk_forward_cv_score for why).
    """
    num_channels = len(spend_cols)
    alphas = params[:num_channels]
    ks = params[num_channels : 2 * num_channels]
    ss = params[2 * num_channels : 3 * num_channels]

    transformed_df = _transform_channels(df, spend_cols, alphas, ks, ss)
    mse, _ = walk_forward_cv_score(transformed_df, kpi_lift)
    return mse


def optimize_with_restarts(objective, initial_params, bounds, args, n_restarts=5, seed=42):
    """
    Runs scipy.optimize.minimize from `initial_params` plus `n_restarts` additional
    starting points sampled uniformly within `bounds`, and returns whichever run
    converged to the lowest objective value.

    Guards against the optimizer settling into a bad local minimum from a single
    starting point -- which is what happens with the Stage-2 elasticity fit on
    collinear channel spend (see docs/superpowers/specs/2026-07-06-dashboard-inconsistencies-fix-design.md).
    """
    rng = np.random.default_rng(seed)
    candidate_starts = [initial_params] + [[rng.uniform(low, high) for low, high in bounds] for _ in range(n_restarts)]

    best_result = None
    for candidate in candidate_starts:
        candidate_result = minimize(
            objective,
            candidate,
            args=args,
            bounds=bounds,
            method="L-BFGS-B",
            options={"maxiter": 500, "disp": False},
        )
        if best_result is None or candidate_result.fun < best_result.fun:
            best_result = candidate_result

    return best_result


def bootstrap_coefficients(X, y, n_bootstrap=200, seed=42):
    """
    Refits Ridge(alpha=1.0, positive=True, fit_intercept=False) on n_bootstrap
    resamples of the rows (with replacement) and returns the (n_bootstrap, n_columns)
    matrix of coefficients. The model uses its mean; A5 uses its percentiles.

    A single fit of a positive-constrained Ridge on correlated columns tends to
    hand all the credit to one column and zero the other (a stable but fragile
    corner solution -- see docs/superpowers/specs/2026-07-06-dashboard-inconsistencies-fix-design.md
    for the original diagnosis and the 2026-07-08 follow-up confirming it happens
    even when the zeroed channel has real, substantial spend). Averaging over
    resamples smooths this out: a channel that only wins the corner solution by
    chance on the full dataset won't win it in every resample.
    """
    rng = np.random.default_rng(seed)
    n_rows = X.shape[0]
    y_arr = np.asarray(y)
    coefs = np.zeros((n_bootstrap, X.shape[1]))
    for b in range(n_bootstrap):
        idx = rng.integers(0, n_rows, n_rows)
        model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(X[idx], y_arr[idx])
        coefs[b] = model.coef_
    return coefs


def run_mmm_engine(config, prepared):
    """
    Runs the Two-Stage Elasticity Analysis (MMM) engine.
    Stage 1: Models the organic baseline using context and calendar features.
    Stage 2: Models the residual KPI lift using marketing investment.
    """
    log.info("Starting Two-Stage Elasticity Analysis Engine...")

    try:
        # Load and prepare data
        kpi_df = prepared.kpi_df.copy()
        daily_investment_df = prepared.investment_df.copy()
        trends_df = prepared.trends_df.copy()

        # Pivot investment data to have channels as columns
        investment_pivot_df = daily_investment_df.pivot_table(
            index="Date", columns="Product Group", values="investment"
        ).fillna(0)

        # Merge all data into a single DataFrame
        df = investment_pivot_df.reset_index().copy()
        df = pd.merge(df, kpi_df, on="Date", how="left")

        context_cols = []
        if trends_df is not None and not trends_df.empty:
            df = pd.merge(df, trends_df, on="Date", how="left")
            context_cols = [col for col in trends_df.columns if col != "Date"]

        # Create calendar features
        country_code = config["country_code"]
        period_days = config.get("period_days", 1)
        df = create_calendar_features(df, country_code=country_code, period_days=period_days)

        # Fill any remaining NaNs
        df = df.fillna(0)

    except Exception as e:
        log.error(
            f"   - ERROR: Failed to prepare data for Elasticity analysis. Details: {e}",
            exc_info=True,
        )
        return None

    kpi_col = "kpi"
    spend_cols = list(investment_pivot_df.columns)

    # Dynamic feature selection for the baseline (Stage 1)
    base_features = [
        col
        for col in df.columns
        if col.startswith("month_") or col in ["is_weekend", "is_payday_period", "is_holiday"] + context_cols
    ]

    # Filter out channels with zero investment
    active_spend_cols = [col for col in spend_cols if df[col].mean() > 0]
    inactive_spend_cols = [col for col in spend_cols if df[col].mean() == 0]

    if not active_spend_cols:
        log.error("   - ERROR: No marketing channels with active investment found.")
        return None

    log.info("   - Stage 1: Modeling Organic Baseline...")
    X_base = df[base_features]
    y_total = df[kpi_col]

    base_scaler = MinMaxScaler()
    X_base_scaled = base_scaler.fit_transform(X_base)

    # No positivity constraint here: calendar/context effects on the baseline can
    # legitimately be negative (weekends/holidays depressing the KPI). Forcing
    # positive coefficients pinned ~1/3 of them to exactly 0, so those depressing
    # effects leaked into the residual and were misattributed to marketing lift.
    # Positivity is kept only on the Stage-2 marketing model, where it belongs.
    base_model = Ridge(alpha=1.0).fit(X_base_scaled, y_total)
    df["kpi_organic_baseline"] = base_model.predict(X_base_scaled)

    # Lift = signed residual of the organic baseline. We deliberately do NOT
    # clip negatives to 0 anymore: the baseline (with intercept) passes through
    # the mean, so the residual is mean ~0. Clipping kept only the positive half
    # of that noise and handed it to the Stage-2 marketing model, manufacturing a
    # ~15% "marketing lift" even from pure noise (verified with a white-noise
    # control). Fitting Stage 2 on the signed residual instead reports the honest
    # net marketing contribution -- which can legitimately be near zero when the
    # data shows little measurable media effect. Stage 2 keeps positive-only
    # coefficients on non-negative features, so the total contribution stays >= 0.
    y_lift = y_total - df["kpi_organic_baseline"]

    log.info("   - Stage 2: Optimizing Marketing Response on Incremental Lift...")
    # Optimization Setup
    bounds = (
        [(0.0, 0.9)] * len(active_spend_cols)
        # Hill k capped at 1.0: k > 1 makes the curve S-shaped, with a convex
        # (accelerating-returns) region before its inflection point. For
        # channels with little independent spend variation, the optimizer
        # picked k near the old 5.0 ceiling and s far beyond real spend,
        # landing the whole historical range inside that convex region --
        # produced a response curve where marginal ROI *increased* with
        # budget (490x iROAS on a real project's Google Ads channel).
        # k <= 1 forces every channel concave (diminishing returns) from the
        # first dollar, which is the standard assumption for media response.
        + [(0.1, 1.0)] * len(active_spend_cols)
        # Hill s (inflection) bounded to the observed spend range, not mean*20.
        # Letting s balloon far past real spend (e.g. 1.6M when the channel never
        # spent near that) flattens the Hill curve into a straight line over the
        # whole data -- "saturation" stops being modeled at all. Capping s near
        # the historical max keeps the inflection inside the range the curve is
        # actually calibrated against.
        + [(df[col].mean() * 0.01, max(df[col].max() * 3, df[col].mean() * 2)) for col in active_spend_cols]
    )

    # Initial guesses
    initial_params = (
        [0.5] * len(active_spend_cols) + [1.0] * len(active_spend_cols) + [df[col].mean() for col in active_spend_cols]
    )

    # Run optimization from multiple starting points to avoid a bad local minimum.
    # n_restarts kept modest: the objective is now a walk-forward CV (k Ridge refits
    # per evaluation), so each restart is ~k times costlier than the old in-sample
    # objective. 3 restarts still clears the local-minimum regression test.
    result = optimize_with_restarts(
        elasticity_objective_function,
        initial_params,
        bounds,
        args=(df, y_lift, active_spend_cols),
        n_restarts=3,
    )

    if not result.success:
        log.warning(f"   - WARNING: Optimization did not converge fully. Details: {result.message}")

    optimal_params = result.x
    num_active_channels = len(active_spend_cols)
    final_alphas = optimal_params[:num_active_channels]
    final_ks = optimal_params[num_active_channels : 2 * num_active_channels]
    final_ss = optimal_params[2 * num_active_channels : 3 * num_active_channels]

    # Final Marketing Fit
    transformed_mkt = pd.DataFrame()
    for i, col in enumerate(active_spend_cols):
        adstocked_spend = geometric_adstock(df[col].values, final_alphas[i])
        saturated_spend = hill_transform(adstocked_spend, final_ks[i], final_ss[i])
        transformed_mkt[col] = saturated_spend

    mkt_scaler = MinMaxScaler()
    X_mkt_scaled = mkt_scaler.fit_transform(transformed_mkt)
    mkt_model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(X_mkt_scaled, y_lift)
    coef_samples = bootstrap_coefficients(X_mkt_scaled, y_lift)
    mkt_model.coef_ = coef_samples.mean(axis=0)

    y_mkt_pred = mkt_model.predict(X_mkt_scaled)
    final_r2 = r2_score(y_lift, y_mkt_pred)
    # Honest out-of-sample fit metric. In-sample R^2 flatters a flexible model;
    # cv_r2 <= 0 means the marketing model does not generalize (predicts the lift
    # worse than its own mean on held-out days) -- treat the mix/ROAS below as
    # unreliable when that happens.
    _, cv_r2 = walk_forward_cv_score(transformed_mkt, y_lift)
    log.info(f"   - Marketing Model R² (in-sample on lift): {final_r2:.4f}")
    log.info(f"   - Marketing Model R² (walk-forward CV): {cv_r2:.4f}")
    if cv_r2 <= 0:
        log.warning(
            "   - AVISO (baixa confianca): o modelo de marketing nao generaliza "
            "(R2 CV <= 0). A divisao de contribuicao e o mix recomendado abaixo "
            "tem confianca baixa -- ha pouco sinal de midia neste periodo."
        )

    # Calculate contribution breakdown
    contributions = {col: (mkt_model.coef_[i] * X_mkt_scaled[:, i]).sum() for i, col in enumerate(active_spend_cols)}
    for col in inactive_spend_cols:
        contributions[col] = 0.0

    total_marketing_contribution = sum(contributions.values())

    # Honest low-signal warning (replaces the old "fabricate a minimum attribution"
    # fallback). When the fitted contribution is a small fraction of the KPI, the
    # model genuinely found little measurable marketing effect -- previously the
    # code overrode the coefficients to force a >=5% attribution and lowered the
    # baseline to match, manufacturing a marketing signal from noise with no flag
    # to the user. We now let the honest (possibly small) number flow through and
    # just warn, so the downstream ROAS/mix numbers reflect what was actually
    # measured instead of a floor invented by the tool.
    min_marketing_pct = config["min_marketing_contribution"]
    if y_total.sum() > 0:
        measured_pct = total_marketing_contribution / y_total.sum()
        if measured_pct < min_marketing_pct:
            log.warning(
                f"   - AVISO (sinal fraco): contribuicao de marketing medida em "
                f"{measured_pct * 100:.1f}% do KPI (abaixo de {min_marketing_pct * 100:.0f}%). "
                "Os numeros de ROAS/mix abaixo tem baixa confianca -- o modelo "
                "encontrou pouco efeito de midia mensuravel neste periodo."
            )

    if total_marketing_contribution > 0:
        contribution_pct = {k: (v / total_marketing_contribution) * 100 for k, v in contributions.items()}
    else:
        contribution_pct = {k: 0.0 for k in contributions}

    log.info(
        f"   - Total Marketing Contribution: {total_marketing_contribution:,.2f} ({(total_marketing_contribution / y_total.sum()) * 100:.2f}% of Total)"
    )

    marketing_contribution_of_kpi_pct = (total_marketing_contribution / y_total.sum()) * 100 if y_total.sum() else 0.0

    return {
        "contribution_pct": contribution_pct,
        "r_squared": final_r2,
        "cv_r_squared": cv_r2,
        "cv_out_of_sample": cv_folds(len(y_lift)) >= 2,  # False: the CV above fell back to in-sample (A6)
        "marketing_contribution_of_kpi_pct": marketing_contribution_of_kpi_pct,
        "model": mkt_model,
        "coef_samples": coef_samples,  # (n_bootstrap, channels), scaled space: A5 CIs, A8 bands
        "channel_totals": X_mkt_scaled.sum(axis=0),  # coef × total = the channel's contribution over the period
        "scaler": mkt_scaler,
        "optimal_params": {"alphas": final_alphas, "ks": final_ks, "ss": final_ss},
        "spend_cols": active_spend_cols,
        "kpi_col": kpi_col,
        "dataframe": df,
        "organic_baseline_mean": df["kpi_organic_baseline"].mean(),
    }


def cap_channel_mix_share(mix, historical_mix, max_share):
    """Caps any channel's share of `mix` at `max_share`, redistributing the
    excess to the remaining channels weighted by their own share (falling
    back to `historical_mix`, then an even split, when every other channel
    is at zero). Guards against a single channel monopolizing the whole
    recommended mix under collinear spend data."""
    if max_share is None or max_share >= 1.0:
        return dict(mix)
    capped = cap_channel_share_per_channel(mix, {k: max_share for k in mix}, historical_mix)
    # too few channels for max_share to be feasible (2 channels, 40%): the cap gives, the budget is never dropped
    return fill_unallocated_share(capped, {k: 1.0 for k in mix})


def fill_unallocated_share(mix, ceilings):
    """Hands the share the caps left out back to the channels: first to those still under `ceilings`, in proportion to
    their headroom, then past the ceilings (pro rata to them) when the channels together cannot absorb it."""
    leftover = 1.0 - sum(mix.values())
    if leftover <= 1e-12:
        return mix
    headroom = {k: max(0.0, ceilings[k] - v) for k, v in mix.items()}
    room = sum(headroom.values())
    if room >= leftover:
        return {k: v + leftover * headroom[k] / room for k, v in mix.items()}
    full = {k: v + headroom[k] for k, v in mix.items()}
    total = sum(ceilings.values())
    weights = ceilings if total > 0 else {k: 1.0 for k in mix}
    total = total if total > 0 else len(mix)
    return {k: v + (leftover - room) * weights[k] / total for k, v in full.items()}


def cap_channel_share_per_channel(mix, per_channel_max_share, historical_mix):
    """Same redistribution algorithm as cap_channel_mix_share, generalized to
    a distinct ceiling per channel instead of one shared max_share.

    Needed because the SLSQP solve in optimize_spend_mix_for_budget only sees
    a *clipped* simulated response past each channel's per-channel spend cap
    (see _capped_channel_spend) -- the objective goes flat there, so nothing
    stops the optimizer from still reporting an allocation past that cap for
    a channel with no more gradient to follow. That nominal allocation then
    leaks into the UI (e.g. the individual response-curve chart's "Recomendado"
    line, drawn using this exact value, could land far to the right of where
    the plotted curve itself was capped and stops). Capping the *reported* mix
    here, not just the simulated response, keeps the two consistent."""
    capped = dict(mix)
    fixed = set()
    for _ in range(len(capped)):
        over = {k for k, v in capped.items() if k not in fixed and v > per_channel_max_share.get(k, 1.0)}
        if not over:
            break

        excess = sum(capped[k] - per_channel_max_share[k] for k in over)
        for k in over:
            capped[k] = per_channel_max_share[k]
            fixed.add(k)

        under_keys = [k for k in capped if k not in fixed]
        if not under_keys:
            break

        weights = {k: capped[k] for k in under_keys}
        if sum(weights.values()) <= 0:
            weights = {k: historical_mix.get(k, 0) for k in under_keys}
        if sum(weights.values()) <= 0:
            weights = {k: 1.0 for k in under_keys}

        total_weight = sum(weights.values())
        for k in under_keys:
            capped[k] += excess * (weights[k] / total_weight)

    return capped


def generate_aggregated_response_curve(
    elasticity_results, config, optimized_mix=None, output_dir=None, suppress_reallocation=False
):
    """
    Generates an aggregated response curve (Total Investment vs. Total KPI)
    based on the Two-Stage Elasticity model, scaling budget using the optimized mixes.
    `suppress_reallocation` (a channel the run cannot identify, A5) keeps the historical mix, as a weak CV does.
    """
    df = elasticity_results["dataframe"]
    active_spend_cols = elasticity_results["spend_cols"]
    opt_params = elasticity_results["optimal_params"]
    mkt_model = elasticity_results["model"]
    mkt_scaler = elasticity_results["scaler"]
    organic_baseline_mean = elasticity_results["organic_baseline_mean"]

    avg_daily_spend = {col: df[col].mean() for col in active_spend_cols}
    total_avg_daily_spend = sum(avg_daily_spend.values())
    historical_max_daily_spend = {col: df[col].max() for col in active_spend_cols}
    per_channel_limit_factor = config["per_channel_investment_limit_factor"]

    historical_mix = {
        col: avg_daily_spend[col] / total_avg_daily_spend if total_avg_daily_spend > 0 else 0
        for col in active_spend_cols
    }
    max_channel_mix_share = config["max_channel_mix_share"]
    if not optimized_mix:
        optimized_mix = historical_mix

    # When the marketing model has no out-of-sample signal (walk-forward CV R^2
    # <= 0) we must NOT recommend moving budget between channels: the "optimal"
    # reallocation is just the optimizer concentrating spend on whichever channel
    # won the corner solution on noise. On a real project this dressed a CV R^2
    # ~= 0 model up as a "+27% by reallocating" recommendation (42x iROAS). When
    # untrusted, the strategic mix collapses to the historical mix, so the curve
    # reflects only the effect of the total spend level, not a low-confidence
    # channel reshuffle. cv_r_squared falls back to r_squared for older callers.
    cv_r2 = elasticity_results.get("cv_r_squared", elasticity_results.get("r_squared", 0.0))
    # Bar is a *meaningful* out-of-sample fit, not merely > 0. Near-zero CV R^2
    # wobbles in the 0-0.05 range run to run (params sit on their bounds -- the
    # channels aren't identified), and a ">0" test would flip the recommendation
    # on and off on noise. Require the model to explain a real share of held-out
    # variance before trusting it to move budget between channels.
    trust_reallocation = trusts_reallocation(cv_r2, config) and not suppress_reallocation

    limit_factor = config["investment_limit_factor"]
    multipliers = np.linspace(0, limit_factor, 100)

    # Calculate steady-state adstock multipliers
    adstock_multipliers = {}
    for i, col in enumerate(active_spend_cols):
        dummy_spend = np.ones(30)
        adstocked = geometric_adstock(dummy_spend, opt_params["alphas"][i])
        adstock_multipliers[col] = adstocked[-1]

    def _capped_channel_spend(spend, col):
        # A channel's Hill curve is only calibrated up to what was actually
        # spent on it historically. Past that, `k`/`s` are extrapolation
        # guesses -- for a channel with little historical spend variation
        # they can land the curve still in its convex, accelerating-returns
        # ramp (real spend^k growth instead of saturating), which produced
        # an aggregate "response curve" where marginal ROI *increased* with
        # budget (490x iROAS on a real project's Google Ads channel).
        # Capping simulated spend per channel keeps every channel within a
        # range the model was actually fit against, independent of how much
        # headroom investment_limit_factor gives the aggregate budget.
        channel_cap = historical_max_daily_spend.get(col, 0) * per_channel_limit_factor
        return min(spend, channel_cap) if channel_cap > 0 else spend

    def simulate_kpi(total_spend, mix):
        mkt_features = []
        for i, col in enumerate(active_spend_cols):
            simulated_daily_spend = _capped_channel_spend(total_spend * mix.get(col, 0), col)
            simulated_adstocked = simulated_daily_spend * adstock_multipliers[col]
            mkt_features.append(hill_transform(simulated_adstocked, opt_params["ks"][i], opt_params["ss"][i]))
        return predict_clipped_kpi(organic_baseline_mean, mkt_model, mkt_scaler, mkt_features)

    coef_samples = elasticity_results["coef_samples"]
    total_history = df[active_spend_cols].sum(axis=1)
    total_range = (total_history.min(), total_history.max())
    channel_range = {col: (df[col].min(), df[col].max()) for col in active_spend_cols}

    def simulate_band(total_spend, mix):
        mkt_features = []
        for i, col in enumerate(active_spend_cols):
            simulated_daily_spend = _capped_channel_spend(total_spend * mix.get(col, 0), col)
            simulated_adstocked = simulated_daily_spend * adstock_multipliers[col]
            mkt_features.append(hill_transform(simulated_adstocked, opt_params["ks"][i], opt_params["ss"][i]))
        return kpi_band(organic_baseline_mean, coef_samples, mkt_scaler, mkt_features)

    def is_extrapolated(total_spend, mix):
        # outside the observed spend, total or any channel's share of it (A8)
        if not total_range[0] <= total_spend <= total_range[1]:
            return True
        return any(
            not channel_range[col][0] <= total_spend * mix.get(col, 0) <= channel_range[col][1]
            for col in active_spend_cols
        )

    def with_guardrails(point, mix):
        point["KPI_Lo"], point["KPI_Hi"] = simulate_band(point["Daily_Investment"], mix)
        point["Extrapolated"] = is_extrapolated(point["Daily_Investment"], mix)
        return point

    def optimize_spend_mix_for_budget(total_budget, previous_optimal_mix=None):
        if total_budget <= 0:
            return {col: 0.0 for col in active_spend_cols}
        if not trust_reallocation:
            # Low-confidence model: keep the historical mix (see trust_reallocation
            # note above) so no budget is reshuffled between channels on noise.
            return dict(historical_mix)

        def objective(spend_array):
            mkt_features = []
            for i, col in enumerate(active_spend_cols):
                simulated_adstocked = _capped_channel_spend(spend_array[i], col) * adstock_multipliers[col]
                mkt_features.append(hill_transform(simulated_adstocked, opt_params["ks"][i], opt_params["ss"][i]))
            return -predict_clipped_kpi(organic_baseline_mean, mkt_model, mkt_scaler, mkt_features)

        if previous_optimal_mix is None:
            init_guess = np.array([total_budget * historical_mix.get(col, 0) for col in active_spend_cols])
        else:
            init_guess = np.array([total_budget * previous_optimal_mix.get(col, 0) for col in active_spend_cols])

        bounds = [(0, total_budget) for _ in active_spend_cols]
        constraints = [{"type": "eq", "fun": lambda x: np.sum(x) - total_budget}]

        result = minimize(
            objective, init_guess, bounds=bounds, constraints=constraints, method="SLSQP", options={"disp": False}
        )

        optimal_spends = result.x if result.success else init_guess
        optimal_spends = np.maximum(0, optimal_spends)
        if np.sum(optimal_spends) > 0:
            optimal_spends = optimal_spends / np.sum(optimal_spends) * total_budget

        raw_mix = {col: optimal_spends[i] / total_budget for i, col in enumerate(active_spend_cols)}
        # Unconstrained, this SLSQP solve routinely hands 100% of the budget to
        # whichever channel has the best marginal efficiency at this spend level
        # (a real optimum for a linear-in-coefficients objective, not a fluke) --
        # the same single-channel collapse cap_channel_mix_share already guards
        # against for the static strategic_mix. Apply it here too so the dynamic,
        # per-budget-level mix can't collapse to one channel either.
        #
        # Combine that 40%-of-mix cap with each channel's own absolute-spend
        # cap (as a fraction of this specific total_budget) into one ceiling
        # per channel, whichever is tighter -- _capped_channel_spend already
        # makes the simulated response flat past the absolute cap, but doesn't
        # stop the optimizer from still *reporting* an allocation past it (see
        # cap_channel_share_per_channel's docstring).
        absolute_share = {
            col: historical_max_daily_spend.get(col, 0) * per_channel_limit_factor / total_budget
            for col in active_spend_cols
        }
        # the caps never drop budget (audit F6): past an infeasible share cap the channels' absolute caps take it, and
        # past those the spend goes where the response is flat, in rows is_extrapolated already flags
        share_cap = max(max_channel_mix_share, 1.0 / len(active_spend_cols))
        per_channel_max_share = {col: min(share_cap, absolute_share[col]) for col in active_spend_cols}
        capped = cap_channel_share_per_channel(raw_mix, per_channel_max_share, historical_mix)
        return fill_unallocated_share(capped, absolute_share)

    # --- NEW: Strategic Reallocation (Same Baseline Budget, Dynamically Optimized Elasticity Mix) ---
    reallocated_optimal_mix = optimize_spend_mix_for_budget(total_avg_daily_spend, previous_optimal_mix=historical_mix)
    reallocated_kpi = simulate_kpi(total_avg_daily_spend, reallocated_optimal_mix)

    # Baseline using Historical Mix
    baseline_kpi = simulate_kpi(total_avg_daily_spend, historical_mix)
    baseline_point = {
        "Scenario": "Cenário Atual",
        "Daily_Investment": total_avg_daily_spend,
        "Projected_Total_KPIs": baseline_kpi,
        "projected_kpis": {
            "Média Histórica": baseline_kpi,
            "Pico de Eficiência": simulate_kpi(total_avg_daily_spend, optimized_mix),
            "Modelo de Elasticidade": reallocated_kpi,
        },
    }

    # Generate curve using the Dynamic Strategic Mix (Elasticity optimal path)
    simulation_results = []
    last_optimal_mix = reallocated_optimal_mix

    for m in multipliers:
        current_total_daily_spend = total_avg_daily_spend * m

        if current_total_daily_spend == 0:
            current_optimal_mix = {col: 0.0 for col in active_spend_cols}
        else:
            current_optimal_mix = optimize_spend_mix_for_budget(
                current_total_daily_spend, previous_optimal_mix=last_optimal_mix
            )
            last_optimal_mix = current_optimal_mix

        total_kpi_daily = simulate_kpi(current_total_daily_spend, current_optimal_mix)
        historical_kpi_daily = simulate_kpi(current_total_daily_spend, historical_mix)
        optimized_kpi_daily = simulate_kpi(current_total_daily_spend, optimized_mix)

        res_dict = {
            "Daily_Investment": current_total_daily_spend,
            "Projected_Total_KPIs": total_kpi_daily,
            "Projected_Total_KPIs_Historical": historical_kpi_daily,
            "Projected_Total_KPIs_Optimized": optimized_kpi_daily,
        }
        res_dict["KPI_Lo"], res_dict["KPI_Hi"] = simulate_band(current_total_daily_spend, current_optimal_mix)
        res_dict["Extrapolated"] = is_extrapolated(current_total_daily_spend, current_optimal_mix)

        for ch in active_spend_cols:
            res_dict[f"Spend_{ch}_Historical"] = current_total_daily_spend * historical_mix.get(ch, 0)
            res_dict[f"Spend_{ch}_Optimized"] = current_total_daily_spend * optimized_mix.get(ch, 0)
            res_dict[f"Spend_{ch}_Strategic"] = current_total_daily_spend * current_optimal_mix.get(ch, 0)

        simulation_results.append(res_dict)

    res_df = pd.DataFrame(simulation_results)
    # increments are measured on the curve itself (its mix at today's budget): the gain of reallocating today's
    # budget is the strategic_reallocation scenario, not a return on extra budget (audit F4)
    res_df["Incremental_KPI"] = (res_df["Projected_Total_KPIs"] - reallocated_kpi).clip(lower=0)
    res_df["Incremental_Investment"] = (res_df["Daily_Investment"] - total_avg_daily_spend).clip(lower=0)

    optimization_target = config["optimization_target"].upper()
    financial_targets = config["financial_targets"]

    kpi_is_monetary = config["kpi_is_monetary"]
    # ponytail: when the KPI is already money, revenue = kpi (multiplier=1), no
    # count-to-revenue conversion applies, regardless of optimization_target.
    conversion_rate = 1.0 if kpi_is_monetary else config["conversion_rate_from_kpi_to_bo"]
    avg_ticket = 1.0 if kpi_is_monetary else config["average_ticket"]
    revenue_mode = kpi_is_monetary or optimization_target == "REVENUE"
    if kpi_is_monetary and optimization_target == "CONVERSIONS":
        log.warning(
            "   - AVISO (config): optimization_target='CONVERSIONS' foi ignorado "
            "porque kpi_is_monetary=true (o KPI ja e R$), entao o modo receita/ROAS "
            "esta em uso. Se o KPI for uma contagem (leads/vendas em unidades, nao "
            "R$), desmarque 'KPI ja esta em R$' no setup; senao, defina o alvo como "
            "RECEITA para remover a contradicao."
        )
    baseline_revenue = baseline_kpi * conversion_rate * avg_ticket
    res_df["Projected_Revenue"] = res_df["Projected_Total_KPIs"] * conversion_rate * avg_ticket
    res_df["Incremental_Revenue"] = res_df["Projected_Revenue"] - reallocated_kpi * conversion_rate * avg_ticket
    res_df["Incremental_ROI"] = (res_df["Incremental_Revenue"] / res_df["Incremental_Investment"]).fillna(0)

    res_df["iCPA"] = (res_df["Incremental_Investment"] / res_df["Incremental_KPI"]).fillna(0)
    res_df["iCPA"] = res_df["iCPA"].replace([np.inf, -np.inf], np.nan)

    # Max Efficiency Point: the knee of the curve in both modes. On a concave curve the best average iROAS from
    # today's spend is always the first grid point above it, so revenue mode answered "spend 2% more" (audit F5).
    curve_segment = res_df[res_df["Daily_Investment"] >= total_avg_daily_spend].copy()
    if len(curve_segment) > 5:
        x = curve_segment["Daily_Investment"].values
        y = curve_segment["Projected_Total_KPIs"].values
        x_norm = (x - x.min()) / (x.max() - x.min() + 1e-9)
        y_norm = (y - y.min()) / (y.max() - y.min() + 1e-9)
        distances = np.abs(y_norm - x_norm) / np.sqrt(2)
        max_eff_investment = x[np.argmax(distances)]
    else:
        max_eff_investment = total_avg_daily_spend

    # Evaluate Max Efficiency Point using its specific Optimized Mix! Its increment is on that same mix (audit F4).
    opt_kpi = simulate_kpi(max_eff_investment, optimized_mix)
    today_optimized_kpi = simulate_kpi(total_avg_daily_spend, optimized_mix)
    inc_opt_kpi = max(0, opt_kpi - today_optimized_kpi)
    inc_opt_inv = max(0, max_eff_investment - total_avg_daily_spend)

    eff_optimal_mix = optimize_spend_mix_for_budget(max_eff_investment, previous_optimal_mix=reallocated_optimal_mix)
    max_efficiency_point = {
        "Scenario": "Máxima Eficiência",
        "Daily_Investment": max_eff_investment,
        "Projected_Total_KPIs": opt_kpi,
        "Incremental_Investment": inc_opt_inv,
        "Incremental_KPI": inc_opt_kpi,
        "projected_kpis": {
            "Média Histórica": simulate_kpi(max_eff_investment, historical_mix),
            "Pico de Eficiência": opt_kpi,
            "Modelo de Elasticidade": simulate_kpi(max_eff_investment, eff_optimal_mix),
        },
    }
    if revenue_mode:
        max_efficiency_point["Projected_Revenue"] = opt_kpi * conversion_rate * avg_ticket
        max_efficiency_point["Incremental_Revenue"] = max(
            0, max_efficiency_point["Projected_Revenue"] - today_optimized_kpi * conversion_rate * avg_ticket
        )
        max_efficiency_point["Incremental_ROI"] = (
            max_efficiency_point["Incremental_Revenue"] / inc_opt_inv if inc_opt_inv > 0 else 0
        )

    strategic_reallocation_point = {
        "Scenario": "Realocação Estratégica",
        "Daily_Investment": total_avg_daily_spend,
        "Projected_Total_KPIs": reallocated_kpi,
        "Incremental_Investment": 0,
        "Incremental_KPI": max(0, reallocated_kpi - baseline_kpi),
        "iCPA": 0,
        "projected_kpis": {
            "Média Histórica": baseline_kpi,
            "Pico de Eficiência": simulate_kpi(total_avg_daily_spend, optimized_mix),
            "Modelo de Elasticidade": reallocated_kpi,
        },
    }
    if revenue_mode:
        strategic_reallocation_point["Projected_Revenue"] = reallocated_kpi * conversion_rate * avg_ticket
        strategic_reallocation_point["Incremental_Revenue"] = max(
            0, strategic_reallocation_point["Projected_Revenue"] - baseline_revenue
        )
        inc_rev = strategic_reallocation_point["Incremental_Revenue"]
        strategic_reallocation_point["Incremental_ROI"] = float("inf") if inc_rev > 0 else 0

    # --- UNIVERSAL FINANCIAL FILTER LOGIC START ---
    strategic_limit_point = None

    max_cpa = financial_targets.get("target_cpa", float("inf"))
    max_icpa = financial_targets.get("target_icpa", float("inf"))
    min_roas = financial_targets.get("target_roas", 0)
    min_iroas = financial_targets.get("target_iroas", config["minimum_acceptable_iroi"])

    valid_points_df = res_df[res_df["Daily_Investment"] > total_avg_daily_spend].copy()

    if not kpi_is_monetary and (
        optimization_target == "CONVERSIONS" or max_cpa != float("inf") or max_icpa != float("inf")
    ):
        if "CPA" not in valid_points_df.columns:
            valid_points_df["CPA"] = (
                valid_points_df["Daily_Investment"] / valid_points_df["Projected_Total_KPIs"]
            ).fillna(0)
        if max_cpa != float("inf"):
            valid_points_df = valid_points_df[valid_points_df["CPA"] <= max_cpa]
        if max_icpa != float("inf"):
            valid_points_df = valid_points_df[(valid_points_df["iCPA"] > 0) & (valid_points_df["iCPA"] <= max_icpa)]

    # outside revenue mode revenue needs no ticket (0 by default) and ROAS targets would reject every point, as
    # analysis.run_opportunity_projection already knows (audit F3)
    if revenue_mode:
        if "ROAS" not in valid_points_df.columns and "Projected_Revenue" in valid_points_df.columns:
            valid_points_df["ROAS"] = (
                valid_points_df["Projected_Revenue"] / valid_points_df["Daily_Investment"]
            ).fillna(0)
        if min_roas > 0 and "ROAS" in valid_points_df.columns:
            valid_points_df = valid_points_df[valid_points_df["ROAS"] >= min_roas]
        if min_iroas > 0 and "Incremental_ROI" in valid_points_df.columns:
            valid_points_df = valid_points_df[valid_points_df["Incremental_ROI"] >= min_iroas]

    if not valid_points_df.empty:
        strategic_limit_idx = valid_points_df["Daily_Investment"].idxmax()
        strategic_limit_point = res_df.loc[strategic_limit_idx].to_dict()
    # --- UNIVERSAL FINANCIAL FILTER LOGIC END ---

    if strategic_limit_point is None:
        # no budget above today's meets the targets: stay where we are, never "spend the most" (audit F3)
        strategic_limit_point = {
            "Daily_Investment": total_avg_daily_spend,
            "Projected_Total_KPIs": baseline_kpi,
            "Incremental_Investment": 0,
            "Incremental_KPI": 0,
            **{f"Spend_{col}_Strategic": avg_daily_spend[col] for col in active_spend_cols},
            "Reasons": ["targets_unreachable"],
        }
        with_guardrails(strategic_limit_point, historical_mix)

    strategic_limit_point["Scenario"] = "Limite Estratégico"
    strategic_limit_inv = strategic_limit_point["Daily_Investment"]
    limit_optimal_mix = optimize_spend_mix_for_budget(strategic_limit_inv, previous_optimal_mix=reallocated_optimal_mix)
    strategic_limit_point["projected_kpis"] = {
        "Média Histórica": simulate_kpi(strategic_limit_inv, historical_mix),
        "Pico de Eficiência": simulate_kpi(strategic_limit_inv, optimized_mix),
        "Modelo de Elasticidade": simulate_kpi(strategic_limit_inv, limit_optimal_mix),
    }

    # NEW: Export the DataFrame to a CSV so Streamlit can use it for interactability
    if output_dir:  # Only export if output_dir is provided
        csv_out_path = os.path.join(output_dir, "response_curve_data.csv")
        res_df.to_csv(csv_out_path, index=False)
        log.info(f"   - Simulation data exported for UI: {csv_out_path}")

        # Persist the confidence signal so the dashboard can surface it (the CSV
        # only carries the curve, not the model's out-of-sample quality). When
        # low_confidence is true the reallocation was already suppressed above,
        # so the UI just needs to warn that the projection is directional.
        metrics_out = {
            "cv_r_squared": float(cv_r2),
            "r_squared": float(elasticity_results.get("r_squared", 0.0)),
            "marketing_contribution_of_kpi_pct": float(
                elasticity_results.get("marketing_contribution_of_kpi_pct", 0.0)
            ),
            "low_confidence": bool(not trusts_reallocation(cv_r2, config)),
            "reallocation_suppressed": bool(not trust_reallocation),
        }
        with open(
            os.path.join(output_dir, "global_saturation_metrics.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(metrics_out, f, ensure_ascii=False, indent=2)

    with_guardrails(baseline_point, historical_mix)
    with_guardrails(max_efficiency_point, optimized_mix)
    with_guardrails(strategic_reallocation_point, reallocated_optimal_mix)

    return (
        res_df,
        baseline_point,
        max_efficiency_point,
        strategic_limit_point,
        None,
        None,
        strategic_reallocation_point,
    )


def generate_individual_response_curves(elasticity_results, config, output_dir=None, strategic_limit_point=None):
    """
    Generates individual response curves for each channel (Spend vs. KPI)
    holding other channels at their historical average.
    """
    df = elasticity_results["dataframe"]
    active_spend_cols = elasticity_results["spend_cols"]
    opt_params = elasticity_results["optimal_params"]
    mkt_model = elasticity_results["model"]
    mkt_scaler = elasticity_results["scaler"]
    organic_baseline_mean = elasticity_results["organic_baseline_mean"]

    avg_daily_spend = {col: df[col].mean() for col in active_spend_cols}
    historical_max_daily_spend = {col: df[col].max() for col in active_spend_cols}
    per_channel_limit_factor = config["per_channel_investment_limit_factor"]
    coef_samples = elasticity_results["coef_samples"]
    historical_min_daily_spend = {col: df[col].min() for col in active_spend_cols}

    # Calculate steady-state adstock multipliers
    adstock_multipliers = {}
    for i, col in enumerate(active_spend_cols):
        dummy_spend = np.ones(30)
        adstocked = geometric_adstock(dummy_spend, opt_params["alphas"][i])
        adstock_multipliers[col] = adstocked[-1]

    limit_factor = config["investment_limit_factor"]

    individual_curves = []

    for target_channel in active_spend_cols:
        target_avg_spend = avg_daily_spend[target_channel]
        max_spend = target_avg_spend * limit_factor
        rec_spend = None
        if strategic_limit_point:
            rec_spend = strategic_limit_point.get(f"Spend_{target_channel}_Strategic", None)
            if rec_spend is not None:
                max_spend = max(max_spend, rec_spend * 1.2)  # Give some padding

        # A8: the curve never passes the range the Hill fit is trusted in, not even to reach the recommended spend
        channel_cap = historical_max_daily_spend.get(target_channel, 0) * per_channel_limit_factor
        if channel_cap > 0:
            max_spend = min(max_spend, channel_cap)

        spend_points = np.linspace(0, max_spend, 100)

        for spend in spend_points:
            mkt_features = []
            for i, col in enumerate(active_spend_cols):
                if col == target_channel:
                    simulated_daily_spend = spend
                else:
                    simulated_daily_spend = avg_daily_spend[col]

                simulated_adstocked = simulated_daily_spend * adstock_multipliers[col]
                mkt_features.append(hill_transform(simulated_adstocked, opt_params["ks"][i], opt_params["ss"][i]))

            predicted_kpi = predict_clipped_kpi(organic_baseline_mean, mkt_model, mkt_scaler, mkt_features)
            kpi_lo, kpi_hi = kpi_band(organic_baseline_mean, coef_samples, mkt_scaler, mkt_features)
            observed = historical_min_daily_spend[target_channel] <= spend <= historical_max_daily_spend[target_channel]
            individual_curves.append(
                {
                    "Channel": target_channel,
                    "Channel_Spend": spend,
                    "Projected_Total_KPIs": predicted_kpi,
                    "Historical_Avg": target_avg_spend,
                    "Recommended": rec_spend,
                    "KPI_Lo": kpi_lo,
                    "KPI_Hi": kpi_hi,
                    "Extrapolated": not observed,
                }
            )

    all_curves_df = pd.DataFrame(individual_curves)

    if output_dir:
        csv_out_path = os.path.join(output_dir, "individual_response_curves_data.csv")
        all_curves_df.to_csv(csv_out_path, index=False)
        log.info(f"   - Individual simulation data exported for UI: {csv_out_path}")

        # --- Plotting Logic (One per channel) ---
        for channel in active_spend_cols:
            plt.figure(figsize=(10, 6))
            channel_data = all_curves_df[all_curves_df["Channel"] == channel]
            plt.plot(
                channel_data["Channel_Spend"],
                channel_data["Projected_Total_KPIs"],
                label=channel,
                color="blue",
            )

            # Flag Historical Average
            hist_spend = avg_daily_spend[channel]
            plt.axvline(
                x=hist_spend,
                color="gray",
                linestyle="--",
                label=f"Historical Avg (R$ {hist_spend:,.2f})",
            )

            # Flag Recommended Point (Strategic Limit)
            if strategic_limit_point:
                rec_spend = strategic_limit_point.get(f"Spend_{channel}_Strategic", None)
                if rec_spend is not None:
                    plt.axvline(
                        x=rec_spend,
                        color="red",
                        linestyle="--",
                        label=f"Recommended (R$ {rec_spend:,.2f})",
                    )

            plt.xlabel("Daily Investment")
            plt.ylabel("Projected Total Daily KPIs")
            plt.title(f"Response Curve: {channel}")
            plt.legend()
            plt.grid(True)

            # Sanitize channel name for filename
            safe_channel_name = "".join([c if c.isalnum() or c in ["-", "_"] else "_" for c in channel])
            plot_out_path = os.path.join(output_dir, f"individual_response_curve_{safe_channel_name}.png")
            plt.savefig(plot_out_path)
            plt.close()
            log.info(f"   - Individual curve plot saved for {channel}: {plot_out_path}")

    return all_curves_df
