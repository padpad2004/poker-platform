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

        if "table_stacks" not in existing_tables:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS table_stacks (
                        id INTEGER PRIMARY KEY,
                        table_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        seat INTEGER NOT NULL,
                        stack INTEGER NOT NULL,
                        name TEXT,
                        profile_picture_url TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(table_id) REFERENCES poker_tables(id),
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    );
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_table_stacks_table_user ON table_stacks(table_id, user_id);"
                )
            )

        if "poker_tables" in existing_tables:
            columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(poker_tables);"))
            }

            if "table_name" not in columns:
                conn.execute(
                    text("ALTER TABLE poker_tables ADD COLUMN table_name TEXT")
                )
                conn.execute(
                    text(
                        "UPDATE poker_tables SET table_name = COALESCE(table_name, 'Table #' || id)"
                    )
                )

            if "game_type" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE poker_tables ADD COLUMN game_type TEXT DEFAULT 'nlh'"
                    )
                )

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

            if "profile_picture_url" not in user_columns:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN profile_picture_url TEXT")
                )

            if "university" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN university TEXT"))

        if "hand_histories" not in existing_tables:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS hand_histories (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        table_name TEXT NOT NULL,
                        result TEXT NOT NULL,
                        net_change INTEGER DEFAULT 0,
                        summary TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    );
                    """
                )
            )

        if "clubs" in existing_tables:
            club_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(clubs);"))
            }

            if "crest_url" not in club_columns:
                conn.execute(text("ALTER TABLE clubs ADD COLUMN crest_url TEXT"))

            # Ensure existing clubs have a default crest so the UI can render it
            conn.execute(
                text(
                    """
                    UPDATE clubs
                    SET crest_url = '/static/crests/crest-crown.svg'
                    WHERE crest_url IS NULL OR crest_url = ''
                    """
                )
            )

        if "club_members" in existing_tables:
            member_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(club_members);"))
            }

            if "status" not in member_columns:
                conn.execute(text("ALTER TABLE club_members ADD COLUMN status TEXT"))
                conn.execute(
                    text(
                        """
                        UPDATE club_members
                        SET status = 'approved'
                        WHERE status IS NULL OR status = ''
                        """
                    )
                )


_schema_initialized = False


def ensure_schema_once():
    """Apply schema migrations a single time per process."""

    global _schema_initialized
    if _schema_initialized:
        return

    ensure_schema()
    _schema_initialized = True


# Run migrations on import so that auxiliary scripts and background tasks
# always have the latest columns available (e.g., profile pictures,
# universities) even if they don't explicitly call ensure_schema().
ensure_schema_once()
