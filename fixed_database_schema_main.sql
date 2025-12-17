-- BEGIN DESTRUCTIVE SCRIPT
-- WARNING: This will DROP data and objects. BACKUP before running.

-- 0) Helper: remove statement timeout for long ops (optional)
SET LOCAL statement_timeout = 0;

-- 1) Ensure extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2) Drop view, functions, triggers, policies, tables in safe order

-- Drop view
DROP VIEW IF EXISTS job_statistics CASCADE;

-- Drop cleanup and trigger functions (if exist)
DROP FUNCTION IF EXISTS cleanup_old_files() CASCADE;
DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;

-- Drop triggers if tables exist
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'bot_users') THEN
    IF EXISTS (
      SELECT 1 FROM pg_trigger t
      JOIN pg_class c ON t.tgrelid = c.oid
      WHERE t.tgname = 'update_bot_users_updated_at' AND c.relname = 'bot_users'
    ) THEN
      EXECUTE 'DROP TRIGGER update_bot_users_updated_at ON bot_users;';
    END IF;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'scraping_jobs') THEN
    IF EXISTS (
      SELECT 1 FROM pg_trigger t
      JOIN pg_class c ON t.tgrelid = c.oid
      WHERE t.tgname = 'update_scraping_jobs_updated_at' AND c.relname = 'scraping_jobs'
    ) THEN
      EXECUTE 'DROP TRIGGER update_scraping_jobs_updated_at ON scraping_jobs;';
    END IF;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'user_sessions') THEN
    IF EXISTS (
      SELECT 1 FROM pg_trigger t
      JOIN pg_class c ON t.tgrelid = c.oid
      WHERE t.tgname = 'update_user_sessions_updated_at' AND c.relname = 'user_sessions'
    ) THEN
      EXECUTE 'DROP TRIGGER update_user_sessions_updated_at ON user_sessions;';
    END IF;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'job_progress') THEN
    IF EXISTS (
      SELECT 1 FROM pg_trigger t
      JOIN pg_class c ON t.tgrelid = c.oid
      WHERE t.tgname = 'update_job_progress_updated_at' AND c.relname = 'job_progress'
    ) THEN
      EXECUTE 'DROP TRIGGER update_job_progress_updated_at ON job_progress;';
    END IF;
  END IF;
EXCEPTION WHEN undefined_table THEN
  -- ignore: table(s) don't exist
END$$;

-- Drop policies on tables (if exist)
DO $$
DECLARE
  rec text;
  items text[] := ARRAY[
    'bot_users|Service role full access',
    'scraping_jobs|Service role full access',
    'scraped_songs|Service role full access',
    'job_progress|Service role full access',
    'user_sessions|Service role full access',
    'bot_users|Users can access own data',
    'scraping_jobs|Users can access own jobs',
    'scraped_songs|Users can access own songs',
    'job_progress|Users can access own progress',
    'user_sessions|Users can access own sessions',
    'bot_users|Allow anonymous user registration'
  ];
BEGIN
  FOREACH rec IN ARRAY items LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I;', split_part(rec, '|', 2), split_part(rec, '|', 1));
  END LOOP;

  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    EXECUTE 'DROP POLICY IF EXISTS "Service role storage access" ON storage.objects;';
    EXECUTE 'DROP POLICY IF EXISTS "Users can upload to own folder" ON storage.objects;';
    EXECUTE 'DROP POLICY IF EXISTS "Users can read own files" ON storage.objects;';
    EXECUTE 'DROP POLICY IF EXISTS "Users can delete own files" ON storage.objects;';
  END IF;
END$$;

-- Drop tables (dependent tables first)
DROP TABLE IF EXISTS file_cleanup_log CASCADE;
DROP TABLE IF EXISTS scraped_songs CASCADE;
DROP TABLE IF EXISTS job_progress CASCADE;
DROP TABLE IF EXISTS user_sessions CASCADE;
DROP TABLE IF EXISTS scraping_jobs CASCADE;
DROP TABLE IF EXISTS bot_users CASCADE;

-- Remove storage bucket metadata if present (does NOT delete actual bucket content)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    DELETE FROM storage.buckets WHERE id = 'loveworld-files';
  END IF;
END$$;

-- 3) Recreate tables and objects

-- 3.1 Bot Users Table
CREATE TABLE bot_users (
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

-- 3.2 Scraping Jobs Table
CREATE TABLE scraping_jobs (
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

-- 3.3 Scraped Songs Table
CREATE TABLE scraped_songs (
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

-- 3.4 Job Progress Tracking Table
CREATE TABLE job_progress (
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

-- 3.5 User Sessions Table
CREATE TABLE user_sessions (
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

-- 3.6 File Cleanup Log Table
CREATE TABLE file_cleanup_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_path TEXT NOT NULL,
    file_type VARCHAR(50),
    file_size_bytes BIGINT,
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    job_id UUID,
    cleanup_reason VARCHAR(100) DEFAULT 'auto_delete'
);

-- 4) Indexes
CREATE INDEX idx_scraping_jobs_user_id ON scraping_jobs(user_id);
CREATE INDEX idx_scraping_jobs_status ON scraping_jobs(status);
CREATE INDEX idx_scraping_jobs_created_at ON scraping_jobs(created_at);
CREATE INDEX idx_scraped_songs_job_id ON scraped_songs(job_id);
CREATE INDEX idx_job_progress_job_id ON job_progress(job_id);
CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_file_cleanup_deleted_at ON file_cleanup_log(deleted_at);

-- 5) Trigger function and triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_bot_users_updated_at
  BEFORE UPDATE ON bot_users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scraping_jobs_updated_at
  BEFORE UPDATE ON scraping_jobs
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_sessions_updated_at
  BEFORE UPDATE ON user_sessions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_job_progress_updated_at
  BEFORE UPDATE ON job_progress
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 6) Enable RLS
ALTER TABLE bot_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraping_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraped_songs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;

-- 7) Policies

-- Service role full access
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

-- Users own-data policies
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

-- Allow anonymous user registration
CREATE POLICY "Allow anonymous user registration" ON bot_users
  FOR INSERT WITH CHECK (true);

-- 8) Storage policies (only apply if storage schema present)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    CREATE POLICY "Service role storage access" ON storage.objects
      FOR ALL USING (auth.role() = 'service_role');

    CREATE POLICY "Users can upload to own folder" ON storage.objects
      FOR INSERT WITH CHECK (
        bucket_id = 'loveworld-files'
        AND auth.role() = 'authenticated'
        AND (storage.foldername(name))[1] = auth.uid()::text
      );

    CREATE POLICY "Users can read own files" ON storage.objects
      FOR SELECT USING (
        bucket_id = 'loveworld-files'
        AND auth.role() = 'authenticated'
        AND (storage.foldername(name))[1] = auth.uid()::text
      );

    CREATE POLICY "Users can delete own files" ON storage.objects
      FOR DELETE USING (
        bucket_id = 'loveworld-files'
        AND auth.role() = 'authenticated'
        AND (storage.foldername(name))[1] = auth.uid()::text
      );
  END IF;
END$$;

-- 9) Cleanup function
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

-- 10) View
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
  COUNT(ss.id) AS actual_songs_processed
FROM scraping_jobs j
LEFT JOIN bot_users bu ON j.user_id = bu.telegram_user_id
LEFT JOIN scraped_songs ss ON j.id = ss.job_id
GROUP BY j.id, j.job_id, j.status, j.total_songs, j.completed_songs,
  j.failed_songs, j.lyrics_completed, j.audio_completed,
  j.created_at, j.completed_at, bu.username, bu.first_name;

-- 11) Grants
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated;

-- 12) Recreate storage bucket metadata if storage exists
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    IF NOT EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'loveworld-files') THEN
      INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
      VALUES ('loveworld-files', 'loveworld-files', false, 52428800, ARRAY['audio/*','text/*','application/zip']);
    END IF;
  END IF;
END$$;

-- 13) (Optional) Add tables to publication for realtime (run manually if needed)
-- ALTER PUBLICATION supabase_realtime ADD TABLE scraping_jobs;
-- ALTER PUBLICATION supabase_realtime ADD TABLE job_progress;
-- ALTER PUBLICATION supabase_realtime ADD TABLE user_sessions;

-- END DESTRUCTIVE SCRIPT