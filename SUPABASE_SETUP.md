# Supabase Integration Setup Guide

This guide will help you set up Supabase integration for the Loveworld Bot, including Storage, Database, and Realtime functionality.

## Prerequisites

1. **Supabase Account**: Create a free account at [supabase.com](https://supabase.com)
2. **Telegram Bot Token**: Get from [@BotFather](https://t.me/botfather)
3. **Domain/Server**: For webhook deployment (optional for development)

## Step 1: Create Supabase Project

1. Go to [supabase.com](https://supabase.com) and sign in
2. Click "New Project"
3. Choose your organization
4. Fill in project details:
   - **Name**: `loveworld-bot`
   - **Database Password**: Choose a strong password
   - **Region**: Select closest to your server
5. Click "Create new project"
6. Wait for project initialization (2-3 minutes)

## Step 2: Get Supabase Credentials

1. Go to Project Settings → API
2. Copy the following values:
   - **Project URL**: `https://your-project-id.supabase.co`
   - **anon public key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`
   - **service_role key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`

⚠️ **Important**: Keep the `service_role` key secret - it has admin access!

## Step 3: Set Up Database Schema

1. In your Supabase project, go to "SQL Editor"
2. Create a new query
3. Copy and paste the contents of `database_schema.sql`
4. Click "Run" to execute the schema

This will create all necessary tables:
- `bot_users` - User management
- `scraping_jobs` - Job tracking
- `scraped_songs` - Song data
- `job_progress` - Progress tracking
- `user_sessions` - Interactive sessions
- `file_cleanup_log` - Cleanup tracking

## Step 4: Set Up Storage Bucket

### Method 1: Via SQL (Recommended)

1. In SQL Editor, run:
```sql
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('loveworld-files', 'loveworld-files', false, 52428800, ARRAY['audio/*', 'text/*', 'application/zip']);
```

2. Set up storage policies:
```sql
-- Allow authenticated users to upload
CREATE POLICY "Authenticated users can upload" ON storage.objects
FOR INSERT WITH CHECK (bucket_id = 'loveworld-files' AND auth.role() = 'authenticated');

-- Allow users to read their own files
CREATE POLICY "Users can read own files" ON storage.objects
FOR SELECT USING (bucket_id = 'loveworld-files');

-- Allow users to delete their own files
CREATE POLICY "Users can delete own files" ON storage.objects
FOR DELETE USING (bucket_id = 'loveworld-files');
```

### Method 2: Via Dashboard

1. Go to "Storage" in your Supabase dashboard
2. Click "Create bucket"
3. Name: `loveworld-files`
4. Public: `Disabled` (recommended for security)
5. File size limit: `50MB`
6. Allowed MIME types: `audio/*, text/*, application/zip`

## Step 5: Configure Environment Variables

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Edit `.env` with your values:
```bash
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
WEBHOOK_URL=https://your-domain.com
PORT=8000
ADMIN_IDS=123456789,987654321

# Supabase (from Step 2)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your_anon_key_here
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here

# Storage Configuration
STORAGE_BUCKET_NAME=loveworld-files
AUTO_DELETE_INTERVAL=3600
```

## Step 6: Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt
```

## Step 7: Test the Integration

### Local Testing

1. Run the bot in polling mode:
```bash
python main_supabase.py bot
```

2. Start the bot on Telegram and send `/start`
3. Upload a test file to see if storage works

### Production Testing

1. Set webhook URL in `.env`
2. Run the server:
```bash
python main_supabase.py
```

3. Test API endpoints:
```bash
curl http://localhost:8000/
```

## Step 8: Enable Realtime

Realtime is automatically enabled for the following tables:
- `scraping_jobs`
- `job_progress`
- `user_sessions`

To verify:
1. Go to Database → Replication
2. Check that realtime is enabled for the tables above

## Step 9: Set Up Auto-Delete (Optional)

Files are automatically deleted every hour (3600 seconds). To customize:

1. Edit `AUTO_DELETE_INTERVAL` in `.env`
2. Values:
   - `3600` = 1 hour
   - `1800` = 30 minutes
   - `7200` = 2 hours

## Step 10: Monitor and Maintain

### Check Storage Usage
1. Go to Supabase Dashboard → Storage
2. Monitor file count and storage usage

### Monitor Database
1. Go to Database → Table Editor
2. Check job and user tables

### View Logs
1. Go to Logs in Supabase dashboard
2. Monitor for errors or performance issues

## Troubleshooting

### Common Issues

#### 1. "Missing required Supabase environment variables"
- Check `.env` file exists and has correct values
- Verify Supabase credentials are correct

#### 2. "Failed to create Supabase client"
- Check internet connection
- Verify Supabase project is active
- Check API keys are valid

#### 3. "Bucket not found"
- Ensure storage bucket was created in Step 4
- Check bucket name matches `STORAGE_BUCKET_NAME`

#### 4. "Permission denied" errors
- Check storage policies are set up correctly
- Verify RLS policies in database schema

#### 5. Files not auto-deleting
- Check `AUTO_DELETE_INTERVAL` setting
- Verify cleanup scheduler is running
- Check Supabase logs for errors

### Debug Mode

Enable debug logging by adding to `.env`:
```bash
LOG_LEVEL=DEBUG
```

## Security Best Practices

1. **Never commit `.env` file** to version control
2. **Use service_role key only** for server-side operations
3. **Keep buckets private** unless public access is needed
4. **Regular cleanup** of old jobs and files
5. **Monitor storage usage** to avoid unexpected costs

## Cost Management

### Supabase Free Tier Includes:
- **Database**: 500MB storage, 2GB bandwidth
- **Storage**: 1GB storage, 2GB bandwidth
- **Realtime**: 500,000 messages
- **API**: 50,000 requests per month

### Cost Optimization Tips:
1. Enable auto-deletion (already configured)
2. Monitor storage usage regularly
3. Clean up old jobs periodically
4. Use appropriate file compression

## Production Deployment

### Environment Variables for Production
```bash
ENVIRONMENT=production
LOG_LEVEL=INFO
AUTO_DELETE_INTERVAL=3600
```

### Monitoring
1. Set up Supabase monitoring alerts
2. Monitor bot response times
3. Track storage and database usage
4. Set up error notifications

## Support

If you encounter issues:

1. Check this guide first
2. Review Supabase documentation
3. Check bot logs for error messages
4. Test individual components separately

## Next Steps

After successful setup:

1. **Test thoroughly** with real data
2. **Monitor performance** and usage
3. **Set up backup strategies** for important data
4. **Plan scaling** if usage increases
5. **Consider premium features** if needed

---

**Happy botting with Supabase! ☁️🚀**