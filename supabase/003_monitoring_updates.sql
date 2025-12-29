-- =============================================================================
-- REDDIT GROWTH ENGINE - MONITORING SYSTEM UPDATES
-- Run this after 001_schema.sql and 002_rls_policies.sql
-- Adds fields needed for in-house keyword monitoring
-- =============================================================================

-- -----------------------------------------------------------------------------
-- KEYWORDS TABLE - Add last_scanned_at for tracking scan frequency
-- -----------------------------------------------------------------------------

ALTER TABLE keywords
ADD COLUMN IF NOT EXISTS last_scanned_at TIMESTAMP WITH TIME ZONE;

-- Add index for efficient scanning queries
CREATE INDEX IF NOT EXISTS idx_keywords_last_scanned
ON keywords(last_scanned_at);

-- -----------------------------------------------------------------------------
-- MENTIONS TABLE - Add fields for richer mention tracking
-- -----------------------------------------------------------------------------

-- Array to store which keywords matched this mention
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS matched_keywords TEXT[];

-- Full content storage (the original schema had content_preview)
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS post_content TEXT;

-- Author of the post
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS post_author TEXT;

-- Post type: 'submission' or 'comment'
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS post_type TEXT DEFAULT 'submission';

-- Original post score at time of detection
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS post_score INTEGER DEFAULT 0;

-- Number of comments at time of detection
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS post_comments INTEGER DEFAULT 0;

-- Post title (separate from content)
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS post_title TEXT;

-- Sentiment analysis result
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS sentiment TEXT DEFAULT 'neutral';

-- Organization ID for easier querying
ALTER TABLE mentions
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);

-- Add index for efficient mention queries
CREATE INDEX IF NOT EXISTS idx_mentions_matched_keywords
ON mentions USING GIN(matched_keywords);

CREATE INDEX IF NOT EXISTS idx_mentions_org
ON mentions(organization_id);

CREATE INDEX IF NOT EXISTS idx_mentions_detected
ON mentions(detected_at DESC);

-- -----------------------------------------------------------------------------
-- SUBREDDITS TABLE - Add marketing analysis fields
-- -----------------------------------------------------------------------------

-- Subscriber count
ALTER TABLE subreddits
ADD COLUMN IF NOT EXISTS subscriber_count INTEGER DEFAULT 0;

-- Active users count
ALTER TABLE subreddits
ADD COLUMN IF NOT EXISTS active_users INTEGER DEFAULT 0;

-- Marketing suitability score (0-1)
ALTER TABLE subreddits
ADD COLUMN IF NOT EXISTS marketing_score DECIMAL(3,2) DEFAULT 0.5;

-- Whether self-promotion is restricted
ALTER TABLE subreddits
ADD COLUMN IF NOT EXISTS self_promo_restricted BOOLEAN DEFAULT FALSE;

-- Last analyzed timestamp
ALTER TABLE subreddits
ADD COLUMN IF NOT EXISTS last_analyzed_at TIMESTAMP WITH TIME ZONE;

-- -----------------------------------------------------------------------------
-- Create a scan_history table for tracking monitoring runs
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scan_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,

    -- Scan results
    keywords_scanned INTEGER DEFAULT 0,
    mentions_found INTEGER DEFAULT 0,
    mentions_new INTEGER DEFAULT 0,
    mentions_duplicate INTEGER DEFAULT 0,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,

    -- Status
    status TEXT DEFAULT 'running', -- running, completed, failed
    error_message TEXT,

    -- Metadata
    scan_type TEXT DEFAULT 'scheduled', -- scheduled, manual, onboarding

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for scan_history
CREATE INDEX IF NOT EXISTS idx_scan_history_client
ON scan_history(client_id);

CREATE INDEX IF NOT EXISTS idx_scan_history_org
ON scan_history(organization_id);

CREATE INDEX IF NOT EXISTS idx_scan_history_created
ON scan_history(created_at DESC);

-- -----------------------------------------------------------------------------
-- RLS Policies for scan_history
-- -----------------------------------------------------------------------------

ALTER TABLE scan_history ENABLE ROW LEVEL SECURITY;

-- Users can view scan history for their organization's clients
CREATE POLICY scan_history_select_policy ON scan_history
    FOR SELECT
    USING (
        organization_id IN (
            SELECT organization_id FROM users WHERE id = auth.uid()
        )
    );

-- Service role can do everything
CREATE POLICY scan_history_service_policy ON scan_history
    FOR ALL
    USING (auth.role() = 'service_role');

-- -----------------------------------------------------------------------------
-- Helper function to record scan completion
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION complete_scan(
    scan_uuid UUID,
    keywords_count INTEGER,
    found_count INTEGER,
    new_count INTEGER,
    duplicate_count INTEGER
)
RETURNS VOID AS $$
BEGIN
    UPDATE scan_history
    SET
        keywords_scanned = keywords_count,
        mentions_found = found_count,
        mentions_new = new_count,
        mentions_duplicate = duplicate_count,
        completed_at = NOW(),
        duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER,
        status = 'completed'
    WHERE id = scan_uuid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- END OF MIGRATION
-- =============================================================================
