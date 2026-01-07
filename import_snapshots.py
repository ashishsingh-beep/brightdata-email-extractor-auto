import pandas as pd
import os
import ast
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_query(query_str):
    try:
        if pd.isna(query_str):
            return []
            
        query_str = str(query_str).strip()
        
        # It seems the CSV has "[,]" for empty or weird lists.
        if query_str == "[,]" or query_str == "[]":
            return []
        
        # If it looks like a list, try to parse it
        if query_str.startswith("[") and query_str.endswith("]"):
            # It might be a string representation of a list
            try:
                # Try ast.literal_eval first (safe eval)
                return ast.literal_eval(query_str)
            except:
                # Fallback: remove brackets and split by comma
                content = query_str[1:-1]
                # Handle quoted strings inside if possible, but simple split for now
                return [x.strip().strip("'").strip('"') for x in content.split(',') if x.strip()]
        return [query_str]
    except Exception as e:
        logger.warning(f"Failed to parse query: {query_str} - {e}")
        return []

def import_data():
    load_dotenv()
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL not found.")
        return

    csv_file = 'process_data.csv'
    if not os.path.exists(csv_file):
        logger.error(f"{csv_file} not found.")
        return

    logger.info(f"Reading {csv_file}...")
    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        logger.error(f"Error reading CSV: {e}")
        return
    
    # Rename columns to match DB
    # CSV: snapshot_id, created, processed, query
    # DB: snapshot_id, created_at, processed, query
    if 'created' in df.columns:
        df = df.rename(columns={'created': 'created_at'})
    
    # Connect to DB
    try:
        engine = create_engine(database_url)
    except Exception as e:
        logger.error(f"Error connecting to DB: {e}")
        return
    
    logger.info(f"Found {len(df)} rows. Starting import...")
    
    success_count = 0
    duplicate_count = 0
    error_count = 0
    
    with engine.connect() as conn:
        for index, row in df.iterrows():
            try:
                snapshot_id = row['snapshot_id']
                created_at = row['created_at'] if 'created_at' in row else None
                processed = str(row['processed']).lower() == 'true'
                query_raw = row['query']
                
                query_list = parse_query(query_raw)
                
                # Insert
                stmt = text("""
                    INSERT INTO snapshot_table (snapshot_id, query, processed, created_at)
                    VALUES (:snapshot_id, :query, :processed, :created_at)
                    ON CONFLICT (snapshot_id) DO NOTHING
                """)
                
                result = conn.execute(stmt, {
                    "snapshot_id": snapshot_id,
                    "query": query_list,
                    "processed": processed,
                    "created_at": created_at
                })
                
                if result.rowcount > 0:
                    success_count += 1
                else:
                    duplicate_count += 1
                    
                if (index + 1) % 1000 == 0:
                    logger.info(f"Processed {index + 1} rows...")
                    conn.commit()
                    
            except Exception as e:
                logger.error(f"Error inserting row {index}: {e}")
                error_count += 1
        
        conn.commit()
        
    logger.info("Import complete.")
    logger.info(f"Success: {success_count}")
    logger.info(f"Duplicates: {duplicate_count}")
    logger.info(f"Errors: {error_count}")

if __name__ == "__main__":
    import_data()
