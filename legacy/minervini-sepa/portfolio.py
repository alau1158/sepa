import os
import csv
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class StockHolding:
    symbol: str
    shares: int
    purchase_date: str
    purchase_price: float


class PortfolioManager:
    def __init__(self, csv_path: str = "/home/alau/long_term_investing/holdings.csv"):
        self.csv_path = csv_path
        self.holdings: List[StockHolding] = []
        self.load_holdings()
    
    def load_holdings(self):
        if not os.path.exists(self.csv_path):
            return
        
        with open(self.csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.holdings.append(StockHolding(
                    symbol=row['symbol'].upper(),
                    shares=int(row['shares']),
                    purchase_date=row['purchase_date'],
                    purchase_price=float(row['purchase_price'])
                ))
    
    def save_holdings(self):
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['symbol', 'shares', 'purchase_date', 'purchase_price'])
            writer.writeheader()
            for h in self.holdings:
                writer.writerow({
                    'symbol': h.symbol,
                    'shares': h.shares,
                    'purchase_date': h.purchase_date,
                    'purchase_price': h.purchase_price
                })
    
    def add_holding(self, symbol: str, shares: int, purchase_price: float):
        self.holdings.append(StockHolding(
            symbol=symbol.upper(),
            shares=shares,
            purchase_date=datetime.now().strftime('%Y-%m-%d'),
            purchase_price=purchase_price
        ))
        self.save_holdings()
    
    def remove_holding(self, symbol: str):
        self.holdings = [h for h in self.holdings if h.symbol != symbol.upper()]
        self.save_holdings()
    
    def get_symbols(self) -> List[str]:
        return [h.symbol for h in self.holdings]