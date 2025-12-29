"""
Email Scraper Script - Brightdata API Integration with PostgreSQL Storage
This script processes search queries, sends them to Brightdata API in batches,
and stores the snapshot IDs in PostgreSQL.
"""

import requests
import json
import time
import os
import csv
from typing import List, Dict, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
import logging

# Load environment variables from project-local .env reliably

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
BRIGHTDATA_URL = os.getenv('BRIGHTDATA_URL', "")
BRIGHTDATA_API_KEY = os.getenv('BRIGHTDATA_API_KEY', "")

# Database Configuration
DATABASE_URL = os.getenv('DATABASE_URL', "postgresql://postgres:password@localhost:5432/brightdata_db")


class BrightdataClient:
    """Client for interacting with Brightdata API"""
    
    def __init__(self, api_key: str, url: str):
        self.api_key = api_key
        self.url = url
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def get_snapshot_data(self, snapshot_id: str) -> tuple[Optional[Dict], bool, bool, str]:
        """
        Retrieve data for a specific snapshot ID
        
        Args:
            snapshot_id: The snapshot ID to retrieve
            
        Returns:
            Tuple of (JSON response data or None if failed, is_still_running boolean, is_valid boolean, error_reason string)
        """
        import json
        
        try:
            # Extract base URL from trigger URL and construct snapshot URL
            base_url = self.url.split('/trigger')[0] if '/trigger' in self.url else 'https://api.brightdata.com/datasets/v3'
            url = f"{base_url}/snapshot/{snapshot_id}?format=json"
            
            response = requests.get(
                url,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()

            # Validate response
            # New rule: Only treat status="running" as invalid. Do not invalidate
            # responses based on presence of errors or small payload size.
            is_valid = True
            error_reason = ""

            data_str = json.dumps(data)
            if '"status":"running"' in data_str or '"status": "running"' in data_str:
                is_valid = False
                error_reason = "Status is running"
                logger.warning(f"Snapshot {snapshot_id} has status 'running' - invalid response")

            # For backward compatibility: is_running = True if status is running
            is_running = not is_valid and "running" in error_reason

            if is_valid:
                logger.info(f"Successfully retrieved valid data for snapshot: {snapshot_id}")

            return data, is_running, is_valid, error_reason
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error retrieving snapshot {snapshot_id}: {e}")
            return None, False, False, f"Request error: {str(e)}"
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding response for snapshot {snapshot_id}: {e}")
            return None, False, False, f"JSON decode error: {str(e)}"
    
    def create_payload(self, keywords: List[str]) -> str:
        """
        Create payload for Brightdata API request
        
        Args:
            keywords: List of search keywords/queries
            
        Returns:
            JSON string payload
        """
        input_data = []
        for keyword in keywords:
            input_data.append({
                "url": "https://www.google.com/",
                "keyword": keyword,
                "language": "",
                "uule": "",
                "brd_mobile": ""
            })
        
        payload_dict = {"input": input_data}
        payload = json.dumps(payload_dict)
        return payload
    
    def send_request(self, keywords: List[str]) -> Optional[Dict]:
        """
        Send request to Brightdata API
        
        Args:
            keywords: List of search keywords to process
            
        Returns:
            Response JSON containing snapshot_id or None if failed
        """
        try:
            payload = self.create_payload(keywords)
            response = requests.post(
                self.url,
                headers=self.headers,
                data=payload,
                timeout=30
            )
            response.raise_for_status()

            result = response.json()
            logger.info(f"Successfully received snapshot: {result.get('snapshot_id')}")
            return result

        except requests.exceptions.HTTPError as e:
            # Log HTTP error details including response text when available
            status = getattr(e.response, 'status_code', None)
            text = getattr(e.response, 'text', '')
            logger.error(f"HTTP error sending request to Brightdata: {status} {e}. Response: {text[:2000]}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error sending request to Brightdata: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding response: {e}")
            return None


class DatabaseClient:
    """Client for interacting with Local PostgreSQL Database"""
    
    def __init__(self, connection_string: str):
        self.engine = create_engine(connection_string)
    
    def save_snapshot(self, snapshot_id: str, queries: List[str] = None) -> bool:
        """
        Save snapshot ID with associated queries to Database
        
        Args:
            snapshot_id: The snapshot ID from Brightdata
            queries: List of queries associated with this snapshot
            
        Returns:
            True if successful, False otherwise
        """
        try:
            query_list = queries if queries else []
            with self.engine.connect() as conn:
                conn.execute(
                    text("INSERT INTO snapshot_table (snapshot_id, query, processed) VALUES (:snapshot_id, :query, :processed)"),
                    {"snapshot_id": snapshot_id, "query": query_list, "processed": False}
                )
                conn.commit()
            logger.info(f"Snapshot {snapshot_id} saved to Database with {len(query_list)} queries")
            return True
            
        except SQLAlchemyError as e:
            logger.error(f"Error saving snapshot to Database: {e}")
            return False
    
    def get_all_existing_queries(self) -> List[str]:
        """
        Get all unique queries from snapshot_table (flattened and lowercase)
        
        Returns:
            List of lowercase queries for case-insensitive comparison
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT query FROM snapshot_table"))
                rows = result.fetchall()
            
            all_queries = []
            for row in rows:
                queries = row[0] # query column is index 0
                if queries:
                    all_queries.extend([q.lower().strip() for q in queries if q])
            
            unique_queries = list(set(all_queries))
            logger.info(f"Found {len(unique_queries)} unique queries in database")
            return unique_queries
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching existing queries: {e}")
            return []
    
    def get_unprocessed_snapshots(self) -> List[Dict]:
        """
        Get all snapshot IDs with their queries where processed = false
        
        Returns:
            List of dictionaries with snapshot_id and query arrays
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT snapshot_id, query FROM snapshot_table WHERE processed = FALSE"))
                rows = result.mappings().all()
            
            snapshots = [dict(row) for row in rows]
            logger.info(f"Found {len(snapshots)} unprocessed snapshots")
            return snapshots
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching unprocessed snapshots: {e}")
            return []
    
    def mark_as_processed(self, snapshot_id: str) -> bool:
        """
        Mark a snapshot as processed in Database
        
        Args:
            snapshot_id: The snapshot ID to mark as processed
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text("UPDATE snapshot_table SET processed = TRUE WHERE snapshot_id = :snapshot_id"),
                    {"snapshot_id": snapshot_id}
                )
                conn.commit()
            logger.info(f"Marked snapshot {snapshot_id} as processed")
            return True
            
        except SQLAlchemyError as e:
            logger.error(f"Error marking snapshot as processed: {e}")
            return False
    
    def save_email(self, email: str) -> tuple[bool, str]:
        """
        Save a single email to Database email_table
        
        Args:
            email: Email address to save
            
        Returns:
            Tuple of (success: bool, error_type: str)
            error_type can be: '' (success), 'duplicate', 'error'
        """
        try:
            with self.engine.connect() as conn:
                # Use ON CONFLICT DO NOTHING to handle duplicates gracefully
                result = conn.execute(
                    text("INSERT INTO email_table (email) VALUES (:email) ON CONFLICT (email) DO NOTHING"),
                    {"email": email}
                )
                conn.commit()
                
                if result.rowcount == 0:
                    logger.warning(f"Duplicate email {email}")
                    return False, 'duplicate'
                
            logger.info(f"Saved email {email} to Database")
            return True, ''
            
        except SQLAlchemyError as e:
            logger.error(f"Error saving email to Database: {e}")
            return False, 'error'
    
    def save_response(self, snapshot_id: str, response_data: dict) -> tuple[bool, str]:
        """
        Save snapshot response to Database response_table
        
        Args:
            snapshot_id: The snapshot ID
            response_data: The JSON response data to save
            
        Returns:
            Tuple of (success: bool, error_type: str)
            error_type can be: '' (success), 'duplicate', 'error'
        """
        try:
            import json
            with self.engine.connect() as conn:
                try:
                    conn.execute(
                        text("INSERT INTO response_table (snapshot_id, response, is_email_extracted) VALUES (:snapshot_id, :response, :is_email_extracted)"),
                        {"snapshot_id": snapshot_id, "response": json.dumps(response_data), "is_email_extracted": False}
                    )
                    conn.commit()
                    logger.info(f"Saved response for snapshot {snapshot_id} to Database")
                    return True, ''
                except SQLAlchemyError as e:
                    if 'unique constraint' in str(e).lower():
                        logger.warning(f"Duplicate snapshot {snapshot_id}")
                        return False, 'duplicate'
                    raise e
            
        except SQLAlchemyError as e:
            logger.error(f"Error saving response to Database: {e}")
            return False, 'error'
    
    def get_unextracted_responses(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        """
        Get responses from response_table where emails haven't been extracted yet
        
        Args:
            limit: Maximum number of rows to fetch (default 20)
            offset: Number of rows to skip (default 0)
            
        Returns:
            List of dictionaries with snapshot_id and response data
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT snapshot_id, response FROM response_table WHERE is_email_extracted = FALSE LIMIT :limit OFFSET :offset"),
                    {"limit": limit, "offset": offset}
                )
                rows = result.mappings().all()
            
            data = []
            for row in rows:
                data.append({
                    "snapshot_id": row["snapshot_id"],
                    "response": row["response"]
                })
                
            logger.info(f"Found {len(data)} unextracted responses (limit: {limit}, offset: {offset})")
            return data
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching unextracted responses: {e}")
            return []
    
    def count_unextracted_responses(self) -> int:
        """
        Get count of unextracted responses without fetching data
        
        Returns:
            Count of rows where is_email_extracted = false
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM response_table WHERE is_email_extracted = FALSE"))
                count = result.scalar()
            logger.info(f"Total unextracted responses: {count}")
            return count
            
        except SQLAlchemyError as e:
            logger.error(f"Error counting unextracted responses: {e}")
            return 0
    
    def mark_email_extracted(self, snapshot_id: str) -> bool:
        """
        Mark a response row as email extracted
        
        Args:
            snapshot_id: The snapshot_id (primary key) in response_table
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text("UPDATE response_table SET is_email_extracted = TRUE WHERE snapshot_id = :snapshot_id"),
                    {"snapshot_id": snapshot_id}
                )
                conn.commit()
            logger.info(f"Marked snapshot {snapshot_id} as email extracted")
            return True
            
        except SQLAlchemyError as e:
            logger.error(f"Error marking snapshot as extracted: {e}")
            return False
    
    def get_emails_by_date(self, start_date: str | None = None, end_date: str | None = None) -> List[Dict]:
        """
        Get all emails from email_table with optional date filtering
        
        Args:
            start_date: Start date in YYYY-MM-DD format (optional)
            end_date: End date in YYYY-MM-DD format (optional)
            
        Returns:
            List of dictionaries with email data
        """
        try:
            query_str = "SELECT * FROM email_table"
            params = {}
            conditions = []
            
            if start_date:
                conditions.append("created_at >= :start_date")
                params["start_date"] = start_date
            if end_date:
                from datetime import datetime, timedelta
                end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                conditions.append("created_at < :end_date")
                params["end_date"] = end_datetime.strftime('%Y-%m-%d')
            
            if conditions:
                query_str += " WHERE " + " AND ".join(conditions)
            
            query_str += " ORDER BY created_at DESC"
            
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str), params)
                rows = result.mappings().all()
            
            data = []
            for row in rows:
                row_dict = dict(row)
                if 'created_at' in row_dict and row_dict['created_at']:
                    row_dict['created_at'] = str(row_dict['created_at'])
                data.append(row_dict)
                
            logger.info(f"Found {len(data)} emails")
            return data
            
        except SQLAlchemyError as e:
            logger.error(f"Error fetching emails: {e}")
            return []


class EmailScraperEngine:
    """Main engine for orchestrating the scraping process"""
    
    def __init__(self, brightdata_client: BrightdataClient, database_client: DatabaseClient):
        self.brightdata = brightdata_client
        self.database = database_client
    
    def process_queries(self, queries: List[str], batch_size: int = 2) -> Dict[str, any]:
        """
        Process search queries in batches and save snapshots to Database
        
        Args:
            queries: List of search queries to process
            batch_size: Number of queries per batch (default: 2)
            
        Returns:
            Dictionary with statistics about processed queries
        """
        total_queries = len(queries)
        successful_snapshots = 0
        failed_batches = 0
        batch_count = 0
        submitted_ids = []
        snapshot_query_map = {}  # Maps snapshot_id to queries
        
        logger.info(f"Starting to process {total_queries} queries with batch size {batch_size}")
        
        # Process queries in batches
        for i in range(0, total_queries, batch_size):
            batch_count += 1
            batch = queries[i:i + batch_size]
            current_batch_size = len(batch)
            
            logger.info(f"Processing batch {batch_count} ({current_batch_size} queries): {batch}")
            
            # Send request to Brightdata
            response = self.brightdata.send_request(batch)
            
            if response and 'snapshot_id' in response:
                snapshot_id = response['snapshot_id']
                
                # Save to Database with query array
                if self.database.save_snapshot(snapshot_id, batch):
                    successful_snapshots += 1
                    submitted_ids.append(snapshot_id)
                    snapshot_query_map[snapshot_id] = batch
                else:
                    failed_batches += 1
            else:
                logger.warning(f"Batch {batch_count} failed: No snapshot_id in response")
                failed_batches += 1
            
            # Add delay between requests to avoid rate limiting
            if i + current_batch_size < total_queries:
                time.sleep(2)
        
        statistics = {
            'total_queries': total_queries,
            'successful_snapshots': successful_snapshots,
            'failed_batches': failed_batches,
            'total_batches': batch_count,
            'submitted_ids': submitted_ids,
            'snapshot_query_map': snapshot_query_map
        }
        
        return statistics


def main():
    """Main entry point"""
    
    # Example queries - User should provide these
    queries = [
        "pizza restaurants near me",
        "coffee shops downtown",
        "best sushi in the city",
        "italian restaurants",
        "breakfast cafes",
        # Add more queries as needed
    ]
    
    try:
        # Initialize clients
        brightdata_client = BrightdataClient(BRIGHTDATA_API_KEY, BRIGHTDATA_URL)
        database_client = DatabaseClient(DATABASE_URL)
        
        # Create engine and process queries
        engine = EmailScraperEngine(brightdata_client, database_client)
        stats = engine.process_queries(queries)
        
        # Log final statistics
        logger.info("=" * 50)
        logger.info("PROCESSING COMPLETE")
        logger.info(f"Total queries: {stats['total_queries']}")
        logger.info(f"Successful snapshots: {stats['successful_snapshots']}")
        logger.info(f"Failed batches: {stats['failed_batches']}")
        logger.info(f"Total batches processed: {stats['total_batches']}")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"Fatal error in main execution: {e}")
        raise


if __name__ == "__main__":
    main()
