import aiohttp
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

async def get_crypto_price_in_usd(currency: str) -> Decimal:
    """
    Get the price of a given cryptocurrency in USD (from Binance USDT pairs).
    If currency is a stablecoin like USDT or USDC, returns 1.0.
    """
    stablecoins = ['USDT-ERC20', 'USDC-ERC20', 'USDT-SPL', 'USDC-SPL', 'USDT-TRC20', 'USDC-TRC20']
    if currency in stablecoins:
        return Decimal('1.0')

    symbol_map = {
        'BTC': 'BTCUSDT',
        'LTC': 'LTCUSDT',
        'ETH': 'ETHUSDT',
        'SOL': 'SOLUSDT',
        'TRX': 'TRXUSDT'
    }

    if currency not in symbol_map:
        logger.error(f"Cannot find price for unsupported currency: {currency}")
        return Decimal('0')

    symbol = symbol_map[currency]
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    price_str = data.get('price', '0')
                    return Decimal(price_str)
                else:
                    logger.warning(f"Binance API error for {symbol}: HTTP {response.status}")
    except Exception as e:
        logger.error(f"Error fetching price from Binance for {symbol}: {e}")

    return Decimal('0')
