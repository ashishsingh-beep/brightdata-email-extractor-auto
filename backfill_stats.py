import os
import json
import re
import logging
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def extract_emails_from_text(text_content: str) -> list:
    pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    return list(set(re.findall(pattern, text_content)))

def extract_emails_from_json(json_data) -> list:
    s = json.dumps(json_data)
    return extract_emails_from_text(s)

def backfill_stats():
    load_dotenv()
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL not found.")
        return

    engine = create_engine(database_url)
    
    # We need to simulate the "New Only" logic.
    # To do this accurately, we must process snapshots in the order they were originally processed.
    # We'll assume ID order in response_table is a good proxy for processing order.
    
    logger.info("Fetching all responses ordered by ID...")
    
    try:
        with engine.connect() as conn:
            # Fetch all responses
            count_result = conn.execute(text("SELECT COUNT(*) FROM response_table"))
            total_rows = count_result.scalar()
            logger.info(f"Total snapshots to process: {total_rows}")
            
            # We will maintain a set of seen emails to track uniqueness
            seen_emails = set()
            
            batch_size = 1000
            offset = 0
            processed_count = 0
            
            while True:
                logger.info(f"Fetching batch with offset {offset}...")
                # Fetch created_at as well to preserve history
                result = conn.execute(
                    text("SELECT snapshot_id, response, created_at FROM response_table ORDER BY id ASC LIMIT :limit OFFSET :offset"),
                    {"limit": batch_size, "offset": offset}
                )
                rows = result.mappings().all()
                
                if not rows:
                    break
                
                stats_batch = []
                
                for row in rows:
                    snapshot_id = row['snapshot_id']
                    response_data = row['response']
                    created_at = row['created_at']
                    
                    emails = extract_emails_from_json(response_data) if response_data else []
                    
                    new_emails_for_snapshot = []
                    for email in emails:
                        if email not in seen_emails:
                            new_emails_for_snapshot.append(email)
                            seen_emails.add(email)
                    
                    stats_batch.append({
                        "snapshot_id": snapshot_id,
                        "email_count": len(new_emails_for_snapshot),
                        "emails": new_emails_for_snapshot,
                        "created_at": created_at
                    })
                    
                    processed_count += 1
                
                if stats_batch:
                    conn.execute(
                        text("""
                            INSERT INTO snapshot_stats (snapshot_id, email_count, emails, created_at) 
                            VALUES (:snapshot_id, :email_count, :emails, :created_at)
                            ON CONFLICT (snapshot_id) DO UPDATE 
                            SET email_count = EXCLUDED.email_count, 
                                emails = EXCLUDED.emails,
                                created_at = EXCLUDED.created_at
                        """),
                        stats_batch
                    )
                    conn.commit()
                    logger.info(f"Processed and saved {processed_count}/{total_rows} snapshots...")
                
                offset += batch_size
                
        logger.info("Backfill complete.")
        
    except Exception as e:
        logger.error(f"Error during backfill: {e}")

if __name__ == "__main__":
    backfill_stats()
