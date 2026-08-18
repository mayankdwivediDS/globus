-- RBAC data access control schema — Email + Drive access management
-- Load once into your `globus` DB:
--   mysql -u globus -p globus < schema/rbac_schema.sql

SET NAMES utf8mb4;
SET sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO';

-- ─────────────────────────────────────────────────────────────────────
-- Per-member RBAC access levels (Email + Drive)
-- ─────────────────────────────────────────────────────────────────────
-- One row per member per org. Tracks what data they can access.
-- Levels: "own" (self only) | "team" (self + team) | "all" (everyone)

CREATE TABLE IF NOT EXISTS member_rbac_access (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  org_id            BIGINT NOT NULL,
  member_email      VARCHAR(320) NOT NULL,
  email_access      VARCHAR(20) NOT NULL DEFAULT 'own',    -- own|team|all
  drive_access      VARCHAR(20) NOT NULL DEFAULT 'own',    -- own|team|all
  updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_org_member (org_id, member_email),
  KEY idx_org (org_id),
  CONSTRAINT fk_rbac_org FOREIGN KEY (org_id) REFERENCES organizations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
-- Audit log — Data access events
-- ─────────────────────────────────────────────────────────────────────
-- Every data access (search, read, etc.) is logged for compliance + audit.
-- Truncate periodically if it grows unbounded; no FK so deletes are manual.

CREATE TABLE IF NOT EXISTS rbac_access_log (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  actor_email       VARCHAR(320) NOT NULL,       -- who performed the action
  action            VARCHAR(80) NOT NULL,        -- search_email_semantic, etc.
  target_email      VARCHAR(320),                -- whose data was accessed
  resource_type     VARCHAR(20) NOT NULL,       -- email|drive
  result            VARCHAR(20) NOT NULL,       -- ok|denied|error
  timestamp         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_actor (actor_email, timestamp),
  KEY ix_target (target_email, timestamp),
  KEY ix_resource (resource_type, timestamp),
  KEY ix_result (result, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
