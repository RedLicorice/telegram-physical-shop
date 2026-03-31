import sys
import os
from pathlib import Path

# Add the project root to sys.path to allow importing from 'bot'
sys.path.append(str(Path(__file__).parent.parent))

import logging
from sqlalchemy import text, inspect
from bot.database.main import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def migrate():
    try:
        db = Database()
        engine = db.engine
        logger.info(f"Connecting to database with engine: {engine}")
        
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info(f"Available tables: {tables}")
        
        target_table = 'orders'
        if target_table not in tables:
            # Check for case-sensitivity
            if target_table.lower() in [t.lower() for t in tables]:
                target_table = [t for t in tables if t.lower() == target_table.lower()][0]
                logger.info(f"Found table with different case: {target_table}")
            else:
                logger.error(f"Table '{target_table}' not found in database!")
                return

        # Missing columns to add
        new_columns = [
            ("crypto_currency", "VARCHAR(20)"),
            ("crypto_amount", "NUMERIC(20, 8)"),
            ("crypto_address", "VARCHAR(150)"),
            ("use_testnet", "BOOLEAN DEFAULT FALSE")
        ]
        
        existing_columns = [c['name'] for c in inspector.get_columns(target_table)]
        logger.info(f"Existing columns in '{target_table}': {existing_columns}")
        
        with engine.connect() as conn:
            for col_name, col_type in new_columns:
                if col_name not in existing_columns:
                    logger.info(f"Adding column '{col_name}' to table '{target_table}'...")
                    conn.execute(text(f"ALTER TABLE {target_table} ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"Column '{col_name}' added successfully.")
                else:
                    logger.info(f"Column '{col_name}' already exists in table '{target_table}'.")
            
            conn.commit()
            logger.info("Migration completed successfully.")
            
    except Exception as e:
        logger.error(f"Migration failed during execution: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    migrate()
