import pandas as pd


def _true_range(highs, lows, closes):
    return pd.concat(
        [
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows - closes.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)


def detect_vcp(df):
    if len(df) < 60:
        return "No VCP", 0

    highs = df["High"]
    lows = df["Low"]
    closes = df["Close"]
    volumes = df["Volume"]

    tr = _true_range(highs, lows, closes)

    atr_50 = tr.rolling(50).mean().iloc[-1]
    atr_25 = tr.rolling(25).mean().iloc[-1]
    atr_10 = tr.rolling(10).mean().iloc[-1]
    atr_5 = tr.rolling(5).mean().iloc[-1]
    atr_2 = tr.rolling(2).mean().iloc[-1]

    score = 0

    if atr_25 < atr_50 * 0.90:
        score += 10
    if atr_10 < atr_25 * 0.90:
        score += 15
    if atr_5 < atr_10 * 0.85:
        score += 20
    if atr_2 < atr_5 * 0.80:
        score += 25

    if (
        atr_25 < atr_50 * 0.90
        and atr_10 < atr_25 * 0.90
        and atr_5 < atr_10 * 0.85
        and atr_2 < atr_5 * 0.80
    ):
        score += 10

    vol_50 = volumes.rolling(50).mean().iloc[-1]
    vol_25 = volumes.rolling(25).mean().iloc[-1]
    vol_10 = volumes.rolling(10).mean().iloc[-1]
    vol_5 = volumes.rolling(5).mean().iloc[-1]
    vol_2 = volumes.rolling(2).mean().iloc[-1]

    if vol_25 < vol_50 * 0.90:
        score += 4
    if vol_10 < vol_25 * 0.90:
        score += 4
    if vol_5 < vol_10 * 0.85:
        score += 4
    if vol_2 < vol_5 * 0.80:
        score += 4

    if (
        vol_25 < vol_50 * 0.90
        and vol_10 < vol_25 * 0.90
        and vol_5 < vol_10 * 0.85
        and vol_2 < vol_5 * 0.80
    ):
        score += 4

    if len(df) >= 30:
        recent = df.iloc[-10:]
        mid = df.iloc[-20:-10]
        early = df.iloc[-30:-20]

        def window_range(w):
            return (w["High"].max() - w["Low"].min()) / w["Close"].mean() * 100

        r3 = window_range(recent)
        r2 = window_range(mid)
        r1 = window_range(early)

        if r2 < r1 * 0.85:
            score += 3
        if r3 < r2 * 0.85:
            score += 2

    score = int(min(100, score))

    if score >= 70:
        status = "VCP Tight"
    elif score >= 40:
        status = "VCP Forming"
    else:
        status = "No VCP"

    return status, score
