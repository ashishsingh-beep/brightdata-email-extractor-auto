import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from dotenv import load_dotenv
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_database_if_not_exists(url):
    """
    Create the database if it doesn't exist.
    """
    db_url = make_url(url)
    db_name = db_url.database
    
    # Connect to default 'postgres' database to create the new database
    # We construct a new URL replacing the database name with 'postgres'
    postgres_url = db_url.set(database='postgres')
    
    try:
        # We use psycopg2 directly here for database creation as it requires autocommit
        # and it's simpler than configuring SQLAlchemy engine for this specific task
        conn = psycopg2.connect(
            dbname='postgres',
            user=postgres_url.username,
            password=postgres_url.password,
            host=postgres_url.host,
            port=postgres_url.port
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{db_name}'")
        exists = cursor.fetchone()
        
        if not exists:
            logger.info(f"Database '{db_name}' does not exist. Creating...")
            cursor.execute(f"CREATE DATABASE {db_name}")
            logger.info(f"Database '{db_name}' created successfully.")
        else:
            logger.info(f"Database '{db_name}' already exists.")
            
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error creating database: {e}")
        return False

def setup_database():
    """
    Initialize the database schema for the Email Scraper application.
    Creates necessary tables if they do not exist.
    """
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL not found in environment variables.")
        return

    # Step 1: Create Database if it doesn't exist
    if not create_database_if_not_exists(database_url):
        return

    # Step 2: Create Tables
    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            logger.info("Connected to database.")
            
            # Create snapshot_table
            logger.info("Creating snapshot_table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS snapshot_table (
                    snapshot_id TEXT PRIMARY KEY,
                    query TEXT[],
                    processed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # Create response_table
            logger.info("Creating response_table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS response_table (
                    id SERIAL PRIMARY KEY,
                    snapshot_id TEXT UNIQUE NOT NULL,
                    response JSONB,
                    is_email_extracted BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (snapshot_id) REFERENCES snapshot_table(snapshot_id)
                );
            """))
            
            # Create email_table
            logger.info("Creating email_table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS email_table (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            conn.commit()
            logger.info("Database schema initialized successfully.")
            
    except Exception as e:
        logger.error(f"Error initializing tables: {e}")

if __name__ == "__main__":
    setup_database()
