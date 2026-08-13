import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import percentileofscore
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
import argparse
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class StockAnalysis:
    symbol: str
    name: str
    price: float
    change_pct: float
    volume: int
    ma_50: float
    ma_150: float
    ma_200: float
    ma_200_trending_up: bool      # BUGFIX: store the real value from analyze_stock
    price_52wk_high: float
    price_52wk_low: float
    eps: Optional[float]
    pe_ratio: Optional[float]
    eps_growth: Optional[float]
    revenue_growth: Optional[float]
    rs_raw_perf: float        # FIX #2: raw weighted performance for percentile ranking
    rs_rating: float          # FIX #2: true percentile rank, set after all stocks are scored
    trend_score: int
    trend_requirements: Dict  # expose which criteria passed/failed for auditing
    fundamental_score: int
    overall_score: float
    signals: List[str]
    minervini_passed: bool    # FIX #3: explicit hard pass/fail flag
    atr_pct: float = 0.0     # 22-day ATR as percentage of price
    # New fields for entry points, earnings, and catalysts
    next_earnings_date: Optional[str] = None
    news_articles: List[Dict] = None
    entry_zone: Optional[str] = None
    entry_price: Optional[float] = None
    catalyst: Optional[str] = None
    # VCP Pattern Detection fields (Minervini SEPA-style)
    vcp_pattern_detected: bool = False
    vcp_pivot_price: Optional[float] = None        # breakout trigger = most recent swing high
    vcp_low_price: Optional[float] = None          # lowest swing low in the base
    vcp_recent_low: Optional[float] = None         # MOST RECENT swing low — use for stop-loss
    vcp_base_high: Optional[float] = None          # high that started the base
    vcp_base_depth_pct: Optional[float] = None     # full base depth (high -> lowest low)
    vcp_legs: int = 0                              # number of contractions detected
    vcp_contractions: Optional[List[float]] = None # depth % of each contraction, oldest -> newest
    vcp_final_contraction_pct: Optional[float] = None  # tightest/last contraction depth
    vcp_volume_dryup: bool = False                 # final leg shows volume dry-up
    vcp_base_length_days: int = 0                  # trading days from base high to today
    vcp_breakout: bool = False                     # price closed above pivot on volume
    # Extension warnings — Minervini's "don't chase extended stocks" rule
    pct_from_50ma: float = 0.0                     # % distance from 50-day MA
    extended_from_50ma: bool = False               # > 25% above 50-MA = climax/sell zone
    actionable: bool = False                       # passes template AND not extended AND has VCP
    # Volume analysis for entry confirmation
    avg_volume_50: float = 0.0                     # 50-day average volume
    prev_day_volume: float = 0.0                   # Previous day's volume
    volume_ratio: float = 0.0                      # prev_day_volume / avg_volume_50
    # Gamma Exposure (GEX) — dealer positioning indicator from options market
    gex: Optional[float] = None                    # Net dealer GEX in $ per 1% move (calls + / puts -)
    gex_expiration: Optional[str] = None           # Expiration used for GEX calculation
    gex_call_oi: int = 0                           # Total call open interest for that expiration
    gex_put_oi: int = 0                            # Total put open interest for that expiration


class MinerviniScreener:

    def __init__(self):
        # Cache for audit_stock to avoid re-screening the full universe per audit.
        # Keyed by index name ('sp500', 'sp400', 'sp600').
        self._audit_cache: Dict[str, List[StockAnalysis]] = {}

    # ---------------------------------------------------------------------------
    # Moving averages
    # ---------------------------------------------------------------------------
    def _calculate_moving_averages(self, data: pd.DataFrame) -> Dict:
        data = data.sort_index()
        close = data['Close']

        ma50  = close.rolling(window=50).mean().iloc[-1]
        ma150 = close.rolling(window=150).mean().iloc[-1]
        ma200_series = close.rolling(window=200).mean()
        ma200 = ma200_series.iloc[-1]

        # 200-MA trending up: require 2-month confirmation (today > 22d ago > 44d ago)
        # This prevents single-point noise from passing a stock whose 200-MA is choppy.
        ma200_22d_ago = ma200_series.iloc[-22] if len(ma200_series) > 22 else ma200
        ma200_44d_ago = ma200_series.iloc[-44] if len(ma200_series) > 44 else ma200_22d_ago
        ma200_trending_up = bool(ma200 > ma200_22d_ago and ma200_22d_ago > ma200_44d_ago)

        return {
            'ma_50': float(ma50),
            'ma_150': float(ma150),
            'ma_200': float(ma200),
            'ma_200_trending_up': ma200_trending_up,
        }

    def _calculate_atr_pct(self, data: pd.DataFrame, period: int = 22) -> float:
        """Calculate ATR as percentage of current price."""
        try:
            high = data['High']
            low = data['Low']
            close = data['Close']

            # Calculate True Range
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # Calculate ATR as moving average of True Range
            atr = true_range.rolling(window=period).mean().iloc[-1]
            current_price = close.iloc[-1]

            # Return ATR as percentage of price
            return float((atr / current_price) * 100)
        except Exception:
            return 0.0

    # ---------------------------------------------------------------------------
    # Gamma Exposure (GEX)
    # ---------------------------------------------------------------------------
    #
    # GEX measures the aggregate dealer gamma position implied by open options
    # contracts. Standard dealer-positioning convention:
    #   - Dealers are assumed LONG calls (customer sells calls to dealer) and
    #     SHORT puts (customer buys puts from dealer). This is the common
    #     SqueezeMetrics / SpotGamma convention.
    #   - Per-contract gamma exposure (in $ per 1% spot move):
    #         GEX_i = gamma_i * OI_i * 100 * spot^2 * 0.01
    #     where 100 = contract multiplier and 0.01 converts to "per 1% move".
    #   - Net GEX = sum(call GEX) - sum(put GEX).
    #
    # Positive GEX => dealers must SELL into rallies / BUY dips (vol-suppressing,
    # mean-reverting tape). Negative GEX => dealers must BUY into rallies /
    # SELL into dips (vol-amplifying, trending tape).
    #
    # Implementation notes:
    #   - We use the NEAREST expiration only (fastest, captures short-term flow).
    #   - We use yfinance's reported impliedVolatility column directly.
    #   - We compute gamma via Black-Scholes:
    #         gamma = phi(d1) / (S * sigma * sqrt(T))
    #     with phi = standard normal PDF, T in years, r assumed 0 (close enough
    #     for short-dated options and avoids an extra rate fetch).
    # ---------------------------------------------------------------------------
    def _calculate_gex(self, ticker: "yf.Ticker", spot: float, max_dte_days: int = 7) -> Dict:
        """
        Compute net dealer Gamma Exposure for the nearest options expiration
        that is within `max_dte_days` calendar days from today.

        Stocks whose nearest available expiration is further out than
        `max_dte_days` return gex=None. This filters out monthly-only chains
        whose GEX is not useful for short-term VCP breakout traders.

        Returns a dict with gex (float | None), expiration (str | None),
        call_oi (int), put_oi (int). Fails open with gex=None on any error.
        """
        empty = {'gex': None, 'expiration': None, 'call_oi': 0, 'put_oi': 0}
        try:
            from scipy.stats import norm
            import math

            expirations = ticker.options or []
            if not expirations:
                return empty

            now = datetime.now()
            # Pick the earliest expiration within the DTE window.
            expiry = None
            for candidate in expirations:
                try:
                    cand_dt = datetime.strptime(candidate, '%Y-%m-%d')
                except ValueError:
                    continue
                dte = (cand_dt - now).days
                if 0 <= dte <= max_dte_days:
                    expiry = candidate
                    break
                if dte > max_dte_days:
                    # Expirations are sorted ascending; once we pass the
                    # window the rest are even further out.
                    break

            if expiry is None:
                return empty

            chain = ticker.option_chain(expiry)
            calls = chain.calls
            puts = chain.puts

            # Time to expiration in years (use end of expiration day)
            try:
                exp_dt = datetime.strptime(expiry, '%Y-%m-%d')
            except ValueError:
                return empty
            t_days = max((exp_dt - now).days + 1, 1)  # at least 1 day to avoid div0
            T = t_days / 365.0

            if spot <= 0 or T <= 0:
                return empty

            def leg_gex(df: pd.DataFrame, sign: float) -> Tuple[float, int]:
                if df is None or df.empty:
                    return 0.0, 0
                total = 0.0
                oi_sum = 0
                for _, row in df.iterrows():
                    try:
                        K = float(row.get('strike', 0) or 0)
                        iv = float(row.get('impliedVolatility', 0) or 0)
                        oi = int(row.get('openInterest', 0) or 0)
                        if K <= 0 or iv <= 0 or oi <= 0:
                            continue
                        # Black-Scholes gamma, r = 0
                        d1 = (math.log(spot / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
                        gamma = norm.pdf(d1) / (spot * iv * math.sqrt(T))
                        # $ change in dealer delta per 1% spot move
                        contract_gex = gamma * oi * 100.0 * (spot ** 2) * 0.01
                        total += sign * contract_gex
                        oi_sum += oi
                    except (ValueError, TypeError, ZeroDivisionError):
                        continue
                return total, oi_sum

            call_gex, call_oi = leg_gex(calls, +1.0)
            put_gex, put_oi = leg_gex(puts, -1.0)
            net_gex = call_gex + put_gex

            return {
                'gex': float(net_gex),
                'expiration': expiry,
                'call_oi': int(call_oi),
                'put_oi': int(put_oi),
            }
        except Exception as e:
            logger.debug(f"GEX calculation failed: {e}")
            return empty

    def get_market_gex(self, symbol: str, max_dte_days: int = 7) -> Dict:
        """
        Fetch spot price + GEX for a market index ETF (e.g. QQQ, SPY).

        Returns dict with: symbol, price, change_pct, gex, expiration,
        call_oi, put_oi. Fields are None / 0 on failure (fails open).
        """
        result = {
            'symbol': symbol.upper(),
            'price': None,
            'change_pct': None,
            'gex': None,
            'expiration': None,
            'call_oi': 0,
            'put_oi': 0,
        }
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='5d')
            if hist is None or hist.empty:
                return result
            price = float(hist['Close'].iloc[-1])
            result['price'] = price
            if len(hist) >= 2:
                prev = float(hist['Close'].iloc[-2])
                if prev > 0:
                    result['change_pct'] = (price - prev) / prev * 100.0

            gex_res = self._calculate_gex(ticker, price, max_dte_days=max_dte_days)
            result['gex'] = gex_res['gex']
            result['expiration'] = gex_res['expiration']
            result['call_oi'] = gex_res['call_oi']
            result['put_oi'] = gex_res['put_oi']
        except Exception as e:
            logger.debug(f"get_market_gex failed for {symbol}: {e}")
        return result

    # ---------------------------------------------------------------------------
    # VCP Pattern Detection — Minervini SEPA methodology
    # ---------------------------------------------------------------------------
    #
    # Per Mark Minervini (Trade Like a Stock Market Wizard / Think & Trade Like a
    # Champion), a Volatility Contraction Pattern is defined by:
    #
    #   1. A prior uptrend (Stage 2) — gated separately by the trend template.
    #   2. 2 to 6 successive PRICE contractions (pullback from swing high to swing
    #      low), each one SHALLOWER than the prior. Typical footprint:
    #      e.g., 25% -> 15% -> 8%.
    #   3. Volume DRIES UP in the final/tightest contraction (lower avg volume
    #      than the base average).
    #   4. Base duration typically 3 to 65 weeks (we require >= 5 weeks of data
    #      for the analysis to be meaningful).
    #   5. The PIVOT is the most recent swing high — breakout above pivot on
    #      volume confirms the setup.
    #
    # Algorithm overview:
    #   - Take last ~75 trading days (~15 weeks) of price/volume.
    #   - Anchor the base at the highest swing-high in the window.
    #   - Walk forward from the anchor, alternately finding swing lows and swing
    #     highs using a fractal (3-bar) peak/trough detector.
    #   - Each (swing_high -> next swing_low) is one contraction. Depth =
    #     (swing_high - swing_low) / swing_high * 100.
    #   - Require >= 2 contractions and STRICTLY monotonically decreasing depth.
    #   - Final contraction should be tight (default <= 15%, usually <= 10%).
    #   - Volume dry-up: avg volume during the final contraction segment <
    #     0.85x the base average volume.
    # ---------------------------------------------------------------------------
    def _detect_vcp_pattern(
        self,
        data: pd.DataFrame,
        lookback_days: int = 75,
        min_base_days: int = 25,
        fractal_window: int = 3,
        max_final_contraction_pct: float = 15.0,
        volume_dryup_ratio: float = 0.85,
    ) -> Dict:
        """
        Detect Minervini-style VCP in the most recent price action.

        Returns dict with the fields used to populate StockAnalysis.vcp_*.
        Fails open (returns vcp_detected=False) on any error or insufficient data.
        """
        empty = {
            'vcp_detected': False,
            'pivot': None,
            'base_high': None,
            'low': None,
            'recent_low': None,
            'base_depth_pct': None,
            'legs': 0,
            'contractions': None,
            'final_contraction_pct': None,
            'volume_dryup': False,
            'base_length_days': 0,
            'breakout': False,
        }

        try:
            if len(data) < min_base_days:
                return empty

            recent = data.iloc[-lookback_days:].copy().reset_index(drop=True)
            if len(recent) < min_base_days:
                return empty

            highs = recent['High'].values.astype(float)
            lows = recent['Low'].values.astype(float)
            closes = recent['Close'].values.astype(float)
            volumes = recent['Volume'].values.astype(float) if 'Volume' in recent.columns else np.zeros(len(recent))
            n = len(recent)

            # -----------------------------------------------------------------
            # 1) Anchor the base.
            #
            #    Naive approach: take the absolute max High in the window.
            #    Problem: when a stock has already broken out of its base and
            #    is making fresh highs RIGHT NOW (e.g., MU mid-rally), the max
            #    sits at the right edge and leaves no room for contractions to
            #    have formed — so the detector misses real bases that were
            #    already broken out of.
            #
            #    Better approach: prefer the EARLIEST swing-high in the window
            #    that is within `proximity_pct` of the absolute max AND has at
            #    least `min_room` days of price action after it. This catches
            #    bases that have already broken out, and gives the detector
            #    room to identify the contraction structure that PRECEDED the
            #    current breakout.
            # -----------------------------------------------------------------
            min_room = 10           # need ~2 weeks of action after base high
            proximity_pct = 0.08    # candidate must be within 8% of absolute max

            abs_max_idx = int(np.argmax(highs))
            abs_max = float(highs[abs_max_idx])

            # Find all qualifying swing-high candidates
            w_anchor = fractal_window
            candidates: List[int] = []
            for i in range(w_anchor, n - min_room):
                lo, hi = max(0, i - w_anchor), min(n, i + w_anchor + 1)
                if highs[i] == highs[lo:hi].max() and highs[i] >= abs_max * (1 - proximity_pct):
                    candidates.append(i)

            if candidates:
                # Take the EARLIEST qualifying candidate so we have the most
                # room to see contractions form.
                base_high_idx = candidates[0]
            else:
                # Fallback: use absolute max. If it's too close to the edge,
                # we'll bail below.
                base_high_idx = abs_max_idx

            base_high = float(highs[base_high_idx])

            # Need enough room AFTER the base high to form contractions
            if (n - 1 - base_high_idx) < 8:
                return empty

            # -----------------------------------------------------------------
            # 2) Fractal swing detection AFTER the base high.
            #    A swing low at index i: lows[i] is the minimum in
            #    [i-w, i+w]. Similarly for swing highs.
            #    We then walk: expect low, then high, then low, then high...
            # -----------------------------------------------------------------
            w = fractal_window

            def is_swing_low(i: int) -> bool:
                lo = max(0, i - w)
                hi = min(n, i + w + 1)
                return lows[i] == lows[lo:hi].min()

            def is_swing_high(i: int) -> bool:
                lo = max(0, i - w)
                hi = min(n, i + w + 1)
                return highs[i] == highs[lo:hi].max()

            # Build the alternating pivot sequence starting from base_high_idx
            # Sequence: [base_high, low1, high1, low2, high2, ...]
            # Each (prev_high -> next_low) defines a contraction.
            pivots: List[Tuple[int, float, str]] = [(base_high_idx, base_high, 'H')]
            expect = 'L'
            i = base_high_idx + 1
            while i < n - w:
                if expect == 'L' and is_swing_low(i):
                    # Must be strictly below the previous pivot's price
                    if lows[i] < pivots[-1][1]:
                        pivots.append((i, float(lows[i]), 'L'))
                        expect = 'H'
                        i += w  # skip ahead to avoid double-counting
                        continue
                elif expect == 'H' and is_swing_high(i):
                    # Must be strictly above the previous swing low
                    if highs[i] > pivots[-1][1]:
                        pivots.append((i, float(highs[i]), 'H'))
                        expect = 'L'
                        i += w
                        continue
                i += 1

            # Always treat today's close as the "current" leg endpoint so an
            # in-progress final contraction is captured even without a confirmed
            # fractal swing low yet.
            last_idx = n - 1
            if pivots[-1][2] == 'H' and last_idx > pivots[-1][0]:
                # Currently pulling back from the last swing high
                running_low_offset = int(np.argmin(lows[pivots[-1][0] + 1:last_idx + 1]))
                running_low_idx = pivots[-1][0] + 1 + running_low_offset
                if lows[running_low_idx] < pivots[-1][1]:
                    pivots.append((running_low_idx, float(lows[running_low_idx]), 'L'))

            # -----------------------------------------------------------------
            # 3) Compute contraction depths (swing_high -> next swing_low).
            # -----------------------------------------------------------------
            contractions: List[float] = []
            contraction_segments: List[Tuple[int, int]] = []  # (start_idx, end_idx)
            for j in range(len(pivots) - 1):
                a_idx, a_px, a_kind = pivots[j]
                b_idx, b_px, b_kind = pivots[j + 1]
                if a_kind == 'H' and b_kind == 'L' and a_px > 0:
                    depth = (a_px - b_px) / a_px * 100.0
                    contractions.append(round(depth, 2))
                    contraction_segments.append((a_idx, b_idx))

            # Lowest swing low and pivot point
            swing_low_pivots = [p for p in pivots if p[2] == 'L']
            swing_lows = [p[1] for p in swing_low_pivots]
            swing_highs_after_base = [p[1] for p in pivots[1:] if p[2] == 'H']

            base_low = float(min(swing_lows)) if swing_lows else float(lows[base_high_idx:].min())
            # Most recent swing low — this is the stop-loss reference point.
            # A break below this invalidates the current contraction structure.
            recent_low = float(swing_low_pivots[-1][1]) if swing_low_pivots else base_low
            # Pivot = most recent confirmed swing high after the base high.
            # If none yet (we only have the base high + pullbacks), pivot = base high.
            pivot = float(swing_highs_after_base[-1]) if swing_highs_after_base else base_high

            base_depth_pct = (base_high - base_low) / base_high * 100.0 if base_high > 0 else 0.0
            base_length_days = n - 1 - base_high_idx

            # -----------------------------------------------------------------
            # 4) Validate VCP structure
            # -----------------------------------------------------------------
            # Need at least 2 contractions
            if len(contractions) < 2:
                return {
                    **empty,
                    'pivot': round(pivot, 2),
                    'base_high': round(base_high, 2),
                    'low': round(base_low, 2),
                    'recent_low': round(recent_low, 2),
                    'base_depth_pct': round(base_depth_pct, 1),
                    'legs': len(contractions),
                    'contractions': contractions or None,
                    'base_length_days': base_length_days,
                }

            # Each contraction must be STRICTLY shallower than the prior one
            monotonic = all(
                contractions[k] < contractions[k - 1]
                for k in range(1, len(contractions))
            )

            final_contraction = contractions[-1]
            tight_enough = final_contraction <= max_final_contraction_pct

            # First (deepest) contraction should be the largest move — sanity
            # check: it should be > final_contraction (implied by monotonic).
            # Minervini also says total base depth typically <= 35% for
            # quality setups; we soft-cap at 50% to avoid late-stage bases.
            base_depth_reasonable = base_depth_pct <= 50.0

            # -----------------------------------------------------------------
            # 5) Volume dry-up check on the final contraction segment.
            #    Compare avg volume during last contraction vs base average.
            # -----------------------------------------------------------------
            volume_dryup = False
            if len(contraction_segments) > 0 and volumes.sum() > 0:
                base_vol_avg = float(np.mean(volumes[base_high_idx:])) if base_high_idx < n else 0.0
                last_start, last_end = contraction_segments[-1]
                final_seg_vol = volumes[last_start:last_end + 1]
                if base_vol_avg > 0 and len(final_seg_vol) > 0:
                    final_vol_avg = float(np.mean(final_seg_vol))
                    volume_dryup = final_vol_avg < (volume_dryup_ratio * base_vol_avg)

            # -----------------------------------------------------------------
            # 6) Breakout check: today's close above pivot on above-avg volume.
            # -----------------------------------------------------------------
            breakout = False
            if pivot > 0 and closes[-1] > pivot:
                if volumes.sum() > 0:
                    avg_vol_50 = float(np.mean(volumes[-50:])) if n >= 50 else float(np.mean(volumes))
                    breakout = volumes[-1] > avg_vol_50  # any above-average vol qualifies
                else:
                    breakout = True

            vcp_detected = bool(
                len(contractions) >= 2
                and monotonic
                and tight_enough
                and base_depth_reasonable
                and base_length_days >= 15   # ~3 weeks min from base high
            )

            return {
                'vcp_detected': vcp_detected,
                'pivot': round(pivot, 2),
                'base_high': round(base_high, 2),
                'low': round(base_low, 2),
                'recent_low': round(recent_low, 2),
                'base_depth_pct': round(base_depth_pct, 1),
                'legs': len(contractions),
                'contractions': contractions,
                'final_contraction_pct': round(final_contraction, 2),
                'volume_dryup': volume_dryup,
                'base_length_days': base_length_days,
                'breakout': breakout,
            }
        except Exception as e:
            logger.debug(f"VCP detection failed: {e}")
            return empty

    def _identify_entry_zone(
        self,
        current_price: float,
        high_52wk: float,
        low_52wk: float,
        ma_50: float,
        ma_150: float,
        ma_200: float,
        ma_200_trending_up: bool,
    ) -> Tuple[Optional[str], Optional[float]]:
        pct_from_high = ((high_52wk - current_price) / high_52wk) * 100
        pct_from_low = ((current_price - low_52wk) / low_52wk) * 100

        ma_stack_aligned = ma_50 > ma_150 > ma_200

        if pct_from_high <= 5 and ma_stack_aligned:
            return "base_breakout", current_price
        elif pct_from_high <= 15 and ma_stack_aligned and pct_from_low >= 30:
            return "tight_consolidation", current_price
        elif ma_stack_aligned and ma_200_trending_up:
            if abs(current_price - ma_50) / ma_50 <= 0.03:
                return "at_50ma_pullback", ma_50
            elif abs(current_price - ma_150) / ma_150 <= 0.03:
                return "at_150ma_pullback", ma_150
        return None, None

    # ---------------------------------------------------------------------------
    # FIX #2 — RS rating: return raw weighted performance only.
    #           True percentile rank is assigned AFTER all stocks are scored.
    # ---------------------------------------------------------------------------
    def _get_rs_raw_performance(self, sp500_data: pd.DataFrame, stock_data: pd.DataFrame) -> float:
        """
        Weighted relative performance vs benchmark (S&P 500 / 400 / 600).
        Weights: 40% (3 m), 20% (6 m), 20% (9 m), 20% (12 m).
        Returns the raw outperformance figure — NOT a 1-99 score yet.

        NOTE: The percentile rank derived from this is computed against the
        screened universe (i.e., the chosen index), NOT the full broad market.
        IBD's official RS Rating ranks vs. ~7,000 listed stocks. A stock at
        the 60th percentile of the S&P 500 may rank far higher in the broad
        market, and vice versa for small-cap screens. Treat the RS rating
        here as an intra-index measure.
        """
        try:
            def get_return(data: pd.DataFrame, days: int) -> float:
                if len(data) < days + 1:
                    return 0.0
                return float((data['Close'].iloc[-1] / data['Close'].iloc[-(days + 1)]) - 1)

            periods = [63, 126, 189, 252]   # ~3, 6, 9, 12 months
            weights = [0.4, 0.2, 0.2, 0.2]

            stock_perf = sum(get_return(stock_data, p) * w for p, w in zip(periods, weights))
            sp_perf    = sum(get_return(sp500_data,  p) * w for p, w in zip(periods, weights))

            return stock_perf - sp_perf     # raw outperformance vs index
        except Exception:
            return 0.0

    # ---------------------------------------------------------------------------
    # FIX #3 — Trend template: strictly binary.  Score is informational only.
    # FIX #6 — Denominator is now 8 (RS is handled separately, not double-counted).
    # ---------------------------------------------------------------------------
    def _check_trend_template(
        self,
        ma_data: Dict,
        current_price: float,
        high_52wk: float,
        low_52wk: float,
        rs_rating: float,           # passed in after percentile ranking
    ) -> Tuple[bool, Dict, int]:

        req: Dict[str, bool] = {}

        # --- MA stack alignment (4 criteria) ---
        req['price_above_50ma']    = current_price > ma_data['ma_50']
        req['price_above_150ma']   = current_price > ma_data['ma_150']
        req['price_above_200ma']   = current_price > ma_data['ma_200']
        req['50ma_above_150_200']  = (
            ma_data['ma_50'] > ma_data['ma_150'] and
            ma_data['ma_50'] > ma_data['ma_200']
        )
        req['150ma_above_200ma']   = ma_data['ma_150'] > ma_data['ma_200']

        # --- 200-MA trending up for at least 1 month ---
        req['200ma_trending_up']   = ma_data['ma_200_trending_up']

        # FIX #1 — proximity uses the TRUE 52-week window (set in analyze_stock)
        distance_from_high = ((high_52wk - current_price) / high_52wk) * 100
        req['within_25pct_of_high'] = distance_from_high <= 25

        # --- 30% above 52-week low (canonical Minervini Trend Template criterion #6) ---
        if low_52wk > 0:
            pct_above_low = ((current_price - low_52wk) / low_52wk) * 100
            req['30pct_above_52wk_low'] = pct_above_low >= 30
        else:
            req['30pct_above_52wk_low'] = False

        # --- RS rating (Minervini's preferred 80+ threshold) ---
        req['rs_rating_above_80']   = rs_rating >= 80

        # Denominator is now 9 criteria total (7 MA/price + 30%-above-low + RS)
        score = sum(1 for v in req.values() if v)

        # Hard binary: ALL criteria must pass
        all_passed = all(req.values())

        return all_passed, req, score

    # ---------------------------------------------------------------------------
    # Earnings acceleration check (Minervini SEPA fundamental component)
    # ---------------------------------------------------------------------------
    def _check_earnings_acceleration(self, ticker: "yf.Ticker") -> bool:
        """
        Returns True if the last 3 quarters show YoY EPS growth that is
        ACCELERATING (each quarter's YoY growth > prior quarter's YoY growth).
        Fails open (returns False) when data is unavailable or insufficient.
        """
        try:
            qe = None
            # Prefer quarterly_income_stmt (newer yfinance), fall back to quarterly_earnings
            try:
                qis = ticker.quarterly_income_stmt
                if qis is not None and not qis.empty and 'Diluted EPS' in qis.index:
                    qe = qis.loc['Diluted EPS'].dropna()
                elif qis is not None and not qis.empty and 'Basic EPS' in qis.index:
                    qe = qis.loc['Basic EPS'].dropna()
            except Exception:
                qe = None

            if qe is None or len(qe) < 7:
                # Need at least 7 quarters to compute 3 YoY growth points
                return False

            # qe is sorted with most-recent first in yfinance; ensure that order
            qe = qe.sort_index(ascending=False)
            eps_vals = qe.values.astype(float)

            # Compute YoY growth for the 3 most recent quarters
            yoy = []
            for i in range(3):
                cur = eps_vals[i]
                prior = eps_vals[i + 4]
                if prior == 0 or np.isnan(prior) or np.isnan(cur):
                    return False
                # Use absolute value of prior to handle negative-to-positive turnarounds
                growth = (cur - prior) / abs(prior)
                yoy.append(growth)

            # yoy[0] = most recent quarter, yoy[2] = oldest of the three
            # Accelerating means: most recent > prior > older
            return yoy[0] > yoy[1] > yoy[2]
        except Exception:
            return False

    # ---------------------------------------------------------------------------
    # Catalysts and news enrichment (best-effort, fails open)
    # ---------------------------------------------------------------------------
    def _get_next_earnings_date(self, ticker: "yf.Ticker") -> Optional[str]:
        try:
            cal = ticker.calendar
            if cal is None:
                return None
            # yfinance returns a dict in newer versions
            if isinstance(cal, dict):
                ed = cal.get('Earnings Date')
                if ed:
                    if isinstance(ed, list) and len(ed) > 0:
                        return str(ed[0])
                    return str(ed)
            # Older versions returned a DataFrame
            elif hasattr(cal, 'loc') and 'Earnings Date' in getattr(cal, 'index', []):
                val = cal.loc['Earnings Date']
                if hasattr(val, 'iloc'):
                    return str(val.iloc[0])
                return str(val)
        except Exception:
            pass
        return None

    def _get_recent_news(self, ticker: "yf.Ticker", limit: int = 3) -> List[Dict]:
        try:
            news = ticker.news or []
            articles = []
            now = datetime.now()

            for item in news[:10]:
                if not isinstance(item, dict):
                    continue

                content = item.get('content') or {}

                title = content.get('title', '')
                summary = content.get('summary', '')
                pub_date_str = content.get('pubDate', '')

                pub_date = None
                if pub_date_str:
                    try:
                        pub_date = datetime.strptime(pub_date_str.replace('Z', '+00:00'), '%Y-%m-%dT%H:%M:%S+00:00')
                    except ValueError:
                        try:
                            pub_date = datetime.strptime(pub_date_str.split('+')[0].strip(), '%Y-%m-%dT%H:%M:%S')
                        except:
                            pass

                if pub_date and (now - pub_date).days >= 7:
                    continue

                provider = content.get('provider', {})
                publisher = provider.get('displayName', '') if isinstance(provider, dict) else ''

                click_through = content.get('clickThroughUrl') or {}
                link = click_through.get('url', '') if isinstance(click_through, dict) else ''

                if title:
                    articles.append({
                        'title': title,
                        'summary': summary,
                        'link': link,
                        'publisher': publisher,
                        'pub_date': pub_date_str
                    })

                if len(articles) >= limit:
                    break

            return articles
        except Exception:
            return []

    def _derive_catalyst(self, next_earnings_date: Optional[str], news_articles: List[Dict]) -> Optional[str]:
        try:
            if next_earnings_date:
                # Try to parse and detect if within 2 weeks
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S'):
                    try:
                        dt = datetime.strptime(next_earnings_date.split('+')[0].strip(), fmt)
                        days = (dt - datetime.now()).days
                        if 0 <= days <= 14:
                            return f"Upcoming earnings in {days}d"
                        break
                    except ValueError:
                        continue
            if news_articles and len(news_articles) > 0:
                first_article = news_articles[0]
                title = first_article.get('title', '')
                if title:
                    return f"Recent news: {title[:80]}"
        except Exception:
            pass
        return None

    # ---------------------------------------------------------------------------
    # Per-stock analysis  (sp500_data passed in — FIX #4: fetched ONCE outside loop)
    # ---------------------------------------------------------------------------
    def analyze_stock(self, symbol: str, sp500_data: pd.DataFrame, reference_date: Optional[datetime] = None) -> Optional[StockAnalysis]:
        try:
            ticker = yf.Ticker(symbol)
            info   = ticker.info

            if reference_date:
                end_date = reference_date.strftime('%Y-%m-%d')
                start_date = (reference_date - timedelta(days=730)).strftime('%Y-%m-%d')
                hist = ticker.history(start=start_date, end=end_date)
            else:
                hist = ticker.history(period="2y")

            if len(hist) < 200:
                logger.warning(f"Insufficient data for {symbol}")
                return None

            current_price = float(hist['Close'].iloc[-1])

            # FIX #1 — 52-week high/low from LAST 252 TRADING DAYS only
            hist_52wk = hist.iloc[-252:]
            high_52wk = float(hist_52wk['High'].max())
            low_52wk  = float(hist_52wk['Low'].min())

            ma_data = self._calculate_moving_averages(hist)

            # Calculate 22-day ATR as percentage of price
            atr_pct = self._calculate_atr_pct(hist, period=22)

            # Volume analysis for entry confirmation (Minervini requires volume spike at breakout)
            avg_volume_50 = float(hist['Volume'].iloc[-50:].mean()) if len(hist) >= 50 else float(hist['Volume'].mean())
            prev_day_volume = float(hist['Volume'].iloc[-2]) if len(hist) >= 2 else 0.0
            volume_ratio = prev_day_volume / avg_volume_50 if avg_volume_50 > 0 else 0.0

            # Detect Minervini-style VCP pattern (look back ~15 weeks)
            vcp_result = self._detect_vcp_pattern(hist, lookback_days=75)

            # Gamma Exposure (dealer positioning from options market).
            # Skipped in backtest mode — options chains are live-only via yfinance.
            if reference_date is None:
                gex_result = self._calculate_gex(ticker, current_price)
            else:
                gex_result = {'gex': None, 'expiration': None, 'call_oi': 0, 'put_oi': 0}

            # Raw RS performance (percentile assigned later in find_top_opportunities)
            rs_raw = self._get_rs_raw_performance(sp500_data, hist)

            # yfinance field names: prefer canonical 'trailingEps', fall back for safety
            eps             = info.get('trailingEps') or info.get('epsTrailingTwelveMonths')
            pe              = info.get('trailingPE')
            eps_growth      = info.get('earningsQuarterlyGrowth')
            revenue_growth  = info.get('revenueGrowth')

            # Fundamental score (0-4) — Minervini SEPA fundamental components.
            # PE cap removed: Minervini does not use a PE filter; high-growth winners
            # frequently trade at PEs > 50 and should not be penalized.
            fundamental_score = 0
            if eps and eps > 0:
                fundamental_score += 1
            if eps_growth and eps_growth > 0.25:
                fundamental_score += 1
            if revenue_growth and revenue_growth > 0.25:
                fundamental_score += 1
            # Earnings acceleration across last 3 quarters (Phase 4)
            earnings_accelerating = self._check_earnings_acceleration(ticker)
            if earnings_accelerating:
                fundamental_score += 1

            # Catalysts / news enrichment (best-effort)
            next_earnings_date = self._get_next_earnings_date(ticker)
            news_articles      = self._get_recent_news(ticker)
            catalyst           = self._derive_catalyst(next_earnings_date, news_articles)

            change_pct = (
                ((current_price - float(hist['Close'].iloc[-2])) / float(hist['Close'].iloc[-2])) * 100
                if len(hist) > 1 else 0.0
            )

            entry_zone, entry_price = self._identify_entry_zone(
                current_price, high_52wk, low_52wk,
                ma_data['ma_50'], ma_data['ma_150'], ma_data['ma_200'],
                ma_data['ma_200_trending_up']
            )

            # Extension check — Minervini's "don't chase extended stocks" rule.
            # A stock more than ~25% above its 50-day MA is climactic / late-stage.
            # Buy zone is typically within 5-10% of the 50-MA after a base breakout.
            pct_from_50ma = ((current_price - ma_data['ma_50']) / ma_data['ma_50']) * 100 if ma_data['ma_50'] else 0.0
            extended_from_50ma = pct_from_50ma > 25.0

            return StockAnalysis(
                symbol=symbol.upper(),
                name=info.get('shortName', symbol),
                price=current_price,
                change_pct=change_pct,
                volume=info.get('volume', 0),
                ma_50=ma_data['ma_50'],
                ma_150=ma_data['ma_150'],
                ma_200=ma_data['ma_200'],
                ma_200_trending_up=ma_data['ma_200_trending_up'],  # BUGFIX: store real value
                price_52wk_high=high_52wk,
                price_52wk_low=low_52wk,
                eps=eps,
                pe_ratio=pe,
                eps_growth=eps_growth,
                revenue_growth=revenue_growth,
                rs_raw_perf=rs_raw,
                rs_rating=50.0,         # placeholder — set after percentile ranking
                trend_score=0,          # placeholder — set after RS is finalised
                trend_requirements={},  # placeholder
                fundamental_score=fundamental_score,
                overall_score=0.0,      # placeholder
                signals=[],
                minervini_passed=False, # placeholder
                atr_pct=atr_pct,       # 22-day ATR as percentage of price
                next_earnings_date=next_earnings_date,
                news_articles=news_articles,
                entry_zone=entry_zone,
                entry_price=entry_price,
                catalyst=catalyst,
                vcp_pattern_detected=vcp_result['vcp_detected'],
                vcp_pivot_price=vcp_result['pivot'],
                vcp_low_price=vcp_result['low'],
                vcp_recent_low=vcp_result['recent_low'],
                vcp_base_high=vcp_result['base_high'],
                vcp_base_depth_pct=vcp_result['base_depth_pct'],
                vcp_legs=vcp_result['legs'],
                vcp_contractions=vcp_result['contractions'],
                vcp_final_contraction_pct=vcp_result['final_contraction_pct'],
                vcp_volume_dryup=vcp_result['volume_dryup'],
                vcp_base_length_days=vcp_result['base_length_days'],
                vcp_breakout=vcp_result['breakout'],
                pct_from_50ma=pct_from_50ma,
                extended_from_50ma=extended_from_50ma,
                actionable=False,  # set in screen_candidates after template runs
                avg_volume_50=avg_volume_50,
                prev_day_volume=prev_day_volume,
                volume_ratio=volume_ratio,
                gex=gex_result['gex'],
                gex_expiration=gex_result['expiration'],
                gex_call_oi=gex_result['call_oi'],
                gex_put_oi=gex_result['put_oi'],
            )
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return None

    # ---------------------------------------------------------------------------
    # FIX #2 — Percentile rank RS across ALL screened stocks, THEN score/filter
    # FIX #3 — overall_score is 0 for any stock that fails the template
    # FIX #4 — S&P 500 data fetched ONCE here, passed into every analyze_stock call
    # ---------------------------------------------------------------------------
    def screen_candidates(self, symbols: List[str], benchmark_ticker: str = "^GSPC", reference_date: Optional[datetime] = None) -> List[StockAnalysis]:
        if reference_date:
            end_date = reference_date.strftime('%Y-%m-%d')
            start_date = (reference_date - timedelta(days=730)).strftime('%Y-%m-%d')
            logger.info(f"Backtest mode: fetching data from {start_date} to {end_date}")
            sp500_data = yf.Ticker(benchmark_ticker).history(start=start_date, end=end_date)
        else:
            logger.info(f"Fetching {benchmark_ticker} benchmark data...")
            sp500_data = yf.Ticker(benchmark_ticker).history(period="2y")

        results: List[StockAnalysis] = []
        for symbol in symbols:
            logger.info(f"Analyzing {symbol}...")
            analysis = self.analyze_stock(symbol, sp500_data, reference_date)
            if analysis:
                results.append(analysis)

        if not results:
            return results

        # FIX #2 — true percentile rank now that we have all raw performances
        all_raw_perfs = [r.rs_raw_perf for r in results]
        for r in results:
            r.rs_rating = float(percentileofscore(all_raw_perfs, r.rs_raw_perf, kind='rank'))

        # Now that RS ratings are finalised, run the trend template check & score
        for r in results:
            passed, req, score = self._check_trend_template(
                ma_data={
                    'ma_50': r.ma_50,
                    'ma_150': r.ma_150,
                    'ma_200': r.ma_200,
                    'ma_200_trending_up': r.ma_200_trending_up,  # BUGFIX: use stored value
                },
                current_price=r.price,
                high_52wk=r.price_52wk_high,
                low_52wk=r.price_52wk_low,
                rs_rating=r.rs_rating,
            )

            r.minervini_passed    = passed
            r.trend_score         = score
            r.trend_requirements  = req

            # Build human-readable signals
            signals: List[str] = []
            if passed:
                signals.append("✅ MINERVINI TREND TEMPLATE PASSED")
            else:
                failed = [k for k, v in req.items() if not v]
                signals.append(f"❌ Failed criteria: {', '.join(failed)}")

            if score >= 8:
                signals.append(f"Strong trend ({score}/9 criteria)")
            if r.rs_rating >= 80:
                signals.append(f"High relative strength (RS: {r.rs_rating:.0f})")
            if req.get('200ma_trending_up'):
                signals.append("200-day MA trending up (2-month confirmed)")
            if r.eps_growth and r.eps_growth > 0.4:
                signals.append(f"Exceptional EPS growth ({r.eps_growth * 100:.0f}%)")
            if r.catalyst:
                signals.append(r.catalyst)

            # Extension / VCP commentary
            if r.extended_from_50ma:
                signals.append(
                    f"⚠️ EXTENDED: {r.pct_from_50ma:+.0f}% above 50-MA — "
                    "do NOT chase, wait for pullback to 50-MA or new base"
                )
            elif r.pct_from_50ma > 15:
                signals.append(
                    f"Stretched: {r.pct_from_50ma:+.0f}% above 50-MA — "
                    "near upper end of buy zone"
                )

            if r.vcp_pattern_detected:
                contractions_str = " → ".join(f"{c:.1f}%" for c in (r.vcp_contractions or []))
                signals.append(
                    f"VCP: {contractions_str}, pivot ${r.vcp_pivot_price}, "
                    f"stop ${r.vcp_recent_low}"
                )
                if r.vcp_breakout:
                    signals.append("🚀 BREAKOUT confirmed (price > pivot on volume)")
                if r.vcp_volume_dryup:
                    signals.append("Volume dry-up on final leg (Minervini-textbook)")

            if r.gex is not None:
                gex_sign = "+" if r.gex >= 0 else ""
                signals.append(f"GEX: {gex_sign}${r.gex/1e6:,.1f}M per 1% ({r.gex_expiration})")

            # Actionable = passes template AND not climactically extended.
            # A perfect actionable setup also has a VCP and is near the pivot,
            # but we keep the threshold loose here so non-VCP stocks near MAs
            # still show as actionable.
            r.actionable = bool(passed and not r.extended_from_50ma)

            r.signals = signals

            # Stocks that fail the template get overall_score = 0
            # RS contributes via its own term only (no double-count)
            # Denominators: trend = 9 criteria, fundamentals = 4 components
            if passed:
                r.overall_score = (
                    (score / 9)           * 50 +   # trend (9 criteria)
                    (r.fundamental_score / 4) * 30 + # fundamentals (EPS+, EPS gr, rev gr, accel)
                    (r.rs_rating / 100)   * 20       # RS percentile
                )
            else:
                r.overall_score = 0.0

        # Sort: passing stocks first (by overall_score desc), then failures
        results.sort(key=lambda x: x.overall_score, reverse=True)
        return results

    # ---------------------------------------------------------------------------
    # Helper: pick the constituents table from a Wikipedia page.
    # Wikipedia occasionally adds intro/header tables that shift the index,
    # so we scan for the first table that has a flat 'Symbol' column.
    # ---------------------------------------------------------------------------
    def _extract_symbols_from_wiki(self, url: str) -> List[str]:
        import requests
        from io import StringIO
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, timeout=15, headers=headers)
        dfs = pd.read_html(StringIO(response.text))
        for df in dfs:
            # Skip MultiIndex columns (those are the "changes" tables)
            if any(isinstance(c, tuple) for c in df.columns):
                continue
            if 'Symbol' in df.columns and len(df) >= 100:
                return df['Symbol'].astype(str).str.replace('.', '-', regex=False).tolist()
        raise ValueError(f"No constituents table with 'Symbol' column found at {url}")

    # ---------------------------------------------------------------------------
    # S&P 500 symbol list helper
    # ---------------------------------------------------------------------------
    def _get_sp500_symbols(self) -> List[str]:
        try:
            return self._extract_symbols_from_wiki(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch S&P 500 list: {e}, using fallback")
            return [
                'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'UNH', 'JNJ',
                'V', 'XOM', 'JPM', 'PG', 'MA', 'HD', 'CVX', 'LLY', 'ABBV', 'MRK',
                'AVGO', 'PEP', 'COST', 'KO', 'TMO', 'MCD', 'CSCO', 'ACN', 'WMT', 'DIS',
                'GOOG', 'APH', 'DELL', 'MU',
            ]

    # ---------------------------------------------------------------------------
    # S&P 400 (Mid-Cap) symbol list helper
    # ---------------------------------------------------------------------------
    def _get_sp400_symbols(self) -> List[str]:
        try:
            return self._extract_symbols_from_wiki(
                "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch S&P 400 list: {e}, using fallback")
            return []

    # ---------------------------------------------------------------------------
    # S&P 600 (Small-Cap) symbol list helper
    # ---------------------------------------------------------------------------
    def _get_sp600_symbols(self) -> List[str]:
        try:
            return self._extract_symbols_from_wiki(
                "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch S&P 600 list: {e}, using fallback")
            return []

    # ---------------------------------------------------------------------------
    # Main entry point
    # index: 'sp500' (default), 'sp400', or 'sp600'
    # ---------------------------------------------------------------------------
    def find_top_opportunities(self, minervini_pass_only: bool = True, limit: int = 10, index: str = 'sp500', reference_date: Optional[datetime] = None) -> List[StockAnalysis]:
        if index == 'sp400':
            logger.info("Fetching S&P 400 (Mid-Cap) symbols...")
            symbols = self._get_sp400_symbols()
            benchmark = "^SP400"
        elif index == 'sp600':
            logger.info("Fetching S&P 600 (Small-Cap) symbols...")
            symbols = self._get_sp600_symbols()
            benchmark = "^SP600"
        else:
            logger.info("Fetching S&P 500 symbols...")
            symbols = self._get_sp500_symbols()
            benchmark = "^GSPC"

        logger.info(f"Loaded {len(symbols)} symbols")

        results = self.screen_candidates(symbols, benchmark, reference_date)

        if minervini_pass_only:
            results = [r for r in results if r.minervini_passed]

        return results[:limit]

    # ---------------------------------------------------------------------------
    # Convenience: audit a single stock with full breakdown (great for debugging)
    # ---------------------------------------------------------------------------
    def audit_stock(self, symbol: str, benchmark_ticker: str = "^GSPC", reference_date: Optional[datetime] = None) -> None:
        """
        Print a full pass/fail breakdown for a single stock.
        Calculates RS rating by comparing against the appropriate index.

        Uses an instance-level cache (`self._audit_cache`) so consecutive audits
        against the same index reuse a single full screen rather than re-running
        the full universe on every call.
        """
        # Determine which index to use based on benchmark_ticker
        if benchmark_ticker == "^GSPC":
            index = 'sp500'
        elif benchmark_ticker == "^SP400":
            index = 'sp400'
        elif benchmark_ticker == "^SP600":
            index = 'sp600'
        else:
            index = 'sp500'

        symbol_upper = symbol.upper()

        # Use cached results if available for this index
        results = self._audit_cache.get(index)

        # If cache miss OR symbol not in cached results, run the full screen
        if results is None or not any(r.symbol.upper() == symbol_upper for r in results):
            # Get the symbols for the index
            if index == 'sp500':
                symbols = self._get_sp500_symbols()
            elif index == 'sp400':
                symbols = self._get_sp400_symbols()
            elif index == 'sp600':
                symbols = self._get_sp600_symbols()
            else:
                symbols = self._get_sp500_symbols()

            # Make sure our symbol is in the list
            if symbol_upper not in [s.upper() for s in symbols]:
                symbols.append(symbol_upper)

            print(f"Calculating RS rating for {symbol_upper} (running full {index} screen — cached for subsequent audits)...")
            results = self.screen_candidates(symbols, benchmark_ticker, reference_date)
            self._audit_cache[index] = results
        else:
            print(f"Using cached {index} screen for {symbol_upper}...")

        # Find our stock
        result = next((r for r in results if r.symbol.upper() == symbol_upper), None)
        if not result:
            print(f"Could not fetch data for {symbol}")
            return

        # Now print the audit breakdown
        passed = result.minervini_passed
        req = result.trend_requirements
        score = result.trend_score

        print(f"\n{'='*55}")
        print(f"  MINERVINI AUDIT — {symbol_upper}")
        print(f"{'='*55}")
        print(f"  Price      : ${result.price:.2f}")
        print(f"  50-day MA  : ${result.ma_50:.2f}   (price {'>' if result.price > result.ma_50 else '<'} MA)")
        print(f"  150-day MA : ${result.ma_150:.2f}   (price {'>' if result.price > result.ma_150 else '<'} MA)")
        print(f"  200-day MA : ${result.ma_200:.2f}   (price {'>' if result.price > result.ma_200 else '<'} MA)")
        print(f"  52wk High  : ${result.price_52wk_high:.2f}")
        print(f"  52wk Low   : ${result.price_52wk_low:.2f}")
        pct_above_low = ((result.price - result.price_52wk_low) / result.price_52wk_low * 100) if result.price_52wk_low > 0 else 0.0
        print(f"  Above Low  : {pct_above_low:.1f}%   (need \u2265 30%)")
        print(f"\n  Criteria breakdown:")
        for criterion, value in req.items():
            status = "✅" if value else "❌"
            print(f"    {status}  {criterion}")
        print(f"\n  Trend Score       : {score}/9")
        print(f"  RS Rating         : {result.rs_rating:.0f} (intra-{index} percentile)")
        print(f"  Fundamental Score : {result.fundamental_score}/4 (EPS+, EPS gr, rev gr, accel)")
        print(f"  % from 50-MA      : {result.pct_from_50ma:+.1f}%   "
              f"{'⚠️ EXTENDED — do not chase' if result.extended_from_50ma else 'OK (within buy zone)'}")
        print(f"  22-day ATR%       : {result.atr_pct:.2f}%")
        if result.gex is not None:
            gex_sign = "+" if result.gex >= 0 else ""
            gex_regime = "positive (vol-suppressing)" if result.gex >= 0 else "negative (vol-amplifying)"
            print(f"  GEX               : {gex_sign}${result.gex:,.0f} per 1% move "
                  f"[{gex_regime}]")
            print(f"  GEX expiration    : {result.gex_expiration}  "
                  f"(call OI: {result.gex_call_oi:,}, put OI: {result.gex_put_oi:,})")
        else:
            print(f"  GEX               : n/a (no options chain available)")

        # VCP block
        if result.vcp_pattern_detected:
            contractions = " → ".join(f"{c:.1f}%" for c in (result.vcp_contractions or []))
            print(f"\n  --- VCP DETECTED ---")
            print(f"  Base high         : ${result.vcp_base_high}")
            print(f"  Pivot (buy point) : ${result.vcp_pivot_price}")
            print(f"  Recent low (stop) : ${result.vcp_recent_low}")
            print(f"  Base depth        : {result.vcp_base_depth_pct}%")
            print(f"  Contractions      : {contractions}")
            print(f"  Final contraction : {result.vcp_final_contraction_pct}%")
            print(f"  Volume dry-up     : {'✅' if result.vcp_volume_dryup else '❌'}")
            print(f"  Base length       : {result.vcp_base_length_days} days")
            print(f"  Breakout          : {'🚀 YES' if result.vcp_breakout else 'not yet'}")
        else:
            print(f"\n  VCP               : no pattern (extended runaway move, or no base formed)")

        if result.next_earnings_date:
            print(f"\n  Next Earnings     : {result.next_earnings_date}")
        if result.catalyst:
            print(f"  Catalyst          : {result.catalyst}")
        print(f"  TEMPLATE          : {'✅ PASSED' if passed else '❌ FAILED'}")
        print(f"  ACTIONABLE        : {'✅ YES — within buy zone' if result.actionable else '❌ NO — extended or template fail'}")
        print(f"{'='*55}\n")


# ---------------------------------------------------------------------------
# Quick-start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Minervini Stock Screener')
    parser.add_argument('-sp400', action='store_true', help='Screen S&P 400 (Mid-Cap) stocks')
    parser.add_argument('-sp600', action='store_true', help='Screen S&P 600 (Small-Cap) stocks')
    parser.add_argument('--audit', type=str, help='Audit a specific stock symbol')
    parser.add_argument('--limit', type=int, default=10, help='Number of results to return (default: 10)')
    parser.add_argument('--date', type=str, help='Run screener as of this date (YYYY-MM-DD) for backtesting')
    args = parser.parse_args()

    reference_date = None
    if args.date:
        try:
            reference_date = datetime.strptime(args.date, '%Y-%m-%d').date()
            print(f"Time-travel mode: analyzing as of {reference_date}")
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD")
            sys.exit(1)

    screener = MinerviniScreener()

    # Determine which index to use
    if args.sp400:
        index = 'sp400'
        index_name = 'S&P 400 (Mid-Cap)'
    elif args.sp600:
        index = 'sp600'
        index_name = 'S&P 600 (Small-Cap)'
    else:
        index = 'sp500'
        index_name = 'S&P 500'

    # Audit specific stock if requested
    if args.audit:
        benchmark_map = {'sp500': '^GSPC', 'sp400': '^SP400', 'sp600': '^SP600'}
        ref_date = datetime.combine(reference_date, datetime.min.time()) if reference_date else None
        screener.audit_stock(args.audit.upper(), benchmark_map[index], ref_date)
        sys.exit(0)

    # Audit specific stocks to verify logic (skip in backtest mode)
    if not reference_date:
        for ticker in ["MU", "GOOG", "APH", "DELL", "MSFT"]:
            screener.audit_stock(ticker)

    # Full screen — only stocks passing ALL Minervini criteria
    print(f"\nRunning full {index_name} screen...\n")
    ref_date = datetime.combine(reference_date, datetime.min.time()) if reference_date else None
    top = screener.find_top_opportunities(minervini_pass_only=True, limit=args.limit, index=index, reference_date=ref_date)
    for i, s in enumerate(top, 1):
        print(f"{i:2}. {s.symbol:<6}  Score: {s.overall_score:.1f}  RS: {s.rs_rating:.0f}  "
              f"Price: ${s.price:.2f}  Signals: {'; '.join(s.signals)}")
