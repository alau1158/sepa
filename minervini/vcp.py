import pandas as pd


def detect_vcp(df):
    if len(df) < 55:
        return "No VCP", 0

    formation = df.iloc[-55:-5]
    action = df.iloc[-5:]

    n = len(formation)
    chunk = max(1, n // 5)

    ranges = []
    volumes = []
    for i in range(5):
        w = formation.iloc[i * chunk : (i + 1) * chunk]
        if len(w) < 2:
            return "No VCP", 0
        r = (w["High"].max() - w["Low"].min()) / w["Close"].mean() * 100
        v = w["Volume"].mean()
        ranges.append(r)
        volumes.append(v)

    score = 0

    rc = 0
    for i in range(1, 5):
        thresh = 0.88 + (i - 1) * 0.03
        if ranges[i] < ranges[i - 1] * thresh:
            rc += 1

    if ranges[4] <= min(ranges[:4]) * 1.02:
        rc += 1

    avg_first_two = (ranges[0] + ranges[1]) / 2
    avg_last_two = (ranges[3] + ranges[4]) / 2

    if avg_last_two < avg_first_two:
        rc += 1

    if avg_last_two < avg_first_two * 0.75 and ranges[4] < ranges[3] * 1.10:
        rc += 1
    score += rc * 10

    vc = 0
    for i in range(1, 5):
        if volumes[i] < volumes[i - 1] * 0.90:
            vc += 1
    avg_v_first = (volumes[0] + volumes[1]) / 2
    avg_v_last = (volumes[3] + volumes[4]) / 2
    if avg_v_last < avg_v_first * 0.80 and volumes[4] < volumes[3] * 1.10:
        vc += 1
    score += vc * 5

    base_high = formation["High"].max()
    action_close = action["Close"].iloc[-1]
    action_vol = action["Volume"].mean()
    formation_vol = formation["Volume"].mean()

    avg_daily_range = (formation["High"] - formation["Low"]).mean()
    avg_daily_range_pct = avg_daily_range / formation["Close"].mean() * 100
    power_day = any(
        (r["High"] - r["Low"]) / r["Close"] * 100 > avg_daily_range_pct * 2
        and r["Close"] > r["High"] * 0.90
        for _, r in action.iterrows()
    )
    action_sma5 = action["Close"].mean()
    if power_day and action_close > action_sma5:
        score += 10

    if action_vol > formation_vol * 1.2:
        score += 10

    if action_close > base_high:
        score += 10
        if action_close >= base_high * 1.02:
            score += 5

    score = int(min(100, score))

    if score >= 60:
        status = "VCP Tight"
    elif score >= 45:
        status = "VCP Forming"
    else:
        status = "No VCP"

    return status, score
