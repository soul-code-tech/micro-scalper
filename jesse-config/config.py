from jesse.config import config
import os

config['env'] = os.getenv('JESSE_ENV', 'live')
config['app']['port'] = int(os.getenv('PORT', 10000))

# ---------- BingX ----------
config['exchanges']['BingX'] = {
    'name': 'BingX',
    'api_key': os.getenv('BINGX_API_KEY'),
    'api_secret': os.getenv('BINGX_SECRET_KEY'),
    'sandbox': os.getenv('BINGX_TESTNET', 'false').lower() == 'true',
    'fee': 0.0002,
    'futures_leverage': 10,
    'futures_leverage_mode': 'cross',
}
