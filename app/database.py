from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
import os

# Absolute path to THIS app folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")

print("USING DATABASE FILE:", DB_PATH)  # VERY IMPORTANT

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_schema():
    """Apply lightweight migrations for existing SQLite databases."""

    with engine.begin() as conn:
        existing_tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table';")
            )
        }

        if "poker_tables" in existing_tables:
            columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(poker_tables);"))
            }

            if "bomb_pot_every_n_hands" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE poker_tables ADD COLUMN bomb_pot_every_n_hands INTEGER"
                    )
                )

            if "bomb_pot_amount" not in columns:
                conn.execute(
                    text("ALTER TABLE poker_tables ADD COLUMN bomb_pot_amount INTEGER")
                )

        if "users" in existing_tables:
            user_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(users);"))
            }

            if "username" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN username TEXT"))
                conn.execute(
                    text(
                        "UPDATE users SET username = email WHERE username IS NULL OR username = ''"
                    )
                )

            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);")
            )
