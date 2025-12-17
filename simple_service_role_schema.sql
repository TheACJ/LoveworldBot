-- Simple Service Role Schema for Loveworld Bot
-- This version works with just the Service Role key - no complex RLS policies

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Bot Users Table
CREATE TABLE IF NOT EXISTS bot_users (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Scraping Jobs Table
CREATE TABLE IF NOT EXISTS scraping_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id VARCHAR(255) UNIQUE NOT NULL,
    user_id BIGINT NOT NULL,
    status VARCHAR(50) DEFAULT 'queued',
    total_songs INTEGER DEFAULT 0,
    completed_songs INTEGER DEFAULT 0,
    failed_songs INTEGER DEFAULT 0,
    lyrics_completed INTEGER DEFAULT 0,
    audio_completed INTEGER DEFAULT 0,
    progress_data JSONB DEFAULT '{}',
    download_url TEXT,
    storage_path TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 3. Scraped Songs Table
CREATE TABLE IF NOT EXISTS scraped_songs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL,
    song_title VARCHAR(500) NOT NULL,
    artist VARCHAR(500) NOT NULL,
    original_url TEXT NOT NULL,
    event_name VARCHAR(255),
    lyrics_content TEXT,
    lyrics_storage_path TEXT,
    audio_storage_path TEXT,
    audio_filename VARCHAR(255),
    audio_size_bytes BIGINT,
    has_lyrics BOOLEAN DEFAULT FALSE,
    has_audio BOOLEAN DEFAULT FALSE,
    scraped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(job_id, original_url)
);

-- 4. Job Progress Tracking Table
CREATE TABLE IF NOT EXISTS job_progress (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL,
    phase VARCHAR(50) NOT NULL,
    current_song_index INTEGER DEFAULT 0,
    total_songs INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running',
    progress_percentage DECIMAL(5,2) DEFAULT 0.00,
    current_song_title VARCHAR(500),
    error_details TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(job_id, phase)
);

-- 5. User Sessions Table
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    session_type VARCHAR(50) DEFAULT 'addsong',
    current_song_data JSONB DEFAULT '{}',
    song_queue JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, session_type, is_active)
);

-- 6. File Cleanup Log Table
CREATE TABLE IF NOT EXISTS file_cleanup_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_path TEXT NOT NULL,
    file_type VARCHAR(50),
    file_size_bytes BIGINT,
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    job_id UUID,
    cleanup_reason VARCHAR(100) DEFAULT 'auto_delete'
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_scraping_jobs_user_id ON scraping_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_scraping_jobs_status ON scraping_jobs(status);
CREATE INDEX IF NOT EXISTS idx_scraping_jobs_created_at ON scraping_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_scraped_songs_job_id ON scraped_songs(job_id);
CREATE INDEX IF NOT EXISTS idx_job_progress_job_id ON job_progress(job_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_file_cleanup_deleted_at ON file_cleanup_log(deleted_at);

-- Trigger function for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers
DROP TRIGGER IF EXISTS update_bot_users_updated_at ON bot_users;
CREATE TRIGGER update_bot_users_updated_at BEFORE UPDATE ON bot_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_scraping_jobs_updated_at ON scraping_jobs;
CREATE TRIGGER update_scraping_jobs_updated_at BEFORE UPDATE ON scraping_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_user_sessions_updated_at ON user_sessions;
CREATE TRIGGER update_user_sessions_updated_at BEFORE UPDATE ON user_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_job_progress_updated_at ON job_progress;
CREATE TRIGGER update_job_progress_updated_at BEFORE UPDATE ON job_progress
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- NO RLS - Simple approach for service role only
-- RLS disabled for all tables (service role has full access)

-- Storage bucket creation
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'loveworld-files') THEN
        INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        VALUES ('loveworld-files', 'loveworld-files', false, 52428800, ARRAY['audio/*', 'text/*', 'application/zip']);
    END IF;
END $$;

-- Storage policies - Simple service role access
DROP POLICY IF EXISTS "Service role storage access" ON storage.objects;
CREATE POLICY "Service role storage access" ON storage.objects
    FOR ALL USING (auth.role() = 'service_role');

-- Allow public read access to signed URLs (for downloads)
DROP POLICY IF EXISTS "Public read access" ON storage.objects;
CREATE POLICY "Public read access" ON storage.objects
    FOR SELECT USING (bucket_id = 'loveworld-files');

-- Cleanup function
CREATE OR REPLACE FUNCTION cleanup_old_files()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
    file_record RECORD;
BEGIN
    FOR file_record IN 
        SELECT DISTINCT ON (storage_path) storage_path, id, job_id
        FROM scraped_songs 
        WHERE scraped_at < NOW() - INTERVAL '1 hour'
        AND storage_path IS NOT NULL
    LOOP
        INSERT INTO file_cleanup_log (file_path, file_type, job_id, cleanup_reason)
        SELECT file_record.storage_path, 'scraped_file', file_record.job_id, 'auto_delete'
        WHERE NOT EXISTS (
            SELECT 1 FROM file_cleanup_log f WHERE f.file_path = file_record.storage_path
        );
        
        deleted_count := deleted_count + 1;
    END LOOP;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- View for job statistics
CREATE OR REPLACE VIEW job_statistics AS
SELECT 
    j.id,
    j.job_id,
    j.status,
    j.total_songs,
    j.completed_songs,
    j.failed_songs,
    j.lyrics_completed,
    j.audio_completed,
    j.created_at,
    j.completed_at,
    bu.username,
    bu.first_name,
    COUNT(ss.id) as actual_songs_processed
FROM scraping_jobs j
LEFT JOIN bot_users bu ON j.user_id = bu.telegram_user_id
LEFT JOIN scraped_songs ss ON j.id = ss.job_id
GROUP BY j.id, j.job_id, j.status, j.total_songs, j.completed_songs, 
         j.failed_songs, j.lyrics_completed, j.audio_completed, 
         j.created_at, j.completed_at, bu.username, bu.first_name;

-- Grants
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated;

-- Enable realtime
ALTER PUBLICATION supabase_realtime ADD TABLE scraping_jobs;
ALTER PUBLICATION supabase_realtime ADD TABLE job_progress;
ALTER PUBLICATION supabase_realtime ADD TABLE user_sessions;