-- Run against the central DB ONLY if your team's tables are missing.
-- Central is pre-populated with a general design -- inspect it first:
--   SHOW TABLES; DESCRIBE <table>;
-- Do not drop anything a judge put there.
CREATE TABLE IF NOT EXISTS sensor_data (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    sensor_position VARCHAR(255)  NOT NULL,
    sensor_value    DECIMAL(10,2) NOT NULL,
    created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_node     VARCHAR(64)   NULL,
    INDEX idx_created (created_at)
);
