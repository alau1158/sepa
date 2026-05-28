import os
import socket

import pandas as pd
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def load_transactions(csv_path: str = "journal.csv") -> pd.DataFrame:
    """Load transactions from CSV (new format: broker,action,ticket,quantity,date,price)"""
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip().str.lower()
    
    # Clean and validate columns
    df['action'] = df['action'].str.strip().str.lower()
    df['ticket'] = df['ticket'].str.strip().str.upper()
    df['broker'] = df['broker'].str.strip().str.lower()
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    
    # Parse date (supports YYYYMMDD format)
    df['date'] = pd.to_datetime(df['date'].astype(str).str.strip(), format='%Y%m%d', errors='coerce')
    
    # Filter valid transactions
    df = df.dropna(subset=['date', 'quantity', 'price'])
    # Sort by date, then by action (buy before sell for same-date transactions)
    df = df.sort_values(['date', 'action']).reset_index(drop=True)
    return df


def fifo_match(transactions: pd.DataFrame) -> Tuple[Dict, List[Dict]]:
    """
    Match sell transactions to buy transactions using FIFO per (broker, ticker)
    Returns: (open_positions, closed_trades)
    """
    open_positions = {}  # key: (broker, ticket), value: list of buy lots
    closed_trades = []
    
    for _, row in transactions.iterrows():
        key = (row['broker'], row['ticket'])
        action = row['action']
        qty = row['quantity']
        price = row['price']
        date = row['date']
        
        if action == 'buy':
            if key not in open_positions:
                open_positions[key] = []
            open_positions[key].append({
                'quantity': qty,
                'date': date,
                'price': price
            })
        
        elif action == 'sell':
            if key not in open_positions or not open_positions[key]:
                print(f"Warning: No open position for {key} to sell")
                continue
            
            remaining_sell_qty = qty
            while remaining_sell_qty > 0 and open_positions[key]:
                buy_lot = open_positions[key][0]
                
                if buy_lot['quantity'] <= remaining_sell_qty:
                    # Sell entire buy lot
                    sell_qty = buy_lot['quantity']
                    profit_loss = (price - buy_lot['price']) * sell_qty
                    
                    closed_trades.append({
                        'broker': row['broker'],
                        'ticket': row['ticket'],
                        'buy_date': buy_lot['date'],
                        'buy_price': buy_lot['price'],
                        'sell_date': date,
                        'sell_price': price,
                        'quantity': sell_qty,
                        'profit_loss': profit_loss
                    })
                    
                    remaining_sell_qty -= sell_qty
                    open_positions[key].pop(0)
                else:
                    # Sell partial buy lot
                    sell_qty = remaining_sell_qty
                    profit_loss = (price - buy_lot['price']) * sell_qty
                    
                    closed_trades.append({
                        'broker': row['broker'],
                        'ticket': row['ticket'],
                        'buy_date': buy_lot['date'],
                        'buy_price': buy_lot['price'],
                        'sell_date': date,
                        'sell_price': price,
                        'quantity': sell_qty,
                        'profit_loss': profit_loss
                    })
                    
                    buy_lot['quantity'] -= sell_qty
                    remaining_sell_qty = 0
            
            # Clean up empty lists
            if key in open_positions and not open_positions[key]:
                del open_positions[key]
    
    return open_positions, closed_trades


def get_open_positions(open_positions: Dict) -> List[Dict]:
    """Convert open positions dict to list of open lots"""
    result = []
    for (broker, ticket), lots in open_positions.items():
        for lot in lots:
            result.append({
                'broker': broker,
                'ticket': ticket,
                'quantity': lot['quantity'],
                'buy_date': lot['date'],
                'buy_price': lot['price']
            })
    return result


def get_portfolio_summary(open_positions: Dict, current_prices: Optional[Dict] = None) -> Dict:
    """Get aggregated portfolio summary per ticker"""
    summary = {}
    
    for (broker, ticket), lots in open_positions.items():
        key = f"{broker.upper()}-{ticket}"
        if key not in summary:
            summary[key] = {
                'broker': broker,
                'ticket': ticket,
                'total_quantity': 0,
                'total_cost': 0,
                'lots': []
            }
        
        for lot in lots:
            summary[key]['total_quantity'] += lot['quantity']
            summary[key]['total_cost'] += lot['quantity'] * lot['price']
            summary[key]['lots'].append(lot)
        
        # Calculate average cost
        if summary[key]['total_quantity'] > 0:
            summary[key]['avg_cost'] = summary[key]['total_cost'] / summary[key]['total_quantity']
        else:
            summary[key]['avg_cost'] = 0
    
    return summary


def load_transactions_from_sheet():
    import gspread

    _script_dir = os.path.dirname(os.path.abspath(__file__))

    creds_file = os.getenv("GOOGLE_CREDENTIALS")
    sheet_id = os.getenv("SHEET_ID")
    if not creds_file or not sheet_id:
        raise ValueError("GOOGLE_CREDENTIALS and SHEET_ID must be set in .env")
    if not os.path.isabs(creds_file):
        creds_file = os.path.join(_script_dir, creds_file)

    _gai = socket.getaddrinfo
    try:
        socket.getaddrinfo = lambda *a, **kw: [
            r for r in _gai(*a, **kw) if r[0] == socket.AF_INET
        ]
        gc = gspread.service_account(filename=creds_file)
        sh = gc.open_by_key(sheet_id)
        ws = sh.sheet1
        records = ws.get_all_values()
    finally:
        socket.getaddrinfo = _gai

    df = pd.DataFrame(records[1:], columns=records[0])
    df.columns = df.columns.str.strip().str.lower()
    df["action"] = df["action"].str.strip().str.lower()
    df["ticket"] = df["ticket"].str.strip().str.upper()
    df["broker"] = df["broker"].str.strip().str.lower()
    df["quantity"] = pd.to_numeric(df["quantity"].astype(str).str.replace(r'[\$,]', '', regex=True), errors="coerce")
    df["price"] = pd.to_numeric(df["price"].astype(str).str.replace(r'[\$,]', '', regex=True), errors="coerce")
    df["date"] = pd.to_datetime(
        df["date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce"
    )
    df = df.dropna(subset=["date", "quantity", "price"])
    df = df.sort_values(["date", "action"]).reset_index(drop=True)
    return df
