from jesse.config import config
from strategies.micro_ml import MicroML

config['app']['trading_exchanges'] = ['BingX']
config['app']['extra_candles'] = []

routes = [
    ('BingX', 'DOGE-USDT', '5m', MicroML),
    ('BingX', 'LTC-USDT', '5m', MicroML),
    ('BingX', 'SHIB-USDT', '5m', MicroML),
    ('BingX', 'SUI-USDT', '5m', MicroML),
]
