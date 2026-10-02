CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  city TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('correction','accessibility','privacy','other')),
  source_id TEXT,
  message TEXT NOT NULL CHECK(length(message) BETWEEN 10 AND 2000),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  deletion_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS feedback_expiry ON feedback(expires_at);
CREATE INDEX IF NOT EXISTS feedback_city_created ON feedback(city,created_at,id);
CREATE TABLE IF NOT EXISTS budget (
  bucket TEXT PRIMARY KEY,
  n INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS budget_expiry ON budget(expires_at);
