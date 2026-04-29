from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

# Create a local SQLite database file called smartdesk.db at the root of the project
SQLALCHEMY_DATABASE_URL = "sqlite:///./smartdesk.db"

# engine manages the connection to the database
# check_same_thread=False is important for SQLite in a multithreaded fastAPI/background task environment
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# A sessionmaker builds a new Session object when called.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# FastAPI dependency for session scope
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# All standard SQLAlchemy models will inherit from this Base class
Base = declarative_base()
