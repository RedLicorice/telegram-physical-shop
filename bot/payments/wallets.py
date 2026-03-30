import os
from pathlib import Path
from typing import List, Tuple, Optional
from bip_utils import (
    Bip39MnemonicGenerator, Bip39SeedGenerator, Bip39WordsNum,
    Bip44, Bip44Coins, Bip44Changes,
    Bip49, Bip49Coins,
    Bip84, Bip84Coins,
    Solana, SolanaCoins
)

class WalletManager:
    """
    Manages BIP-based wallet generation and address derivation for multiple chains.
    """
    
    # Mapping of chain names to bip-utils coin types and classes
    CHAIN_CONFIG = {
        "BTC": {"class": Bip84, "coin": Bip84Coins.BITCOIN},
        "ETH": {"class": Bip44, "coin": Bip44Coins.ETHEREUM},
        "LTC": {"class": Bip84, "coin": Bip84Coins.LITECOIN},
        "SOL": {"class": Solana, "coin": SolanaCoins.SOLANA},
        "TRX": {"class": Bip44, "coin": Bip44Coins.TRON},
    }

    def __init__(self, wallets_dir: str = "config/wallets"):
        self.wallets_dir = Path(wallets_dir)
        self.wallets_dir.mkdir(parents=True, exist_ok=True)

    def get_public_file(self, chain: str) -> Path:
        return self.wallets_dir / f"{chain.lower()}.public.txt"

    def get_private_file(self, chain: str) -> Path:
        return self.wallets_dir / f"{chain.lower()}.private.txt"

    def generate_keypair(self, chain: str) -> Tuple[str, str, str]:
        """
        Generates a new mnemonic and derived public/private keys.
        
        Returns:
            Tuple[str, str, str]: (mnemonic, encoded_public_key, encoded_private_key)
        """
        chain = chain.upper()
        if chain not in self.CHAIN_CONFIG:
            raise ValueError(f"Unsupported chain: {chain}")

        # 1. Generate 12-word mnemonic
        mnemonic = Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12)
        
        # 2. Generate seed
        seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
        
        # 3. Create Bip object
        config = self.CHAIN_CONFIG[chain]
        bip_obj = config["class"].FromSeed(seed_bytes, config["coin"])
        
        # 4. Get Master Public/Private keys (Extended keys if supported)
        if chain == "SOL":
            # Solana doesn't use "Extended" keys in the same way as BTC/ETH in bip-utils
            # We'll use the derived account 0 for simplicity if using standard BIP44
            # Usually users expect the mnemonic for Solana.
            # We'll store the public key and mnemonic.
            # For derivation, we'll need the Bip44 object.
            public_key = bip_obj.PublicKey().ToExtended()
            private_key = bip_obj.PrivateKey().ToExtended()
        else:
            # BTC/ETH/LTC/TRX use Account 0, Change 0 (Internal/External)
            # We derive Account 0 to get the XPUB that can derive addresses.
            account_0 = bip_obj.Purpose().Coin().Account(0)
            public_key = account_0.PublicKey().ToExtended()
            private_key = account_0.PrivateKey().ToExtended()

        # Save to files
        self._save_keys(chain, mnemonic, public_key, private_key)
        
        return str(mnemonic), public_key, private_key

    def import_wallet(self, chain: str, mnemonic: Optional[str] = None, public_key: Optional[str] = None):
        """
        Imports an existing mnemonic or public key (XPUB).
        """
        chain = chain.upper()
        if chain not in self.CHAIN_CONFIG:
            raise ValueError(f"Unsupported chain: {chain}")

        if not mnemonic and not public_key:
            raise ValueError("Either mnemonic or public_key must be provided.")

        config = self.CHAIN_CONFIG[chain]
        
        if mnemonic:
            # Validate mnemonic and derive keys
            seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
            bip_obj = config["class"].FromSeed(seed_bytes, config["coin"])
            
            if chain == "SOL":
                derived_pub = bip_obj.PublicKey().ToExtended()
                derived_priv = bip_obj.PrivateKey().ToExtended()
            else:
                account_0 = bip_obj.Purpose().Coin().Account(0)
                derived_pub = account_0.PublicKey().ToExtended()
                derived_priv = account_0.PrivateKey().ToExtended()
            
            # If public_key was also provided, verify it matches
            if public_key and public_key != derived_pub:
                raise ValueError(f"Provided public key does not match mnemonic! Derived: {derived_pub}")
            
            self._save_keys(chain, mnemonic, derived_pub, derived_priv)
            return derived_pub
        else:
            # Public key only (can only be used for derivation, no private key stored)
            # Validate public key by attempting to load it
            try:
                config["class"].FromExtendedKey(public_key, config["coin"])
            except Exception as e:
                raise ValueError(f"Invalid public key for {chain}: {e}")

            public_path = self.get_public_file(chain)
            with open(public_path, "w") as f:
                f.write(public_key)
            
            # Remove private key file if it exists to avoid confusion
            private_path = self.get_private_file(chain)
            if private_path.exists():
                private_path.unlink()
                
            return public_key

    def _save_keys(self, chain: str, mnemonic: str, public_key: str, private_key: str):
        """Saves keys to the wallets directory."""
        chain = chain.lower()
        public_path = self.get_public_file(chain)
        private_path = self.get_private_file(chain)

        # Public key only
        with open(public_path, "w") as f:
            f.write(public_key)

        # Private key + Mnemonic (Secure this file!)
        with open(private_path, "w") as f:
            f.write(f"Mnemonic: {mnemonic}\n")
            f.write(f"Private Key: {private_key}\n")

    def derive_addresses(self, chain: str, start_index: int, count: int) -> List[str]:
        """
        Derives addresses from an extended public key found in config/wallets/.
        """
        chain = chain.upper()
        public_path = self.get_public_file(chain)
        
        if not public_path.exists():
            raise FileNotFoundError(f"Public key for {chain} not found at {public_path}. Please generate or add it.")

        with open(public_path, "r") as f:
            extended_pub_key = f.read().strip()

        config = self.CHAIN_CONFIG[chain]
        
        # Reconstruct Bip object from Extended Public Key
        # Note: If it's an XPUB, it can only derive child public keys (addresses)
        if chain == "SOL":
            # Solana handling
            bip_obj = config["class"].FromExtendedKey(extended_pub_key, config["coin"])
        else:
            # BTC/ETH/LTC/TRX
            # The saved key is the Account 0 extended public key
            bip_obj = config["class"].FromExtendedKey(extended_pub_key, config["coin"])

        addresses = []
        for i in range(start_index, start_index + count):
            if chain == "SOL":
                # Solana: Account / Change / Index
                # Bip-utils Solana implementation might vary, check Bip44 for Solana
                # Usually m/44'/501'/0'/0'
                child = bip_obj.Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
            elif chain in ["ETH", "TRX"]:
                # BIP44 path: m/44'/coin'/account'/change/index
                child = bip_obj.Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
            else:
                # BIP84 (SegWit) path: m/84'/coin'/account'/change/index
                child = bip_obj.Change(Bip44Changes.CHAIN_EXT).AddressIndex(i)
            
            addresses.append(child.PublicKey().ToAddress())
            
        return addresses

    def get_public_key(self, chain: str) -> Optional[str]:
        """Reads the public key from the file."""
        public_path = self.get_public_file(chain)
        if public_path.exists():
            with open(public_path, "r") as f:
                return f.read().strip()
        return None
