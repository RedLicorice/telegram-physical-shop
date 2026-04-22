"""
Testnet wallet management: create per-user wallets, check balances,
send payments, and provide faucet links.

Only active when USE_TESTNET=1 AND BotSettings('testnet_user_wallets') == 'true'.
"""
import logging
from decimal import Decimal
from typing import Optional, Tuple

from cryptography.fernet import Fernet
from bot.config.env import EnvKeys
from bot.database.main import Database
from bot.database.models.main import UserTestnetWallet, BotSettings

logger = logging.getLogger(__name__)

# ── Encryption helpers (key derived from bot token) ──────────────

_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        import hashlib, base64
        # Derive a stable 32-byte key from the bot token
        raw = hashlib.sha256((EnvKeys.TOKEN or "fallback").encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(raw))
    return _fernet


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


# ── Feature gate ─────────────────────────────────────────────────

def is_testnet_wallets_enabled() -> bool:
    """Check if testnet user wallets are enabled."""
    if not EnvKeys.USE_TESTNET:
        return False
    from bot.database.methods.read import get_bot_setting
    return get_bot_setting("testnet_user_wallets", default="false").lower() == "true"


# ── Faucet links ─────────────────────────────────────────────────

TESTNET_FAUCETS = {
    "BTC": "https://coinfaucet.eu/en/btc-testnet/",
    "LTC": "https://testnet-faucet.com/ltc-testnet/",
    "ETH": "https://www.alchemy.com/faucets/ethereum-sepolia",
    "SOL": "https://faucet.solana.com/",
    "TRX": "https://nileex.io/join/getJoinPage",
}


def get_faucet_url(chain: str) -> str:
    return TESTNET_FAUCETS.get(chain.upper(), "")


# ── Wallet creation ──────────────────────────────────────────────

# Map currency codes (like USDT-ERC20) to the chain whose wallet we need
CURRENCY_TO_CHAIN = {
    "BTC": "BTC", "LTC": "LTC",
    "ETH": "ETH", "USDT-ERC20": "ETH", "USDC-ERC20": "ETH",
    "SOL": "SOL", "USDT-SPL": "SOL", "USDC-SPL": "SOL",
    "TRX": "TRX", "USDT-TRC20": "TRX", "USDC-TRC20": "TRX",
}


def get_or_create_wallet(user_id: int, chain: str) -> Tuple[str, str]:
    """
    Get existing wallet or create a new one for (user, chain).

    Returns:
        (address, private_key_hex)
    """
    chain = chain.upper()
    with Database().session() as s:
        existing = s.query(UserTestnetWallet).filter_by(
            user_id=user_id, chain=chain
        ).first()
        if existing:
            return existing.address, _decrypt(existing.private_key_enc)

    # Create new wallet using bip_utils (lazy-loaded)
    address, priv_hex = _derive_testnet_wallet(chain)

    with Database().session() as s:
        # Double-check (race condition guard)
        existing = s.query(UserTestnetWallet).filter_by(
            user_id=user_id, chain=chain
        ).first()
        if existing:
            return existing.address, _decrypt(existing.private_key_enc)

        s.add(UserTestnetWallet(
            user_id=user_id,
            chain=chain,
            address=address,
            private_key_enc=_encrypt(priv_hex),
        ))

    logger.info(f"Created testnet {chain} wallet for user {user_id}: {address}")
    return address, priv_hex


def _derive_testnet_wallet(chain: str) -> Tuple[str, str]:
    """Derive a fresh random wallet for the given chain. Returns (address, private_key_hex)."""
    from bot.payments.wallets import _load_bip_utils
    bip = _load_bip_utils()

    mnemonic = bip['Bip39MnemonicGenerator']().FromWordsNumber(bip['Bip39WordsNum'].WORDS_NUM_12)
    seed = bip['Bip39SeedGenerator'](mnemonic).Generate()

    # Pick the right BIP class/coin
    chain_map = {
        "BTC": (bip['Bip84'], bip['Bip84Coins'].BITCOIN),
        "LTC": (bip['Bip84'], bip['Bip84Coins'].LITECOIN),
        "ETH": (bip['Bip44'], bip['Bip44Coins'].ETHEREUM),
        "SOL": (bip['Bip44'], bip['Bip44Coins'].SOLANA),
        "TRX": (bip['Bip44'], bip['Bip44Coins'].TRON),
    }

    if chain not in chain_map:
        raise ValueError(f"Unsupported chain for testnet wallet: {chain}")

    cls, coin = chain_map[chain]
    bip_obj = cls.FromSeed(seed, coin)
    child = bip_obj.Purpose().Coin().Account(0).Change(
        bip['Bip44Changes'].CHAIN_EXT
    ).AddressIndex(0)

    address = child.PublicKey().ToAddress()
    priv_key = child.PrivateKey().Raw().ToHex()

    return address, priv_key


# ── Balance checking ─────────────────────────────────────────────

async def get_wallet_balance(chain: str, address: str, currency: str) -> Decimal:
    """Check testnet balance using existing checker infrastructure."""
    try:
        from bot.payments.checkers import PaymentCheckerFactory
        checker = PaymentCheckerFactory.get_checker(currency)
        if not checker:
            return Decimal(0)

        # Use a very small expected amount to just get the balance check to run
        # We need to call the underlying API directly
        return await _check_balance_raw(chain, address, currency)
    except Exception as e:
        logger.error(f"Balance check error for {chain}/{address}: {e}")
        return Decimal(0)


async def _check_balance_raw(chain: str, address: str, currency: str) -> Decimal:
    """Raw balance check using the same APIs as payment checkers."""
    import aiohttp

    if chain == "ETH":
        import os
        api_key = os.getenv('ETHERSCAN_API_KEY', '')
        url = "https://api-sepolia.etherscan.io/api"
        params = {
            'module': 'account', 'action': 'balance',
            'address': address, 'tag': 'latest', 'apikey': api_key
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get('status') == '1':
                    return Decimal(data['result']) / Decimal('1000000000000000000')
    elif chain == "SOL":
        url = "https://api.devnet.solana.com"
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance", "params": [address]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                value = data.get('result', {}).get('value', 0)
                return Decimal(value) / Decimal('1000000000')  # lamports
    elif chain == "BTC":
        url = f"https://blockstream.info/testnet/api/address/{address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                funded = data.get('chain_stats', {}).get('funded_txo_sum', 0)
                spent = data.get('chain_stats', {}).get('spent_txo_sum', 0)
                mempool_funded = data.get('mempool_stats', {}).get('funded_txo_sum', 0)
                return Decimal(funded - spent + mempool_funded) / Decimal('100000000')
    elif chain == "LTC":
        url = f"https://api.blockcypher.com/v1/ltc/test3/addrs/{address}/balance"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                balance = data.get('balance', 0) + data.get('unconfirmed_balance', 0)
                return Decimal(balance) / Decimal('100000000')
    elif chain == "TRX":
        url = f"https://nile.trongrid.io/v1/accounts/{address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                balance = 0
                for item in data.get('data', []):
                    balance = item.get('balance', 0)
                return Decimal(balance) / Decimal('1000000')

    return Decimal(0)


# ── Transaction sending ──────────────────────────────────────────

async def send_payment(
    chain: str,
    currency: str,
    from_private_key: str,
    to_address: str,
    amount: Decimal,
) -> Tuple[bool, str]:
    """
    Send crypto from user's testnet wallet to shop address.

    Returns:
        (success, tx_hash_or_error)
    """
    chain = chain.upper()
    try:
        if chain == "ETH":
            return await _send_eth(from_private_key, to_address, amount)
        elif chain == "SOL":
            return await _send_sol(from_private_key, to_address, amount)
        else:
            return False, f"Auto-send not implemented for {chain}. Please send manually."
    except Exception as e:
        logger.error(f"Send payment error ({chain}): {e}")
        return False, str(e)


async def _send_eth(private_key: str, to_address: str, amount: Decimal) -> Tuple[bool, str]:
    """Send ETH on Sepolia testnet using web3.py."""
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider("https://rpc.sepolia.org"))
    if not w3.is_connected():
        # Fallback RPCs
        for rpc in ["https://ethereum-sepolia-rpc.publicnode.com", "https://1rpc.io/sepolia"]:
            w3 = Web3(Web3.HTTPProvider(rpc))
            if w3.is_connected():
                break
        else:
            return False, "Cannot connect to Sepolia RPC"

    account = w3.eth.account.from_key(private_key)
    nonce = w3.eth.get_transaction_count(account.address)
    value_wei = int(amount * Decimal('1000000000000000000'))

    tx = {
        'nonce': nonce,
        'to': Web3.to_checksum_address(to_address),
        'value': value_wei,
        'gas': 21000,
        'gasPrice': w3.eth.gas_price,
        'chainId': 11155111,  # Sepolia
    }

    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return True, w3.to_hex(tx_hash)


async def _send_sol(private_key: str, to_address: str, amount: Decimal) -> Tuple[bool, str]:
    """Send SOL on devnet using solana-py/solders."""
    try:
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.system_program import transfer, TransferParams
        from solders.transaction import Transaction
        from solders.message import Message
        from solders.hash import Hash
        import aiohttp
    except ImportError:
        return False, "solders/solana-py not installed. Run: pip install solders"

    kp = Keypair.from_seed(bytes.fromhex(private_key)[:32])
    to_pubkey = Pubkey.from_string(to_address)
    lamports = int(amount * Decimal('1000000000'))

    url = "https://api.devnet.solana.com"

    # Get recent blockhash
    async with aiohttp.ClientSession() as session:
        resp = await session.post(url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getLatestBlockhash", "params": [{"commitment": "finalized"}]
        })
        data = await resp.json()
        blockhash = Hash.from_string(data['result']['value']['blockhash'])

    ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=to_pubkey, lamports=lamports))
    msg = Message.new_with_blockhash([ix], kp.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([kp], blockhash)

    raw = bytes(tx)

    import base64 as b64
    async with aiohttp.ClientSession() as session:
        resp = await session.post(url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [b64.b64encode(raw).decode(), {"encoding": "base64"}]
        })
        data = await resp.json()
        if 'error' in data:
            return False, data['error'].get('message', str(data['error']))
        return True, data['result']
