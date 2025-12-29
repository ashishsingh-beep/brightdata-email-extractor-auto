-- Local Database Schema for Bright Data Email Extractor

-- Table: snapshot_table
-- Stores metadata about Bright Data snapshots and the queries used to generate them.
CREATE TABLE IF NOT EXISTS snapshot_table (
    snapshot_id TEXT PRIMARY KEY,
    query TEXT[],
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: response_table
-- Stores the raw JSON response from Bright Data for each snapshot.
CREATE TABLE IF NOT EXISTS response_table (
    id SERIAL PRIMARY KEY,
    snapshot_id TEXT UNIQUE NOT NULL,
    response JSONB,
    is_email_extracted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (snapshot_id) REFERENCES snapshot_table(snapshot_id)
);

-- Table: email_table
-- Stores unique email addresses extracted from the responses.
CREATE TABLE IF NOT EXISTS email_table (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes (Optional but recommended for performance)
CREATE INDEX IF NOT EXISTS idx_snapshot_processed ON snapshot_table(processed);
CREATE INDEX IF NOT EXISTS idx_response_extracted ON response_table(is_email_extracted);
