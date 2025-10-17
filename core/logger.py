import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%d.%m.%y %H:%M",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger()

# ---------- удобные обёртки ----------
def log_buy(qty: float, price: float, symbol: str):
    log.info(f"📈  BUY  {qty:>8.4f}  {symbol}  @ {price:>12.2f}")

def log_sell(qty: float, price: float, symbol: str):
    log.info(f"📉  SELL {qty:>8.4f}  {symbol}  @ {price:>12.2f}")

def log_profit(pnl_usd: float, pnl_pct: float, symbol: str):
    sign = "+" if pnl_usd >= 0 else "-"
    log.info(f"💰  {sign}{abs(pnl_usd):>8.2f} $ ({sign}{abs(pnl_pct):>5.2f} %)  {symbol}")
