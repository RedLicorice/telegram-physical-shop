import os
from pathlib import Path
from bot.config import EnvKeys


def dsn() -> str:
    # Check for explicit DATABASE_URL override (supports sqlite:///path)
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    driver = os.getenv("DB_DRIVER", "postgresql+psycopg2")

    # SQLite mode
    if driver.startswith("sqlite"):
        db_path = os.getenv("SQLITE_PATH", "data/telegram_shop.db")
        # Ensure parent directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"

    if Path("/.dockerenv").exists() or os.getenv("POSTGRES_HOST"):
        # Running in Docker or with separate PostgreSQL env vars
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "")
        database = os.getenv("POSTGRES_DB", "telegram_shop")

        return f"{driver}://{user}:{password}@{host}:{port}/{database}"

    # Local development with hardcoded URL
    return EnvKeys.DATABASE_URL