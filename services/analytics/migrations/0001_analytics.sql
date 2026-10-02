-- No IP, article URL, token, user agent, cookie, or visitor profile is stored.
CREATE TABLE country_totals (
  city TEXT NOT NULL CHECK (city IN ('berlin','hamburg','munich','cologne','frankfurt','dusseldorf','stuttgart','leipzig','dortmund','bremen','essen','dresden','hannover','nuremberg')),
  country TEXT NOT NULL CHECK (length(country)=2 AND country GLOB '[A-Z][A-Z]'),
  pv INTEGER NOT NULL CHECK (pv > 0),
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (city, country)
) WITHOUT ROWID;
CREATE TABLE daily_budget (
  day TEXT PRIMARY KEY,
  accepted INTEGER NOT NULL CHECK (accepted BETWEEN 0 AND 5000)
) WITHOUT ROWID;
-- Rotating HMACs for short abuse protection; never a stable visitor identifier.
CREATE TABLE short_limits (
  bucket TEXT PRIMARY KEY,
  used INTEGER NOT NULL CHECK (used BETWEEN 1 AND 10),
  admission TEXT NOT NULL,
  expires_at INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX short_limits_expiry ON short_limits(expires_at);
-- Triggers run in the same write statement, so concurrent country writes cannot
-- bypass the global 5000/day cap. This is a conservative application cap, not a
-- promise about all provider quotas or a guarantee against denial of service.
CREATE TRIGGER total_insert_budget AFTER INSERT ON country_totals BEGIN
  INSERT INTO daily_budget(day, accepted) VALUES(date('now'), 1)
  ON CONFLICT(day) DO UPDATE SET accepted=accepted+1;
END;
CREATE TRIGGER total_update_budget AFTER UPDATE OF pv ON country_totals BEGIN
  INSERT INTO daily_budget(day, accepted) VALUES(date('now'), 1)
  ON CONFLICT(day) DO UPDATE SET accepted=accepted+1;
END;
