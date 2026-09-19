-- Run once on a Pi whose farm_local DB was created before Challenge 3.
-- Safe to re-run: CREATE TABLE IF NOT EXISTS.
USE farm_local;

CREATE TABLE IF NOT EXISTS challenge_events (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    challenge   VARCHAR(32)  NOT NULL,
    event_type  VARCHAR(64)  NOT NULL,
    message     VARCHAR(500) NULL,
    raw_excerpt VARCHAR(512) NOT NULL,
    received_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_challenge_at (challenge, received_at)
);
