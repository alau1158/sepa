import pandas as pd

from . import indicators as ind
from . import rs_rating as rsr
from . import vcp as vcp_module
from . import sell_signals as sell
from . import earnings as earn
from . import fundamentals as fund


def screen_stocks(data_dict):
    rs_ratings = rsr.compute_rs_ratings(data_dict)

    all_tickers = list(data_dict.keys())
    spy_df = data_dict.get("SPY")

    results = []
    for ticker, df in data_dict.items():
        if len(df) < 250:
            continue

        try:
            c1 = ind.check_price_above_ma(df, 150) and ind.check_price_above_ma(df, 200)
            c2 = ind.check_ma_above_ma(df, 150, 200)
            c3 = ind.check_ma_slope(df, 200, 22)
            c4 = ind.check_ma_above_ma(df, 50, 150) and ind.check_ma_above_ma(df, 50, 200)
            c5 = ind.check_price_above_ma(df, 50)
            c6 = ind.above_52w_low_pct(df) >= 30
            c7 = ind.within_52w_high_pct(df) <= 25
            c8 = rs_ratings.get(ticker, 0) >= 80

            score = sum([c1, c2, c3, c4, c5, c6, c7, c8])

            if score == 8:
                price = round(df["Close"].iloc[-1], 2)
                vs_50 = ind.price_distance_from_sma(df, 50)
                atr_val = ind.compute_atr_value(df, 22)
                rs_val = rs_ratings.get(ticker, 0)

                ad_letter, ad_score = ind.compute_ad_rating(df)

                rs_div = "N/A"
                rs_trend = "N/A"
                corr_div = "N/A"
                if spy_df is not None and ticker != "SPY":
                    rs_line = ind.compute_rs_line(df["Close"], spy_df["Close"])
                    rs_trend_bool, rs_slope = ind.check_rs_line_trend(rs_line, 65)
                    rs_trend = "Up" if rs_trend_bool else "Down"
                    rs_div = ind.check_rs_divergence(rs_line, df["Close"], 65)
                    corr_div = ind.check_correction_divergence(df, spy_df, 5)

                results.append(
                    {
                        "Ticker": ticker,
                        "Price": price,
                        "vs_50_SMA%": round(vs_50, 2) if vs_50 is not None else None,
                        "ATR%": atr_val,
                        "VCP_Status": None,
                        "VCP_Score": None,
                        "AD": ad_letter,
                        "EPS_Rating": None,
                        "Ind_Rank": None,
                        "Next_Earnings": None,
                        "RS_Rating": rs_val,
                        "RS_Trend": rs_trend,
                        "RS_Div": rs_div,
                        "Corr_Div": corr_div,
                        "Brk_Order": None,
                        "Exh_Score": None,
                        "Exh_Status": None,
                        "Dist_Score": None,
                        "Dist_Status": None,
                    }
                )
        except Exception:
            continue

    if not results:
        return pd.DataFrame()

    df_results = pd.DataFrame(results)
    passing_tickers = df_results["Ticker"].tolist()

    for idx, row in df_results.iterrows():
        ticker = row["Ticker"]
        df = data_dict[ticker]
        status, score = vcp_module.detect_vcp(df)
        df_results.at[idx, "VCP_Status"] = status
        df_results.at[idx, "VCP_Score"] = score

    earnings_cache = earn.get_earnings_cache(passing_tickers)
    for idx, row in df_results.iterrows():
        ticker = row["Ticker"]
        df_results.at[idx, "Next_Earnings"] = earnings_cache.get(ticker, "N/A")

    industries = fund.get_industries(all_tickers)
    ind_ranks = fund.compute_industry_ranks(
        all_tickers, passing_tickers, rs_ratings, industries
    )
    for idx, row in df_results.iterrows():
        ticker = row["Ticker"]
        rank_info = ind_ranks.get(ticker, (None, None))
        rank, total = rank_info
        if rank is not None:
            df_results.at[idx, "Ind_Rank"] = f"{rank}/{total}"
        else:
            df_results.at[idx, "Ind_Rank"] = "N/A"

    breakout_order = fund.compute_breakout_order(
        passing_tickers, data_dict, industries
    )
    for idx, row in df_results.iterrows():
        ticker = row["Ticker"]
        order, total = breakout_order.get(ticker, ("N/A", 0))
        if order != "N/A":
            df_results.at[idx, "Brk_Order"] = f"{order}/{total}"
        else:
            df_results.at[idx, "Brk_Order"] = "N/A"

    eps_data = fund.get_eps_data(passing_tickers)
    eps_ratings = fund.compute_eps_ratings(passing_tickers, eps_data)
    for idx, row in df_results.iterrows():
        ticker = row["Ticker"]
        df_results.at[idx, "EPS_Rating"] = eps_ratings.get(ticker)

    for idx, row in df_results.iterrows():
        ticker = row["Ticker"]
        df = data_dict[ticker]
        ex_score, ex_status = sell.compute_exhaustion_score(df)
        di_score, di_status = sell.compute_distribution_score(df)
        df_results.at[idx, "Exh_Score"] = ex_score
        df_results.at[idx, "Exh_Status"] = ex_status
        df_results.at[idx, "Dist_Score"] = di_score
        df_results.at[idx, "Dist_Status"] = di_status

    df_results = df_results.sort_values("RS_Rating", ascending=False).reset_index(drop=True)
    return df_results
