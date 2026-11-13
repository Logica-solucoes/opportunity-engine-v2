import time
import unittest

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import Ridge

from engine.elasticity_analysis import (
    _media_ridge,
    bootstrap_coefficients,
    cap_channel_mix_share,
    cap_channel_share_per_channel,
    create_calendar_features,
    fit_media_params,
    optimize_with_restarts,
    predict_clipped_kpi,
    walk_forward_cv_score,
)
from tests.engine.helpers import full_config


class TestCapChannelMixShare(unittest.TestCase):
    def test_caps_dominant_channel_and_redistributes_by_historical_mix(self):
        mix = {"SKYSCANNER": 1.0, "GOOGLE": 0.0, "BING": 0.0}
        historical_mix = {"SKYSCANNER": 0.34, "GOOGLE": 0.5, "BING": 0.16}

        capped = cap_channel_mix_share(mix, historical_mix, max_share=0.4)

        self.assertAlmostEqual(capped["SKYSCANNER"], 0.4)
        self.assertAlmostEqual(sum(capped.values()), 1.0)
        # Excess (0.6) redistributed proportional to historical mix (GOOGLE 0.5 vs BING 0.16)
        self.assertGreater(capped["GOOGLE"], capped["BING"])

    def test_no_channel_ends_up_over_cap_with_four_channels(self):
        # Regression: with >=2 channels needing redistribution, GOOGLE's own
        # share (whatever it settles at after receiving BING's excess) used
        # to be eligible to receive *more* excess in the next loop pass
        # (nothing permanently excluded a just-capped channel), overshooting
        # the cap itself. Reproduces the real response-curve data where this
        # left two of four channels above 40% instead of the dominant one.
        mix = {"BING": 1.0, "FACEBOOK": 0.0, "GOOGLE": 0.0, "PMAX": 0.0}
        historical_mix = {"BING": 0.06, "FACEBOOK": 0.85, "GOOGLE": 0.03, "PMAX": 0.06}

        capped = cap_channel_mix_share(mix, historical_mix, max_share=0.4)

        for channel, share in capped.items():
            self.assertLessEqual(share, 0.4 + 1e-9, f"{channel} exceeded the cap")
        self.assertAlmostEqual(sum(capped.values()), 1.0)

    def test_leaves_mix_untouched_when_no_channel_exceeds_cap(self):
        mix = {"A": 0.4, "B": 0.35, "C": 0.25}
        capped = cap_channel_mix_share(mix, historical_mix={}, max_share=0.5)
        self.assertEqual(capped, mix)

    def test_falls_back_to_even_split_when_no_signal_at_all(self):
        mix = {"A": 1.0, "B": 0.0, "C": 0.0}
        capped = cap_channel_mix_share(mix, historical_mix={"A": 0, "B": 0, "C": 0}, max_share=0.5)
        self.assertAlmostEqual(capped["A"], 0.5)
        self.assertAlmostEqual(capped["B"], 0.25)
        self.assertAlmostEqual(capped["C"], 0.25)

    def test_disabled_when_max_share_is_none_or_one(self):
        mix = {"A": 1.0, "B": 0.0}
        self.assertEqual(cap_channel_mix_share(mix, {}, None), mix)
        self.assertEqual(cap_channel_mix_share(mix, {}, 1.0), mix)


class TestCapChannelSharePerChannel(unittest.TestCase):
    def test_caps_each_channel_at_its_own_ceiling(self):
        # BING has a much tighter ceiling than FACEBOOK -- e.g. it's derived
        # from a much smaller historical spend range for that channel.
        mix = {"BING": 0.9, "FACEBOOK": 0.1}
        per_channel_max_share = {"BING": 0.1, "FACEBOOK": 0.9}

        capped = cap_channel_share_per_channel(mix, per_channel_max_share, historical_mix={})

        self.assertAlmostEqual(capped["BING"], 0.1)
        self.assertAlmostEqual(capped["FACEBOOK"], 0.9)
        self.assertAlmostEqual(sum(capped.values()), 1.0)

    def test_no_channel_ends_up_over_its_own_cap_with_four_channels(self):
        # Regression mirror of the cap_channel_mix_share fix: a channel
        # sitting exactly at its ceiling must not be handed more excess in a
        # later redistribution pass and pushed back over it.
        mix = {"BING": 1.0, "FACEBOOK": 0.0, "GOOGLE": 0.0, "PMAX": 0.0}
        per_channel_max_share = {"BING": 0.05, "FACEBOOK": 0.9, "GOOGLE": 0.4, "PMAX": 0.4}
        historical_mix = {"BING": 0.06, "FACEBOOK": 0.85, "GOOGLE": 0.03, "PMAX": 0.06}

        capped = cap_channel_share_per_channel(mix, per_channel_max_share, historical_mix)

        for channel, share in capped.items():
            self.assertLessEqual(share, per_channel_max_share[channel] + 1e-9, f"{channel} exceeded its cap")
        self.assertAlmostEqual(sum(capped.values()), 1.0)

    def test_leaves_mix_untouched_when_no_channel_exceeds_its_cap(self):
        mix = {"A": 0.4, "B": 0.35, "C": 0.25}
        capped = cap_channel_share_per_channel(mix, {"A": 0.5, "B": 0.5, "C": 0.5}, historical_mix={})
        self.assertEqual(capped, mix)


def two_basin_objective(params, _):
    """Toy non-convex objective with a shallow local minimum near x=1 (value 0.5)
    and a deeper global minimum near x=8 (value 0), used to prove multi-start
    escapes a bad local minimum a single start would get stuck in."""
    x = params[0]
    return min((x - 1) ** 2 + 0.5, (x - 8) ** 2)


class TestOptimizeWithRestarts(unittest.TestCase):
    def test_finds_better_minimum_than_a_single_bad_start(self):
        bounds = [(0.0, 10.0)]
        bad_start = [1.0]

        single_start_result = minimize(two_basin_objective, bad_start, args=(None,), bounds=bounds, method="L-BFGS-B")
        multi_start_result = optimize_with_restarts(
            two_basin_objective, bad_start, bounds, args=(None,), n_restarts=5, seed=42
        )

        self.assertLess(multi_start_result.fun, single_start_result.fun)
        self.assertAlmostEqual(multi_start_result.fun, 0.0, places=4)

    def test_reproducible_with_a_fixed_seed(self):
        bounds = [(0.0, 10.0)]
        result_a = optimize_with_restarts(two_basin_objective, [1.0], bounds, args=(None,), n_restarts=5, seed=42)
        result_b = optimize_with_restarts(two_basin_objective, [1.0], bounds, args=(None,), n_restarts=5, seed=42)
        self.assertEqual(result_a.fun, result_b.fun)

    def test_a_passed_deadline_stops_after_one_iteration_and_keeps_the_best_point(self):
        with self.assertLogs("engine.elasticity_analysis", level="WARNING") as logs:
            result = optimize_with_restarts(
                two_basin_objective, [1.0], [(0.0, 10.0)], args=(None,), n_restarts=5, deadline=time.monotonic() - 1
            )
        self.assertLessEqual(result.nit, 1)
        self.assertTrue(np.isfinite(result.fun))
        self.assertIn("deadline", "\n".join(logs.output))


class TestMediaRidge(unittest.TestCase):
    def test_reaches_the_exact_positive_ridge_optimum(self):
        # 46 correlated channels: sklearn's positive Ridge stops short of the optimum here (relative gradient 4e-3 on its
        # free coefficients), which made the Stage 2 objective noisy and hung the MMM on a 46-channel client
        rng = np.random.default_rng(0)
        base = rng.uniform(0, 1, (1000, 1))
        X = np.clip(base + rng.normal(0, 0.3, (1000, 46)), 0, None)
        y = X[:, :10] @ rng.uniform(50, 500, 10) - X[:, 10:15] @ rng.uniform(50, 500, 5) + rng.normal(0, 100, 1000)

        model = _media_ridge().fit(X, y)

        # KKT of min |yc - Xc w|² + |w|², w >= 0: zero gradient on the free coefficients, non-negative on the bound ones
        Xc, yc = X - X.mean(axis=0), y - y.mean()
        grad = 2 * (Xc.T @ (Xc @ model.coef_ - yc) + model.coef_)
        scale = np.abs(2 * Xc.T @ yc).max()
        free = model.coef_ > 0
        self.assertTrue((model.coef_ >= 0).all())
        self.assertTrue(free.any())
        self.assertLess(np.abs(grad[free]).max() / scale, 1e-8)
        self.assertGreater(grad[~free].min(initial=0) / scale, -1e-8)
        self.assertAlmostEqual(model.intercept_, y.mean() - X.mean(axis=0) @ model.coef_)
        np.testing.assert_allclose(model.predict(X), X @ model.coef_ + model.intercept_)


class TestFitMediaParamsScale(unittest.TestCase):
    def test_46_channels_finish_well_inside_the_worker_watchdog(self):
        rng = np.random.default_rng(1)
        n_rows, n_channels = 1000, 46
        spend = pd.DataFrame(
            rng.gamma(0.5, 1000, (n_rows, n_channels)) * (rng.uniform(0, 1, (n_rows, n_channels)) < 0.3),
            columns=[f"C{i}" for i in range(n_channels)],
        )
        lift = spend.iloc[:, :4].sum(axis=1).to_numpy() * 0.01 + rng.normal(0, 5, n_rows)

        start = time.monotonic()
        fit_media_params(spend, lift - lift.mean(), deadline=start + 120)

        self.assertLess(time.monotonic() - start, 150)


class TestBootstrapCoefficients(unittest.TestCase):
    def test_recovers_a_zeroed_channels_true_contribution(self):
        # Two highly correlated columns (corr ~0.99) that BOTH truly drive y
        # (70/30 split). A single positive-constrained Ridge fit on the full
        # data hands 100% of the credit to column A and zeroes column B -- a
        # stable corner solution caused by the collinearity, not a fluke.
        rng = np.random.default_rng(5)
        n = 60
        a = rng.uniform(1, 10, n)
        b = np.clip(a + rng.normal(0, 0.5, n), 0.1, None)
        X = np.column_stack([a, b])
        y = 0.7 * a + 0.3 * b + rng.normal(0, 2.0, n)

        single_fit = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(X, y)
        self.assertEqual(single_fit.coef_[1], 0.0)

        boot_coef = bootstrap_coefficients(X, y, n_bootstrap=300, seed=42)[0].mean(axis=0)
        self.assertGreater(boot_coef[1], 0.0)

    def test_reproducible_with_a_fixed_seed(self):
        rng = np.random.default_rng(1)
        X = rng.uniform(1, 10, (40, 2))
        y = X[:, 0] + X[:, 1] + rng.normal(0, 1.0, 40)

        coefs_a, intercepts_a = bootstrap_coefficients(X, y, n_bootstrap=50, seed=7)
        coefs_b, intercepts_b = bootstrap_coefficients(X, y, n_bootstrap=50, seed=7)
        np.testing.assert_array_equal(coefs_a, coefs_b)
        np.testing.assert_array_equal(intercepts_a, intercepts_b)

    def test_blocks_of_one_row_are_the_iid_row_bootstrap(self):
        rng = np.random.default_rng(1)
        X = rng.uniform(1, 10, (40, 3))
        y = X @ np.array([1.0, 0.5, 0.0]) + rng.normal(0, 1.0, 40)
        loop_rng = np.random.default_rng(5)
        coefs = np.zeros((30, 3))
        for b in range(30):
            idx = loop_rng.integers(0, 40, 40)
            coefs[b] = _media_ridge().fit(X[idx], y[idx]).coef_

        np.testing.assert_array_equal(bootstrap_coefficients(X, y, n_bootstrap=30, seed=5, block=1)[0], coefs)

    def test_returns_one_row_per_resample(self):
        rng = np.random.default_rng(2)
        X = rng.uniform(1, 10, (30, 3))
        y = X.sum(axis=1)

        samples, intercepts = bootstrap_coefficients(X, y, n_bootstrap=20, seed=1)

        self.assertEqual(samples.shape, (20, 3))
        self.assertEqual(intercepts.shape, (20,))
        self.assertTrue((samples >= 0).all())  # positive Ridge


class FakeScaler:
    """Replicates MinMaxScaler's un-clipped affine transform for a column whose
    historical range was [100, 200], without depending on sklearn internals."""

    def transform(self, X):
        return np.array([[(row[0] - 100.0) / (200.0 - 100.0)] for row in X])


class FakeModel:
    """Replicates a fitted single-feature linear model with coefficient 10."""

    def predict(self, X):
        return np.array([10.0 * row[0] for row in X])


class TestPredictClippedKpi(unittest.TestCase):
    def test_clips_extrapolated_feature_instead_of_going_negative(self):
        # Simulated spend of 0 is below the historical minimum (100), which would
        # scale to -1.0 without clipping -> KPI 10 below baseline. Clipped to 0,
        # it should contribute nothing, landing exactly on the baseline.
        predicted = predict_clipped_kpi(500.0, FakeModel(), FakeScaler(), [0.0])
        self.assertEqual(predicted, 500.0)

    def test_leaves_in_range_values_unaffected(self):
        # Spend of 150 scales to 0.5, well within [0, 1] -- clip is a no-op.
        predicted = predict_clipped_kpi(500.0, FakeModel(), FakeScaler(), [150.0])
        self.assertEqual(predicted, 505.0)

    def test_does_not_flatten_extrapolation_above_historical_max(self):
        # Spend of 400 is well above the historical max (200) -> scales to 3.0.
        # The Hill feature itself is still finite and below its own asymptote
        # at this spend, so the upper bound must stay unclipped: two spend
        # levels above the historical max should still predict different KPIs,
        # not collapse to the same flat value.
        predicted_300 = predict_clipped_kpi(500.0, FakeModel(), FakeScaler(), [300.0])
        predicted_400 = predict_clipped_kpi(500.0, FakeModel(), FakeScaler(), [400.0])
        self.assertNotEqual(predicted_300, predicted_400)
        self.assertGreater(predicted_400, predicted_300)


class TestReallocationSuppression(unittest.TestCase):
    """The money-critical guardrail: a low-confidence model must NOT recommend
    moving budget between channels (Projected == Historical projection)."""

    def _make_results(self, cv_r2):
        from sklearn.linear_model import Ridge
        from sklearn.preprocessing import MinMaxScaler

        from engine.elasticity_analysis import geometric_adstock, hill_transform

        rng = np.random.default_rng(0)
        n = 120
        a = rng.uniform(100, 200, n)
        b = rng.uniform(100, 200, n)
        kpi = 1000 + 5 * a + 1 * b + rng.normal(0, 10, n)  # A far more efficient
        df = pd.DataFrame({"A": a, "B": b, "kpi": kpi})
        df["kpi_organic_baseline"] = 1000.0
        params = {"alphas": [0.0, 0.0], "ks": [1.0, 1.0], "ss": [150.0, 150.0]}
        tdf = pd.DataFrame()
        for i, c in enumerate(["A", "B"]):
            ad = geometric_adstock(df[c].values, params["alphas"][i])
            tdf[c] = hill_transform(ad, params["ks"][i], params["ss"][i])
        # fit on .values (no feature names) -- the engine feeds the scaler plain
        # lists at simulate time, so a name-carrying scaler just spams warnings.
        scaler = MinMaxScaler().fit(tdf.values)
        y = df["kpi"] - df["kpi_organic_baseline"]
        model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(scaler.transform(tdf.values), y)
        return {
            "dataframe": df,
            "spend_cols": ["A", "B"],
            "optimal_params": params,
            "model": model,
            "scaler": scaler,
            "organic_baseline_mean": 1000.0,
            "contribution_pct": {"A": 80.0, "B": 20.0},
            "cv_r_squared": cv_r2,
            "coef_samples": model.coef_[None, :],
        }

    def _max_realloc_gap(self, cv_r2):
        from engine.elasticity_analysis import generate_aggregated_response_curve

        cfg = full_config({"reallocation_min_cv_r2": 0.1, "max_channel_mix_share": 0.9, "investment_limit_factor": 3.0})
        out = generate_aggregated_response_curve(self._make_results(cv_r2), cfg)
        df = out[0]
        return (df["Projected_Total_KPIs"] - df["Projected_Total_KPIs_Historical"]).abs().max()

    def test_low_cv_r2_suppresses_reallocation(self):
        self.assertLess(self._max_realloc_gap(cv_r2=0.0), 1e-6)

    def test_high_cv_r2_allows_reallocation(self):
        self.assertGreater(self._max_realloc_gap(cv_r2=0.9), 0.0)


class TestWalkForwardCvScore(unittest.TestCase):
    def test_high_cv_r2_when_feature_truly_drives_lift(self):
        # A feature that linearly drives the lift should generalize out-of-sample.
        rng = np.random.default_rng(0)
        n = 120
        x = rng.uniform(0, 1, n)
        lift = 5.0 * x + rng.normal(0, 0.1, n)
        transformed = pd.DataFrame({"CH": x})
        _, r2 = walk_forward_cv_score(transformed, lift)
        self.assertGreater(r2, 0.5)

    def test_cv_r2_not_positive_on_pure_noise(self):
        # Lift independent of the feature -> the model must NOT show it generalizes.
        # In-sample R^2 would be spuriously > 0; walk-forward CV R^2 should be ~0
        # or negative. This is exactly the "no real signal" case the metric exists
        # to expose (the two-stage clip artifact manufactured such lift before).
        rng = np.random.default_rng(1)
        n = 120
        x = rng.uniform(0, 1, n)
        lift = rng.normal(0, 1, n)  # unrelated to x
        transformed = pd.DataFrame({"CH": x})
        _, r2 = walk_forward_cv_score(transformed, lift)
        self.assertLessEqual(r2, 0.1)


class TestCreateCalendarFeaturesCadenceGate(unittest.TestCase):
    """Fase 3: calendar features must only include day-of-week/payday/holiday
    dummies for genuinely daily data (period_days=1) -- on weekly-or-coarser
    data every row lands on the same day of week, so those columns would be
    constant/degenerate. month_* is kept regardless of cadence."""

    def test_daily_generates_month_and_weekday_features(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        df = pd.DataFrame({"Date": dates, "x": range(30)})

        out = create_calendar_features(df, period_days=1)

        for col in ["is_weekend", "is_payday_period", "is_holiday", "month_1"]:
            self.assertIn(col, out.columns)

    def test_weekly_generates_only_month_features(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="7D")
        df = pd.DataFrame({"Date": dates, "x": range(30)})

        out = create_calendar_features(df, period_days=7)

        self.assertIn("month_1", out.columns)
        for col in ["is_weekend", "is_payday_period", "is_holiday"]:
            self.assertNotIn(col, out.columns)

    def test_base_features_selection_does_not_crash_without_calendar_dummies(self):
        """Mirrors the `base_features` list comprehension in run_mmm_engine
        (col.startswith('month_') or col in [...] + context_cols) -- a
        membership check over df.columns, so it must degrade gracefully
        (fewer selected features) rather than KeyError when is_weekend/
        is_payday_period/is_holiday are absent."""
        dates = pd.date_range("2024-01-01", periods=30, freq="7D")
        df = pd.DataFrame({"Date": dates, "x": range(30)})
        df = create_calendar_features(df, period_days=7)

        context_cols = []
        base_features = [
            col
            for col in df.columns
            if col.startswith("month_") or col in ["is_weekend", "is_payday_period", "is_holiday"] + context_cols
        ]

        # Should not raise, and should still pick up the always-present
        # month_* one-hot columns.
        self.assertTrue(any(c.startswith("month_") for c in base_features))
        self.assertNotIn("is_weekend", base_features)


if __name__ == "__main__":
    unittest.main()


class TestRunMmmEngineDoesNotLoadData:
    def test_uses_the_prepared_data_and_reads_no_file(self, monkeypatch):
        from engine import data_preprocessor
        from engine.data_preprocessor import PreparedData
        from engine.elasticity_analysis import run_mmm_engine

        def boom(*args, **kwargs):
            raise AssertionError("run_mmm_engine must not read files")

        monkeypatch.setattr(data_preprocessor, "read_csv_robust", boom)
        dates = pd.date_range("2025-01-01", periods=40, freq="D")
        prepared = PreparedData(
            kpi_df=pd.DataFrame({"Date": dates, "kpi": np.arange(40, dtype=float)}),
            investment_df=pd.DataFrame({"Date": dates, "Product Group": "A", "investment": 0.0}),
            spend_df=pd.DataFrame({"Date": dates, "Product Group": "A", "investment": 0.0}),
            trends_df=pd.DataFrame(
                {"Date": pd.Series(dtype="datetime64[ns]"), "Generic Searches": pd.Series(dtype=float)}
            ),
            controls_df=pd.DataFrame({"Date": dates}),
            correlation_matrix=pd.DataFrame(),
            period_days=1,
        )

        assert run_mmm_engine({"period_days": 1}, prepared) is None  # no channel with spend: the path past the load
