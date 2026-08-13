import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import List
from scipy.stats import percentileofscore
from dotenv import load_dotenv
import argparse

load_dotenv()

from screener import MinerviniScreener, StockAnalysis
from notifier import EmailNotifier
from api_clients import fetch_stock_data
from ai_analyst import get_ai_analysis


class ReportGenerator:
    def __init__(self):
        self.screener = MinerviniScreener()
        self.notifier = EmailNotifier()
    
    def format_price(self, price: float) -> str:
        return f"${price:.2f}"
    
    def format_pct(self, pct: float) -> str:
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct:.2f}%"
    
    def generate_report(self, recipient: str, index: str = 'sp500') -> bool:
        # Map index to display name
        index_names = {
            'sp500': 'S&P 500',
            'sp400': 'S&P 400 (Mid-Cap)',
            'sp600': 'S&P 600 (Small-Cap)'
        }
        index_name = index_names.get(index, 'S&P 500')

        print(f"Generating weekly report for {index_name}...")

        print("\n=== Finding top opportunities ===")
        opportunities = self.screener.find_top_opportunities(minervini_pass_only=True, limit=50, index=index)

        # Sort by status priority: BREAKOUT > SETUP > NEAR 50-MA > ACTIONABLE > EXTENDED > Watch only
        def get_status_priority(o):
            if o.vcp_breakout:
                return 0  # BREAKOUT
            elif o.vcp_pattern_detected and not o.extended_from_50ma:
                return 1  # SETUP
            elif o.actionable and not o.vcp_pattern_detected and o.pct_from_50ma < 5:
                return 2  # NEAR 50-MA
            elif o.actionable:
                return 3  # ACTIONABLE
            elif o.extended_from_50ma:
                return 4  # EXTENDED
            else:
                return 5  # Watch only

        opportunities.sort(key=lambda x: -x.rs_rating)

        all_symbols_for_api = [o.symbol for o in opportunities]
        print(f"Fetching earnings and news data for {len(all_symbols_for_api)} symbols...")
        external_data = fetch_stock_data(all_symbols_for_api, use_finnhub=True)

        for o in opportunities:
            if o.symbol in external_data:
                data = external_data[o.symbol]
                if not o.next_earnings_date:
                    o.next_earnings_date = data.get("next_earnings")
                if not o.catalyst:
                    o.catalyst = data.get("catalyst")

        print("\n=== Running AI Analysis ===")
        ai_analysis = get_ai_analysis(opportunities)

        # Market-overview GEX (same DTE window as the stocks below).
        print("\n=== Fetching market GEX (QQQ + SPY) ===")
        market_gex = {
            'QQQ': self.screener.get_market_gex('QQQ', max_dte_days=7),
            'SPY': self.screener.get_market_gex('SPY', max_dte_days=7),
        }

        def _market_cell(m: dict) -> str:
            sym = m.get('symbol', '?')
            price = m.get('price')
            change_pct = m.get('change_pct')
            gex = m.get('gex')
            expiry = m.get('expiration')

            price_str = f"${price:.2f}" if price is not None else "n/a"
            if change_pct is None:
                chg_html = ""
            elif change_pct >= 0:
                chg_html = f' <span class="positive">+{change_pct:.2f}%</span>'
            else:
                chg_html = f' <span class="negative">{change_pct:.2f}%</span>'

            if gex is None:
                gex_html = '<span style="color:#7f8c8d;">GEX: n/a (no expiry ≤ 7d)</span>'
                regime_html = ""
            else:
                gex_m = gex / 1e6
                if gex_m < 0:
                    gex_html = f'<span class="positive">GEX: -${abs(gex_m):,.1f}M / 1%</span>'
                    regime_html = ' <span class="positive">(vol-amplifying, favors breakouts)</span>'
                else:
                    gex_html = f'<span class="negative">GEX: +${gex_m:,.1f}M / 1%</span>'
                    regime_html = ' <span class="negative">(vol-suppressing, fades breakouts)</span>'
                if expiry:
                    gex_html += f' <small style="color:#7f8c8d;">[{expiry}]</small>'

            return (
                f'<div style="flex:1; min-width:280px; padding:12px; '
                f'background:#ffffff; border:1px solid #ddd; border-radius:6px;">'
                f'<div style="font-size:16px;"><strong>{sym}</strong> {price_str}{chg_html}</div>'
                f'<div style="margin-top:6px;">{gex_html}{regime_html}</div>'
                f'</div>'
            )

        market_banner_html = (
            '<div style="display:flex; gap:12px; flex-wrap:wrap; margin:0 0 20px 0;">'
            + _market_cell(market_gex['QQQ'])
            + _market_cell(market_gex['SPY'])
            + '</div>'
        )

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #2c3e50; }}
                h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
                table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
                th {{ background-color: #3498db; color: white; }}
                .optimal {{ color: #27ae60; font-weight: bold; }}
                .good {{ color: #2980b9; }}
                .weak {{ color: #f39c12; }}
                .sell {{ color: #e74c3c; font-weight: bold; }}
                .positive {{ color: #27ae60; }}
                .negative {{ color: #e74c3c; }}
                .signals {{ background-color: #ecf0f1; padding: 10px; border-radius: 5px; }}
                .summary {{ background-color: #e8f6f3; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .ai-buy {{ color: #27ae60; font-weight: bold; }}
                .ai-hold {{ color: #f39c12; }}
                .ai-skip {{ color: #e74c3c; }}
                .sentiment-positive {{ color: #27ae60; font-weight: bold; }}
                .sentiment-negative {{ color: #e74c3c; font-weight: bold; }}
                .sentiment-neutral {{ color: #f39c12; }}
            </style>
        </head>
        <body>
            <h1>📈 Minervini SEPA - {index_name} - {datetime.now().strftime('%Y-%m-%d')}</h1>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

            <h2 style="border:none; margin-bottom:8px;">Market GEX Overview</h2>
            <p style="color:#7f8c8d; font-size:12px; margin-top:0;">
                Same ≤7-day expiration window used for individual stocks below.
                <span class="positive">Green = negative GEX (good for breakouts)</span>,
                <span class="negative">red = positive GEX (breakouts may fade)</span>.
            </p>
            {market_banner_html}

            <div class="summary">
                <h3>Summary</h3>
                <p><strong>Index:</strong> {index_name}</p>
                <p><strong>Top Opportunities:</strong> {len(opportunities)} stocks passing Minervini template</p>
            </div>

            <h2>Top Opportunities (Minervini Pass) — sorted by RS Rating</h2>
            <p style="color: #7f8c8d; font-size: 13px;">
                <strong>Reading this report:</strong> Focus on rows with <span class="optimal">✅</span> Status.
                Skip <span class="sell">⚠️ EXTENDED</span> rows — these are climactic and Minervini's rules
                say do not chase. Many stocks will pass the trend template but few are actionable today;
                that is normal and the system is telling you to be patient.
            </p>
        """

        if opportunities:
            html += """
            <table>
                <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>Status</th>
                    <th>% from<br>50-MA</th>
                    <th>RS</th>
                    <th>Trend</th>
                    <th>ATR%</th>
                    <th>Earnings</th>
                    <th>VCP</th>
                    <th>Pivot<br>(Buy)</th>
                    <th>Stop<br>(Recent Low)</th>
                    <th>Contractions</th>
                    <th>Vol</th>
                    <th>GEX<br>(per 1%)</th>
                    <th>AI</th>
                </tr>
            """
            for opp in opportunities:
                earnings = opp.next_earnings_date or "-"

                # ACTIONABLE STATUS — primary signal for the trader
                if opp.extended_from_50ma:
                    status_cell = '<span class="sell">⚠️ EXTENDED<br><small>Do not chase</small></span>'
                elif opp.actionable:
                    if opp.vcp_pattern_detected and opp.vcp_breakout:
                        status_cell = '<span class="optimal">🚀 BREAKOUT<br><small>Buy now</small></span>'
                    elif opp.vcp_pattern_detected:
                        status_cell = '<span class="optimal">✅ SETUP<br><small>Wait for pivot</small></span>'
                    elif opp.pct_from_50ma < 5:
                        status_cell = '<span class="good">✅ NEAR 50-MA<br><small>Buy zone</small></span>'
                    else:
                        status_cell = '<span class="good">✅ ACTIONABLE</span>'
                else:
                    status_cell = '<span class="weak">⚠️ Watch only</span>'

                # % from 50-MA cell with color
                pct_50_value = opp.pct_from_50ma
                if pct_50_value > 25:
                    pct_50_cell = f'<span class="sell">{pct_50_value:+.1f}%</span>'
                elif pct_50_value > 15:
                    pct_50_cell = f'<span class="weak">{pct_50_value:+.1f}%</span>'
                else:
                    pct_50_cell = f'<span class="positive">{pct_50_value:+.1f}%</span>'

                # VCP cell — show ✅ + breakout flag if applicable
                if opp.vcp_pattern_detected:
                    if opp.vcp_breakout:
                        vcp_cell = "✅ 🚀<br><small>Breakout</small>"
                    else:
                        vcp_cell = "✅"
                        if opp.vcp_volume_dryup:
                            vcp_cell += "<br><small>Vol dry-up</small>"
                else:
                    vcp_cell = "—"

                # Pivot price (breakout trigger / buy point)
                pivot_cell = (
                    self.format_price(opp.vcp_pivot_price)
                    if opp.vcp_pivot_price else "-"
                )

                # Stop-loss = most recent swing low (or 50-MA fallback if no VCP)
                if opp.vcp_recent_low:
                    risk_pct = ((opp.price - opp.vcp_recent_low) / opp.price) * 100
                    stop_cell = (
                        f"{self.format_price(opp.vcp_recent_low)}"
                        f"<br><small>-{risk_pct:.1f}% from price</small>"
                    )
                else:
                    # Fallback: suggest 50-MA as stop reference
                    risk_pct = ((opp.price - opp.ma_50) / opp.price) * 100
                    stop_cell = (
                        f"{self.format_price(opp.ma_50)}"
                        f"<br><small>50-MA, -{risk_pct:.1f}%</small>"
                    )

                # Contraction footprint (e.g. 18% → 9% → 4%)
                if opp.vcp_contractions:
                    contractions_cell = " → ".join(
                        f"{c:.1f}%" for c in opp.vcp_contractions
                    )
                else:
                    contractions_cell = "-"

                # Volume check: Minervini requires volume spike at breakout
                # SETUP: need 1.4x+ the 50-day avg, NEAR 50-MA: need 1.5x+
                vol_ratio = opp.volume_ratio if opp.volume_ratio else 0.0
                is_setup = opp.vcp_pattern_detected and not opp.vcp_breakout and not opp.extended_from_50ma
                is_near_50ma = opp.actionable and not opp.vcp_pattern_detected and opp.pct_from_50ma < 5
                if is_setup:
                    if vol_ratio >= 1.4:
                        vol_cell = '<span class="positive">✅ 1.4x</span>'
                    else:
                        vol_cell = '<span class="negative">❌ 1.4x</span>'
                elif is_near_50ma:
                    if vol_ratio >= 1.5:
                        vol_cell = '<span class="positive">✅ 1.5x</span>'
                    else:
                        vol_cell = '<span class="negative">❌ 1.5x</span>'
                elif opp.vcp_breakout:
                    vol_cell = '<span class="optimal">🚀</span>'
                else:
                    vol_cell = "—"

                atr_pct = f"{opp.atr_pct:.2f}%" if opp.atr_pct else "-"

                # GEX cell — dealer gamma exposure for nearest expiry.
                # For VCP/breakout traders: NEGATIVE GEX is bullish (dealers chase
                # price, fueling breakouts), POSITIVE GEX is bearish (dealers fade
                # price, breakouts stall). Colors reflect breakout-trader view:
                # green = negative GEX, red = positive GEX.
                if opp.gex is not None:
                    gex_m = opp.gex / 1e6  # display in $M
                    if gex_m < 0:
                        gex_cell = (
                            f'<span class="positive">-${abs(gex_m):,.1f}M</span>'
                            f'<br><small>{opp.gex_expiration or ""}</small>'
                        )
                    else:
                        gex_cell = (
                            f'<span class="negative">+${gex_m:,.1f}M</span>'
                            f'<br><small>{opp.gex_expiration or ""}</small>'
                        )
                else:
                    gex_cell = "-"

                ai = ai_analysis.get(opp.symbol) if ai_analysis else None
                if ai and ai.sentiment:
                    sent = ai.sentiment.lower()
                    if sent == "positive":
                        sentiment = '<span class="sentiment-positive">🟢</span>'
                    elif sent == "negative":
                        sentiment = '<span class="sentiment-negative">🔴</span>'
                    else:
                        sentiment = '<span class="sentiment-neutral">🟡</span>'
                else:
                    sentiment = "-"
                html += f"""
                <tr>
                    <td><a href="https://www.tradingview.com/chart/?symbol={opp.symbol}" style="color: inherit; text-decoration: none;"><strong>{opp.symbol}</strong></a><br><small>{opp.name}</small></td>
                    <td>{self.format_price(opp.price)}</td>
                    <td>{status_cell}</td>
                    <td>{pct_50_cell}</td>
                    <td>{opp.rs_rating:.0f}</td>
                    <td>{opp.trend_score}/9</td>
                    <td>{atr_pct}</td>
                    <td>{earnings}</td>
                    <td>{vcp_cell}</td>
                    <td>{pivot_cell}</td>
                    <td>{stop_cell}</td>
                    <td><small>{contractions_cell}</small></td>
                    <td>{vol_cell}</td>
                    <td>{gex_cell}</td>
                    <td>{sentiment}</td>
                </tr>
                """
            html += "</table>"
        else:
            html += "<p>No stocks currently passing the Minervini template.</p>"

        html += """
            <h2>Understanding the Report</h2>
            <ul>
                <li><strong>Status:</strong> The PRIMARY trading signal:
                    <ul>
                        <li><span class="optimal">🚀 BREAKOUT</span> — VCP detected and price has closed above pivot on volume. <strong>Buy now.</strong></li>
                        <li><span class="optimal">✅ SETUP</span> — Valid VCP forming, wait for pivot break. <strong>Set buy stop at pivot.</strong></li>
                        <li><span class="good">✅ NEAR 50-MA</span> — Price within 5% of 50-MA after prior breakout. <strong>Classic Minervini pullback entry.</strong></li>
                        <li><span class="good">✅ ACTIONABLE</span> — Template passes, within buy zone (≤25% above 50-MA).</li>
                        <li><span class="sell">⚠️ EXTENDED</span> — More than 25% above 50-MA. <strong>Do not chase.</strong> Already-held positions: consider trimming. Wait for a 4+ week base before re-entering.</li>
                        <li><span class="weak">⚠️ Watch only</span> — Template passes but conditions not yet ideal for entry.</li>
                    </ul>
                </li>
                <li><strong>% from 50-MA:</strong> Distance of current price from the 50-day MA. Minervini's "buy zone" is typically 0-15% above; 15-25% is stretched; &gt;25% is climactic.</li>
                <li><strong>RS:</strong> Relative strength rating (0-100, higher is better)</li>
                <li><strong>Trend:</strong> Minervini template checks passed (X/9)</li>
                <li><strong>VCP:</strong> Volatility Contraction Pattern (✅ = valid VCP, 🚀 = breakout above pivot, "Vol dry-up" = volume contracting on final leg)</li>
                <li><strong>Pivot (Buy):</strong> Most recent swing high — the breakout trigger / buy point. Enter when price closes above pivot on above-average volume.</li>
                <li><strong>Stop (Recent Low):</strong> Most recent swing low — your stop-loss level. If no VCP detected, the 50-MA is shown as a reference stop.</li>
                <li><strong>Contractions:</strong> Sequence of pullback depths (oldest → newest). Valid VCPs show each leg shallower than the last (e.g. 18% → 9% → 4%).</li>
                <li><strong>Vol:</strong> Previous day volume vs 50-day average. For SETUP stocks: need ≥1.4× to confirm breakout. For NEAR 50-MA: need ≥1.5× for pullback entry confirmation. ✅ = passes, ❌ = fails.</li>
                <li><strong>GEX (per 1%):</strong> Dealer net Gamma Exposure for the nearest options expiry <strong>within 7 calendar days</strong>, expressed as $ change in dealer delta per 1% move in spot. Stocks whose nearest expiration is further out (e.g. monthly-only chains) show "-" since far-dated GEX is not actionable for short-term breakout trading. Calls treated as dealer-long, puts as dealer-short. <em>Colors reflect the breakout-trader view: green = bullish for VCP entries, red = bearish.</em>
                    <ul>
                        <li><span class="positive">Negative GEX (green)</span> — dealers must buy rallies / sell dips. Vol-amplifying, trending tape. <strong>Favors VCP breakouts and momentum continuation.</strong></li>
                        <li><span class="negative">Positive GEX (red)</span> — dealers must sell rallies / buy dips. Vol-suppressing, mean-reverting tape. <strong>Breakouts tend to fade — be cautious.</strong></li>
                    </ul>
                </li>
                <li><strong>AI:</strong> Sentiment based on earnings and news (🟢 Positive / 🟡 Neutral / 🔴 Negative)</li>
            </ul>

            <h2>Minervini Trading Plan</h2>
            <ol>
                <li><strong>Only buy ACTIONABLE setups:</strong> Skip anything marked EXTENDED — chasing a stock &gt;25% above its 50-MA is how Minervini-style traders give back gains.</li>
                <li><strong>Wait for breakout:</strong> For VCP setups, price must close above the <em>Pivot</em> on volume ≥ 1.4× the 50-day average.</li>
                <li><strong>Enter at pivot:</strong> Buy as close to the pivot as possible — never chase more than 5% above.</li>
                <li><strong>Set hard stop:</strong> Place stop-loss just below the <em>Recent Low</em> (or 50-MA for non-VCP setups). Max risk per trade = 1-2% of portfolio.</li>
                <li><strong>Take profits on extended stocks:</strong> When a held position becomes EXTENDED, trim 1/3-1/2 into strength. Re-enter on the next valid base.</li>
            </ol>

            <h2>Minervini Trend Template Criteria (9 Total)</h2>
            <ol>
                <li>Current price > 50-day moving average</li>
                <li>Current price > 150-day moving average</li>
                <li>Current price > 200-day moving average</li>
                <li>50-day MA > 150-day MA and 50-day MA > 200-day MA</li>
                <li>150-day MA > 200-day MA</li>
                <li>200-day MA trending up (2-month confirmed)</li>
                <li>Price within 25% of 52-week high</li>
                <li>Price ≥30% above 52-week low</li>
                <li>RS rating (intra-index percentile) ≥80</li>
            </ol>

            <h2>Position Sizing Formula (Risk Management)</h2>
            <p><strong>S = (0.02T) / (E × 1.5A)</strong></p>
            <ul>
                <li><strong>S</strong> = Number of shares</li>
                <li><strong>E</strong> = Entry price</li>
                <li><strong>T</strong> = Total portfolio size</li>
                <li><strong>A</strong> = ATR % (e.g., 2.5% = 2.5)</li>
            </ul>
            
            <p style="margin-top: 30px; color: #7f8c8d; font-size: 12px;">
                This report is generated based on Mark Minervini's stock selection method.<br>
                Always do your own due diligence before making investment decisions.<br>
                Refer to <a href="https://github.com/alau1158/Minervini-SEPA">https://github.com/alau1158/Minervini-SEPA</a> for more information.
            </p>
        </body>
        </html>
        """
        
        subject = f"Minervini SEPA stocks - {datetime.now().strftime('%Y-%m-%d')}"
        return self.notifier.send_report(recipient, subject, html)
    
    def run_weekly(self, index: str = 'sp500'):
        recipients = os.getenv("RECIPIENTS", os.getenv("SMTP_USER"))
        self.generate_report(recipients, index)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Minervini Weekly Report Generator')
    parser.add_argument('-sp400', action='store_true', help='Use S&P 400 (Mid-Cap) stocks')
    parser.add_argument('-sp600', action='store_true', help='Use S&P 600 (Small-Cap) stocks')
    args = parser.parse_args()

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

    print(f"Generating report for {index_name}...")
    report = ReportGenerator()
    report.run_weekly(index)
