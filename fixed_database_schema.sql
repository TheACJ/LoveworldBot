-- Loveworld Bot Database Schema for Supabase (Fixed RLS Policies)
-- Run this SQL in your Supabase SQL Editor

-- Enable necessary extensions
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
    job_id VARCHAR(255) UNIQUE NOT NULL, -- Custom job ID (user_id_timestamp format)
    user_id BIGINT NOT NULL,
    status VARCHAR(50) DEFAULT 'queued', -- queued, running, completed, failed, cancelled
    total_songs INTEGER DEFAULT 0,
    completed_songs INTEGER DEFAULT 0,
    failed_songs INTEGER DEFAULT 0,
    lyrics_completed INTEGER DEFAULT 0,
    audio_completed INTEGER DEFAULT 0,
    progress_data JSONB DEFAULT '{}',
    download_url TEXT,
    storage_path TEXT, -- Path to ZIP file in Supabase Storage
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
    lyrics_storage_path TEXT, -- Path to lyrics file in Storage
    audio_storage_path TEXT,  -- Path to audio file in Storage
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
    phase VARCHAR(50) NOT NULL, -- lyrics, audio, archiving
    current_song_index INTEGER DEFAULT 0,
    total_songs INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running', -- running, completed, failed
    progress_percentage DECIMAL(5,2) DEFAULT 0.00,
    current_song_title VARCHAR(500),
    error_details TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(job_id, phase)
);

-- 5. User Sessions Table (for interactive mode)
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL,
    session_type VARCHAR(50) DEFAULT 'addsong', -- addsong, queue, etc.
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
    file_type VARCHAR(50), -- audio, lyrics, archive, temp
    file_size_bytes BIGINT,
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    job_id UUID,
    cleanup_reason VARCHAR(100) DEFAULT 'auto_delete' -- auto_delete, manual, job_cleanup
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_scraping_jobs_user_id ON scraping_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_scraping_jobs_status ON scraping_jobs(status);
CREATE INDEX IF NOT EXISTS idx_scraping_jobs_created_at ON scraping_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_scraped_songs_job_id ON scraped_songs(job_id);
CREATE INDEX IF NOT EXISTS idx_job_progress_job_id ON job_progress(job_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_file_cleanup_deleted_at ON file_cleanup_log(deleted_at);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
CREATE TRIGGER update_bot_users_updated_at BEFORE UPDATE ON bot_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scraping_jobs_updated_at BEFORE UPDATE ON scraping_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_sessions_updated_at BEFORE UPDATE ON user_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_job_progress_updated_at BEFORE UPDATE ON job_progress
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- FIXED RLS Policies - Allow service role full access
ALTER TABLE bot_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraping_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraped_songs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;

-- Allow service role to do everything
CREATE POLICY "Service role full access" ON bot_users
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access" ON scraping_jobs
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access" ON scraped_songs
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access" ON job_progress
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access" ON user_sessions
    FOR ALL USING (auth.role() = 'service_role');

-- Allow authenticated users to access their own data
CREATE POLICY "Users can access own data" ON bot_users
    FOR ALL USING (telegram_user_id = current_setting('app.current_user_id')::BIGINT);

CREATE POLICY "Users can access own jobs" ON scraping_jobs
    FOR ALL USING (user_id = current_setting('app.current_user_id')::BIGINT);

CREATE POLICY "Users can access own songs" ON scraped_songs
    FOR ALL USING (
        job_id IN (
            SELECT id FROM scraping_jobs 
            WHERE user_id = current_setting('app.current_user_id')::BIGINT
        )
    );

CREATE POLICY "Users can access own progress" ON job_progress
    FOR ALL USING (
        job_id IN (
            SELECT id FROM scraping_jobs 
            WHERE user_id = current_setting('app.current_user_id')::BIGINT
        )
    );

CREATE POLICY "Users can access own sessions" ON user_sessions
    FOR ALL USING (user_id = current_setting('app.current_user_id')::BIGINT);

-- Allow anonymous users to insert bot_users (for registration)
CREATE POLICY "Allow anonymous user registration" ON bot_users
    FOR INSERT WITH CHECK (true);

-- Storage bucket creation (run this separately in Supabase Storage)
-- Create bucket named 'loveworld-files' with public access disabled
-- INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
-- VALUES ('loveworld-files', 'loveworld-files', false, 52428800, ARRAY['audio/*', 'text/*', 'application/zip']);

-- Storage policies - FIXED
-- Allow service role to do everything with storage
CREATE POLICY "Service role storage access" ON storage.objects
    FOR ALL USING (auth.role() = 'service_role');

-- Allow authenticated users to upload to their own folders
CREATE POLICY "Users can upload to own folder" ON storage.objects
    FOR INSERT WITH CHECK (
        bucket_id = 'loveworld-files' 
        AND auth.role() = 'authenticated'
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

-- Allow users to read their own files
CREATE POLICY "Users can read own files" ON storage.objects
    FOR SELECT USING (
        bucket_id = 'loveworld-files'
        AND auth.role() = 'authenticated'
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

-- Allow users to delete their own files
CREATE POLICY "Users can delete own files" ON storage.objects
    FOR DELETE USING (
        bucket_id = 'loveworld-files'
        AND auth.role() = 'authenticated'
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

-- Function to automatically clean up old files (for cron job)
CREATE OR REPLACE FUNCTION cleanup_old_files()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
    file_record RECORD;
BEGIN
    -- Delete files older than 1 hour
    FOR file_record IN 
        SELECT DISTINCT ON (storage_path) storage_path, id
        FROM scraped_songs 
        WHERE scraped_at < NOW() - INTERVAL '1 hour'
        AND storage_path IS NOT NULL
    LOOP
        -- Log the cleanup
        INSERT INTO file_cleanup_log (file_path, file_type, job_id, cleanup_reason)
        SELECT file_record.storage_path, 'scraped_file', job_id, 'auto_delete'
        FROM scraped_songs WHERE id = file_record.id;
        
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

-- Grant necessary permissions
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated;

-- Enable realtime for relevant tables
ALTER PUBLICATION supabase_realtime ADD TABLE scraping_jobs;
ALTER PUBLICATION supabase_realtime ADD TABLE job_progress;
ALTER PUBLICATION supabase_realtime ADD TABLE user_sessions;

-- Create storage bucket (if it doesn't exist)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'loveworld-files') THEN
        INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        VALUES ('loveworld-files', 'loveworld-files', false, 52428800, ARRAY['audio/*', 'text/*', 'application/zip']);
    END IF;
END $$;