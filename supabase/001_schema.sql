-- ============================================================================
-- REDDIT GROWTH ENGINE - SUPABASE SCHEMA
-- Version: 1.0
-- Run this in Supabase SQL Editor
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Organizations (for multi-tenant support)
CREATE TABLE public.organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    settings JSONB DEFAULT '{}'::jsonb,
    subscription_tier TEXT DEFAULT 'starter' CHECK (subscription_tier IN ('starter', 'growth', 'scale', 'agency')),
    subscription_status TEXT DEFAULT 'active' CHECK (subscription_status IN ('active', 'past_due', 'cancelled', 'trial')),
    trial_ends_at TIMESTAMPTZ,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT
);

-- Users (linked to Supabase Auth)
CREATE TABLE public.users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    email TEXT NOT NULL,
    full_name TEXT,
    role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Clients (businesses being marketed)
CREATE TABLE public.clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    website TEXT,

    -- Extracted product info
    product_name TEXT,
    product_description TEXT,
    value_propositions TEXT[],
    target_audience TEXT,
    use_cases TEXT[],
    competitors TEXT[],

    -- Scraped content
    website_content TEXT,
    website_scraped_at TIMESTAMPTZ,

    -- Settings
    tone TEXT DEFAULT 'professional' CHECK (tone IN ('professional', 'casual', 'technical', 'friendly')),
    mention_frequency TEXT DEFAULT 'natural' CHECK (mention_frequency IN ('never', 'rare', 'natural', 'frequent')),
    disclosure_text TEXT DEFAULT 'I work on this product',

    -- Status
    status TEXT DEFAULT 'onboarding' CHECK (status IN ('onboarding', 'active', 'paused', 'churned')),
    onboarding_completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Reddit Accounts
CREATE TABLE public.reddit_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    client_id UUID REFERENCES public.clients(id) ON DELETE SET NULL,

    -- Reddit credentials
    username TEXT NOT NULL,
    password_encrypted TEXT NOT NULL, -- Encrypt with Supabase Vault in production
    reddit_client_id TEXT NOT NULL,
    reddit_client_secret TEXT NOT NULL,
    user_agent TEXT NOT NULL,

    -- Account health
    karma INTEGER DEFAULT 0,
    account_age_days INTEGER DEFAULT 0,
    warmup_stage INTEGER DEFAULT 0 CHECK (warmup_stage >= 0 AND warmup_stage <= 5),
    -- Stage 0: New, no activity
    -- Stage 1: Browsing only (1-3 days)
    -- Stage 2: Upvoting (3-5 days)
    -- Stage 3: Commenting on safe subs (5-10 days)
    -- Stage 4: Posting to safe subs (10-14 days)
    -- Stage 5: Ready for marketing

    -- Rate limiting
    last_action_at TIMESTAMPTZ,
    daily_actions_count INTEGER DEFAULT 0,
    daily_actions_reset_at DATE DEFAULT CURRENT_DATE,

    -- Status
    status TEXT DEFAULT 'warming_up' CHECK (status IN ('warming_up', 'active', 'rate_limited', 'shadowbanned', 'suspended', 'inactive')),
    status_reason TEXT,
    last_verified_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(organization_id, username)
);

-- Keywords
CREATE TABLE public.keywords (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

    keyword TEXT NOT NULL,
    keyword_type TEXT DEFAULT 'product' CHECK (keyword_type IN ('product', 'competitor', 'industry', 'problem', 'solution')),

    -- F5Bot tracking
    f5bot_enabled BOOLEAN DEFAULT FALSE,

    -- Performance
    mention_count INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    last_mention_at TIMESTAMPTZ,

    -- Settings
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(client_id, keyword)
);

-- Subreddits
CREATE TABLE public.subreddits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

    name TEXT NOT NULL, -- Without r/ prefix
    display_name TEXT,
    description TEXT,

    -- Stats
    subscribers INTEGER DEFAULT 0,
    active_users INTEGER DEFAULT 0,

    -- Scoring
    relevance_score DECIMAL(3,2) CHECK (relevance_score >= 0 AND relevance_score <= 1),
    engagement_score DECIMAL(3,2) CHECK (engagement_score >= 0 AND engagement_score <= 1),

    -- Rules
    rules_summary TEXT,
    allows_self_promotion BOOLEAN DEFAULT TRUE,
    minimum_karma INTEGER DEFAULT 0,
    minimum_account_age_days INTEGER DEFAULT 0,

    -- Tracking
    last_posted_at TIMESTAMPTZ,
    posts_count INTEGER DEFAULT 0,
    avg_upvotes DECIMAL(10,2) DEFAULT 0,

    -- Status
    is_approved BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(client_id, name)
);

-- ============================================================================
-- OPERATIONAL TABLES
-- ============================================================================

-- Post Queue
CREATE TABLE public.posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.reddit_accounts(id) ON DELETE SET NULL,
    subreddit_id UUID REFERENCES public.subreddits(id) ON DELETE SET NULL,

    -- Content
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text' CHECK (content_type IN ('text', 'link', 'image')),
    link_url TEXT,

    -- Reddit data (after posting)
    reddit_post_id TEXT,
    reddit_url TEXT,
    reddit_permalink TEXT,

    -- Scheduling
    scheduled_at TIMESTAMPTZ,
    posted_at TIMESTAMPTZ,

    -- Metrics
    upvotes INTEGER DEFAULT 0,
    downvotes INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    upvote_ratio DECIMAL(3,2),

    -- Status
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'scheduled', 'posting', 'posted', 'failed', 'deleted', 'removed')),
    error_message TEXT,

    -- Metadata
    generated_by TEXT DEFAULT 'manual' CHECK (generated_by IN ('manual', 'ai', 'template')),
    template_id UUID,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metrics_updated_at TIMESTAMPTZ
);

-- Create index for queue processing
CREATE INDEX idx_posts_status_scheduled ON public.posts(status, scheduled_at) WHERE status = 'scheduled';
CREATE INDEX idx_posts_client_status ON public.posts(client_id, status);

-- Mentions (from F5Bot monitoring)
CREATE TABLE public.mentions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    keyword_id UUID REFERENCES public.keywords(id) ON DELETE SET NULL,

    -- Reddit data
    reddit_post_id TEXT NOT NULL,
    reddit_url TEXT NOT NULL,
    reddit_permalink TEXT,
    subreddit TEXT NOT NULL,

    -- Content
    title TEXT,
    author TEXT,
    content_preview TEXT,
    is_post BOOLEAN DEFAULT TRUE, -- TRUE = post, FALSE = comment
    parent_post_id TEXT, -- If this is a comment

    -- Processing
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    relevance_score DECIMAL(3,2),
    sentiment TEXT CHECK (sentiment IN ('positive', 'negative', 'neutral', 'question')),

    -- Reply tracking
    should_reply BOOLEAN DEFAULT TRUE,
    replied BOOLEAN DEFAULT FALSE,
    reply_id UUID,
    replied_at TIMESTAMPTZ,
    skip_reason TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(client_id, reddit_post_id)
);

CREATE INDEX idx_mentions_client_replied ON public.mentions(client_id, replied) WHERE replied = FALSE;

-- Replies
CREATE TABLE public.replies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.reddit_accounts(id) ON DELETE SET NULL,
    mention_id UUID REFERENCES public.mentions(id) ON DELETE SET NULL,
    post_id UUID REFERENCES public.posts(id) ON DELETE SET NULL,

    -- Reddit data
    reddit_comment_id TEXT,
    reddit_url TEXT,
    parent_type TEXT CHECK (parent_type IN ('post', 'comment')),
    parent_reddit_id TEXT,

    -- Content
    content TEXT NOT NULL,

    -- Metrics
    upvotes INTEGER DEFAULT 0,

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'posted', 'failed', 'deleted', 'removed')),
    error_message TEXT,

    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metrics_updated_at TIMESTAMPTZ
);

-- ============================================================================
-- ANALYTICS TABLES
-- ============================================================================

-- Daily Metrics (materialized for performance)
CREATE TABLE public.daily_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    date DATE NOT NULL,

    -- Activity counts
    posts_count INTEGER DEFAULT 0,
    replies_count INTEGER DEFAULT 0,
    mentions_found INTEGER DEFAULT 0,
    mentions_replied INTEGER DEFAULT 0,

    -- Engagement
    total_upvotes INTEGER DEFAULT 0,
    total_comments INTEGER DEFAULT 0,

    -- Account health
    total_karma_gained INTEGER DEFAULT 0,
    accounts_active INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(client_id, date)
);

CREATE INDEX idx_daily_metrics_client_date ON public.daily_metrics(client_id, date DESC);

-- Activity Log (for audit trail)
CREATE TABLE public.activity_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
    client_id UUID REFERENCES public.clients(id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.reddit_accounts(id) ON DELETE SET NULL,

    activity_type TEXT NOT NULL CHECK (activity_type IN (
        'post_created', 'post_scheduled', 'post_published', 'post_failed',
        'reply_created', 'reply_published', 'reply_failed',
        'mention_detected', 'mention_skipped',
        'account_warmup', 'account_status_change',
        'client_onboarded', 'client_settings_changed'
    )),

    -- Context
    entity_type TEXT,
    entity_id UUID,
    details JSONB DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_activity_log_client ON public.activity_log(client_id, created_at DESC);
CREATE INDEX idx_activity_log_type ON public.activity_log(activity_type, created_at DESC);

-- ============================================================================
-- CONTENT TEMPLATES
-- ============================================================================

CREATE TABLE public.content_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES public.clients(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    template_type TEXT CHECK (template_type IN ('post', 'reply', 'warmup')),

    -- Template content (with placeholders)
    title_template TEXT,
    content_template TEXT NOT NULL,

    -- Targeting
    subreddit_types TEXT[], -- e.g., ['startup', 'saas', 'marketing']

    -- Performance
    times_used INTEGER DEFAULT 0,
    avg_upvotes DECIMAL(10,2) DEFAULT 0,

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get current user's organization_id
CREATE OR REPLACE FUNCTION public.get_user_organization_id()
RETURNS UUID AS $$
    SELECT organization_id FROM public.users WHERE id = auth.uid()
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- Function to check if user has access to client
CREATE OR REPLACE FUNCTION public.user_has_client_access(client_uuid UUID)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.clients c
        JOIN public.users u ON u.organization_id = c.organization_id
        WHERE c.id = client_uuid AND u.id = auth.uid()
    )
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to increment daily actions count
CREATE OR REPLACE FUNCTION public.increment_daily_actions(account_uuid UUID)
RETURNS INTEGER AS $$
DECLARE
    current_count INTEGER;
    reset_date DATE;
BEGIN
    SELECT daily_actions_count, daily_actions_reset_at
    INTO current_count, reset_date
    FROM public.reddit_accounts
    WHERE id = account_uuid;

    -- Reset count if it's a new day
    IF reset_date < CURRENT_DATE THEN
        UPDATE public.reddit_accounts
        SET daily_actions_count = 1, daily_actions_reset_at = CURRENT_DATE
        WHERE id = account_uuid;
        RETURN 1;
    ELSE
        UPDATE public.reddit_accounts
        SET daily_actions_count = daily_actions_count + 1
        WHERE id = account_uuid;
        RETURN current_count + 1;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at trigger to all relevant tables
CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_clients_updated_at BEFORE UPDATE ON public.clients
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_reddit_accounts_updated_at BEFORE UPDATE ON public.reddit_accounts
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_subreddits_updated_at BEFORE UPDATE ON public.subreddits
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_posts_updated_at BEFORE UPDATE ON public.posts
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER update_content_templates_updated_at BEFORE UPDATE ON public.content_templates
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX idx_users_organization ON public.users(organization_id);
CREATE INDEX idx_clients_organization ON public.clients(organization_id);
CREATE INDEX idx_clients_status ON public.clients(status);
CREATE INDEX idx_reddit_accounts_organization ON public.reddit_accounts(organization_id);
CREATE INDEX idx_reddit_accounts_status ON public.reddit_accounts(status);
CREATE INDEX idx_reddit_accounts_warmup ON public.reddit_accounts(warmup_stage) WHERE warmup_stage < 5;
CREATE INDEX idx_keywords_client ON public.keywords(client_id);
CREATE INDEX idx_keywords_f5bot ON public.keywords(f5bot_enabled) WHERE f5bot_enabled = TRUE;
CREATE INDEX idx_subreddits_client ON public.subreddits(client_id);
CREATE INDEX idx_subreddits_active ON public.subreddits(client_id, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_posts_client ON public.posts(client_id);
CREATE INDEX idx_mentions_client ON public.mentions(client_id);
CREATE INDEX idx_replies_client ON public.replies(client_id);
