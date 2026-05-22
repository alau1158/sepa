def compute_weighted_return(df):
    closes = df["Close"]
    current = closes.iloc[-1]

    if len(closes) < 252:
        return None

    close_3m = closes.iloc[-63]
    close_6m = closes.iloc[-126]
    close_9m = closes.iloc[-189]
    close_12m = closes.iloc[-252]

    ret_3m = (current - close_3m) / close_3m * 100
    ret_6m = (current - close_6m) / close_6m * 100
    ret_9m = (current - close_9m) / close_9m * 100
    ret_12m = (current - close_12m) / close_12m * 100

    return ret_3m * 0.4 + ret_6m * 0.2 + ret_9m * 0.2 + ret_12m * 0.2


def compute_rs_ratings(data_dict):
    returns = {}
    for ticker, df in data_dict.items():
        ret = compute_weighted_return(df)
        if ret is not None:
            returns[ticker] = ret

    if not returns:
        return {}

    sorted_tickers = sorted(returns.items(), key=lambda x: x[1])
    n = len(sorted_tickers)

    ratings = {}
    for i, (ticker, _) in enumerate(sorted_tickers):
        percentile = (i / (n - 1)) * 98 + 1 if n > 1 else 50
        ratings[ticker] = round(percentile)

    return ratings
