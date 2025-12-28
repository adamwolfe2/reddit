-- ============================================================================
-- ROW LEVEL SECURITY POLICIES
-- Run this AFTER 001_schema.sql
-- ============================================================================

-- Enable RLS on all tables
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reddit_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keywords ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subreddits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.replies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.activity_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_templates ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- ORGANIZATIONS POLICIES
-- ============================================================================

-- Users can view their own organization
CREATE POLICY "Users can view own organization"
ON public.organizations FOR SELECT
TO authenticated
USING (id = public.get_user_organization_id());

-- Only owners can update organization
CREATE POLICY "Owners can update organization"
ON public.organizations FOR UPDATE
TO authenticated
USING (
    id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role = 'owner'
    )
);

-- ============================================================================
-- USERS POLICIES
-- ============================================================================

-- Users can view members of their organization
CREATE POLICY "Users can view org members"
ON public.users FOR SELECT
TO authenticated
USING (organization_id = public.get_user_organization_id());

-- Users can update their own profile
CREATE POLICY "Users can update own profile"
ON public.users FOR UPDATE
TO authenticated
USING (id = auth.uid());

-- Allow insert for new users (during signup)
CREATE POLICY "Users can insert own profile"
ON public.users FOR INSERT
TO authenticated
WITH CHECK (id = auth.uid());

-- ============================================================================
-- CLIENTS POLICIES
-- ============================================================================

-- Users can view clients in their organization
CREATE POLICY "Users can view org clients"
ON public.clients FOR SELECT
TO authenticated
USING (organization_id = public.get_user_organization_id());

-- Admins and owners can create clients
CREATE POLICY "Admins can create clients"
ON public.clients FOR INSERT
TO authenticated
WITH CHECK (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

-- Admins and owners can update clients
CREATE POLICY "Admins can update clients"
ON public.clients FOR UPDATE
TO authenticated
USING (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

-- Owners can delete clients
CREATE POLICY "Owners can delete clients"
ON public.clients FOR DELETE
TO authenticated
USING (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role = 'owner'
    )
);

-- ============================================================================
-- REDDIT ACCOUNTS POLICIES
-- ============================================================================

CREATE POLICY "Users can view org reddit accounts"
ON public.reddit_accounts FOR SELECT
TO authenticated
USING (organization_id = public.get_user_organization_id());

CREATE POLICY "Admins can insert reddit accounts"
ON public.reddit_accounts FOR INSERT
TO authenticated
WITH CHECK (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

CREATE POLICY "Admins can update reddit accounts"
ON public.reddit_accounts FOR UPDATE
TO authenticated
USING (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

CREATE POLICY "Admins can delete reddit accounts"
ON public.reddit_accounts FOR DELETE
TO authenticated
USING (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

-- ============================================================================
-- KEYWORDS POLICIES
-- ============================================================================

CREATE POLICY "Users can view client keywords"
ON public.keywords FOR SELECT
TO authenticated
USING (public.user_has_client_access(client_id));

CREATE POLICY "Admins can insert keywords"
ON public.keywords FOR INSERT
TO authenticated
WITH CHECK (
    public.user_has_client_access(client_id)
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

CREATE POLICY "Admins can update keywords"
ON public.keywords FOR UPDATE
TO authenticated
USING (
    public.user_has_client_access(client_id)
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

CREATE POLICY "Admins can delete keywords"
ON public.keywords FOR DELETE
TO authenticated
USING (
    public.user_has_client_access(client_id)
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

-- ============================================================================
-- SUBREDDITS POLICIES
-- ============================================================================

CREATE POLICY "Users can view client subreddits"
ON public.subreddits FOR SELECT
TO authenticated
USING (public.user_has_client_access(client_id));

CREATE POLICY "Members can insert subreddits"
ON public.subreddits FOR INSERT
TO authenticated
WITH CHECK (public.user_has_client_access(client_id));

CREATE POLICY "Members can update subreddits"
ON public.subreddits FOR UPDATE
TO authenticated
USING (public.user_has_client_access(client_id));

CREATE POLICY "Admins can delete subreddits"
ON public.subreddits FOR DELETE
TO authenticated
USING (
    public.user_has_client_access(client_id)
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

-- ============================================================================
-- POSTS POLICIES
-- ============================================================================

CREATE POLICY "Users can view client posts"
ON public.posts FOR SELECT
TO authenticated
USING (public.user_has_client_access(client_id));

CREATE POLICY "Members can create posts"
ON public.posts FOR INSERT
TO authenticated
WITH CHECK (public.user_has_client_access(client_id));

CREATE POLICY "Members can update posts"
ON public.posts FOR UPDATE
TO authenticated
USING (public.user_has_client_access(client_id));

CREATE POLICY "Admins can delete posts"
ON public.posts FOR DELETE
TO authenticated
USING (
    public.user_has_client_access(client_id)
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

-- ============================================================================
-- MENTIONS POLICIES
-- ============================================================================

CREATE POLICY "Users can view client mentions"
ON public.mentions FOR SELECT
TO authenticated
USING (public.user_has_client_access(client_id));

CREATE POLICY "System can insert mentions"
ON public.mentions FOR INSERT
TO authenticated
WITH CHECK (public.user_has_client_access(client_id));

CREATE POLICY "Members can update mentions"
ON public.mentions FOR UPDATE
TO authenticated
USING (public.user_has_client_access(client_id));

-- ============================================================================
-- REPLIES POLICIES
-- ============================================================================

CREATE POLICY "Users can view client replies"
ON public.replies FOR SELECT
TO authenticated
USING (public.user_has_client_access(client_id));

CREATE POLICY "Members can insert replies"
ON public.replies FOR INSERT
TO authenticated
WITH CHECK (public.user_has_client_access(client_id));

CREATE POLICY "Members can update replies"
ON public.replies FOR UPDATE
TO authenticated
USING (public.user_has_client_access(client_id));

-- ============================================================================
-- DAILY METRICS POLICIES
-- ============================================================================

CREATE POLICY "Users can view client metrics"
ON public.daily_metrics FOR SELECT
TO authenticated
USING (public.user_has_client_access(client_id));

-- Service role handles inserts/updates for metrics

-- ============================================================================
-- ACTIVITY LOG POLICIES
-- ============================================================================

CREATE POLICY "Users can view org activity"
ON public.activity_log FOR SELECT
TO authenticated
USING (organization_id = public.get_user_organization_id());

-- Service role handles inserts for activity log

-- ============================================================================
-- CONTENT TEMPLATES POLICIES
-- ============================================================================

CREATE POLICY "Users can view templates"
ON public.content_templates FOR SELECT
TO authenticated
USING (
    organization_id = public.get_user_organization_id()
    OR (client_id IS NOT NULL AND public.user_has_client_access(client_id))
);

CREATE POLICY "Admins can insert templates"
ON public.content_templates FOR INSERT
TO authenticated
WITH CHECK (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

CREATE POLICY "Admins can update templates"
ON public.content_templates FOR UPDATE
TO authenticated
USING (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

CREATE POLICY "Admins can delete templates"
ON public.content_templates FOR DELETE
TO authenticated
USING (
    organization_id = public.get_user_organization_id()
    AND EXISTS (
        SELECT 1 FROM public.users
        WHERE id = auth.uid() AND role IN ('owner', 'admin')
    )
);

-- ============================================================================
-- SERVICE ROLE BYPASS NOTE
-- ============================================================================

-- The service_role key in Supabase automatically bypasses RLS
-- Make sure to use the service_role key (not anon key) for all N8N/Python operations
-- This allows backend workers to read/write all data regardless of RLS policies
