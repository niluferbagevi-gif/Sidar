-- Only runs on fresh postgres data directory.
-- Enable pgvector extension for default Sidar databases.
\connect sidar
CREATE EXTENSION IF NOT EXISTS vector;

\connect sidar_development
CREATE EXTENSION IF NOT EXISTS vector;

\connect sidar_test
CREATE EXTENSION IF NOT EXISTS vector;
