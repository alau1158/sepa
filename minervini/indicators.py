import pandas as pd
import numpy as np


def compute_sma(series, period):
    return series.rolling(window=period).mean()


def check_price_above_ma(df, period):
    sma = compute_sma(df["Close"], period)
    if pd.isna(sma.iloc[-1]):
        return False
    return df["Close"].iloc[-1] > sma.iloc[-1]


def check_ma_above_ma(df, period_upper, period_lower):
    sma_upper = compute_sma(df["Close"], period_upper)
    sma_lower = compute_sma(df["Close"], period_lower)
    if pd.isna(sma_upper.iloc[-1]) or pd.isna(sma_lower.iloc[-1]):
        return False
    return sma_upper.iloc[-1] > sma_lower.iloc[-1]


def check_ma_slope(df, period, lookback=22):
    sma = compute_sma(df["Close"], period)
    if len(sma) <= lookback or pd.isna(sma.iloc[-1]) or pd.isna(sma.iloc[-(lookback + 1)]):
        return False
    return sma.iloc[-1] > sma.iloc[-(lookback + 1)]


def compute_atr(df, period=22):
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period).mean()


def above_52w_low_pct(df):
    current = df["Close"].iloc[-1]
    low_52w = df["Close"].min()
    return ((current - low_52w) / low_52w) * 100


def within_52w_high_pct(df):
    current = df["Close"].iloc[-1]
    high_52w = df["Close"].max()
    return ((high_52w - current) / high_52w) * 100


def price_distance_from_sma(df, period):
    sma = compute_sma(df["Close"], period)
    if pd.isna(sma.iloc[-1]):
        return None
    return ((df["Close"].iloc[-1] - sma.iloc[-1]) / sma.iloc[-1]) * 100


def compute_atr_value(df, period=22):
    atr = compute_atr(df, period)
    if pd.isna(atr.iloc[-1]):
        return None
    pct = (atr.iloc[-1] / df["Close"].iloc[-1]) * 100
    return round(pct, 2)
