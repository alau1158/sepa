import pandas as pd
import numpy as np


def detect_vcp(df):
    if len(df) < 50:
        return "No VCP", 0

    closes = df["Close"]
    highs = df["High"]
    lows = df["Low"]
    volumes = df["Volume"]

    tr = pd.concat(
        [
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows - closes.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_10 = tr.rolling(10).mean().iloc[-1]
    atr_22 = tr.rolling(22).mean().iloc[-1]

    atr_ratio = atr_10 / atr_22 if atr_22 > 0 else 1
    atr_score = max(0, (1 - atr_ratio) * 100)

    vol_10 = volumes.rolling(10).mean().iloc[-1]
    vol_50 = volumes.rolling(50).mean().iloc[-1]
    vol_ratio = vol_10 / vol_50 if vol_50 > 0 else 1
    vol_score = max(0, (1 - vol_ratio) * 100)

    window_size = 8
    range_score = 0
    if len(df) >= window_size * 3 + 5:
        recent = df.iloc[-window_size:]
        mid = df.iloc[-window_size * 2 : -window_size]
        early = df.iloc[-window_size * 3 : -window_size * 2]

        def window_range(w):
            return (w["High"].max() - w["Low"].min()) / w["Close"].mean() * 100

        r3 = window_range(recent)
        r2 = window_range(mid)
        r1 = window_range(early)

        if r2 < r1 * 0.85:
            range_score += 20
        if r3 < r2 * 0.85:
            range_score += 30
        if r3 < r1 * 0.7:
            range_score += 20

    score = min(100, int(atr_score * 0.3 + vol_score * 0.3 + range_score))

    if score >= 70:
        status = "VCP Tight"
    elif score >= 40:
        status = "VCP Forming"
    else:
        status = "No VCP"

    return status, score
