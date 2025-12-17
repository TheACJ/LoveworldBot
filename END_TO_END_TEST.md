# End-to-End Supabase Integration Test

This guide will walk you through testing the complete Supabase integration with a real project.

## 🔧 Step 1: Create Supabase Project

### 1.1 Create Account & Project
1. Go to [supabase.com](https://supabase.com)
2. Sign up/Login with your account
3. Click "New Project"
4. Fill in project details:
   - **Name**: `loveworld-bot-test`
   - **Database Password**: `your_secure_password_here`
   - **Region**: Choose closest to your location
5. Wait 2-3 minutes for project initialization

### 1.2 Get Credentials
1. Go to **Settings → API** in your Supabase dashboard
2. Copy these values:
   ```
   Project URL: https://xxxxx.supabase.co
   anon public: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   service_role: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   ```

## 📁 Step 2: Configure Environment

### 2.1 Setup Environment File
```bash
# Copy the example file
cp .env.example .env
```

### 2.2 Add Your Credentials
Edit `.env` file with your actual values:

```bash
# Telegram Bot (use your existing bot token)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
WEBHOOK_URL=http://localhost:8000
PORT=8000
ADMIN_IDS=your_telegram_user_id

# Supabase (paste your actual credentials)
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Storage Configuration
STORAGE_BUCKET_NAME=loveworld-files
AUTO_DELETE_INTERVAL=3600

# Optional: Add your Telegram Bot token if you don't have one
# Get from @BotFather on Telegram
```

## 🗄️ Step 3: Setup Database Schema

### 3.1 Run Database Setup
1. In your Supabase dashboard, go to **SQL Editor**
2. Create a new query
3. Copy the entire contents of `database_schema.sql`
4. Paste and click **Run**
5. You should see "Success. No rows returned"

### 3.2 Verify Tables Created
Run this query to check tables:
```sql
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public'
ORDER BY table_name;
```

You should see these tables:
- `bot_users`
- `scraping_jobs`
- `scraped_songs`
- `job_progress`
- `user_sessions`
- `file_cleanup_log`

## ☁️ Step 4: Setup Storage Bucket

### 4.1 Create Storage Bucket (SQL Method)
In SQL Editor, run:
```sql
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('loveworld-files', 'loveworld-files', false, 52428800, ARRAY['audio/*', 'text/*', 'application/zip']);
```

### 4.2 Setup Storage Policies
Run these policies:
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

## 🧪 Step 5: Test Integration

### 5.1 Basic Integration Test
```bash
python basic_test.py
```

**Expected Output:**
```
=== Supabase Integration Test ===
Testing imports...
PASS: supabase_config imported
PASS: supabase_storage imported
PASS: supabase_database imported
PASS: supabase_realtime imported

Testing configuration...
PASS: Storage bucket = loveworld-files
PASS: Auto-delete = 3600 seconds

=== Results ===
Passed: 2/2

SUCCESS: All basic tests passed!
```

### 5.2 Full Integration Test
```bash
python test_supabase_integration.py
```

**Expected Output:**
```
🚀 Starting Supabase Integration Tests

🔧 Testing Supabase Configuration...
✅ Configuration is valid

🗄️  Testing Database Connection...
✅ Database connection successful

☁️  Testing Storage Bucket...
✅ Storage bucket initialized successfully

📤 Testing File Upload...
✅ File upload successful

⚡ Testing Realtime Service...
✅ Realtime service initialized successfully

📋 Testing Job Management...
✅ Job creation successful
✅ Job update successful

==================================================
📊 TEST SUMMARY
Configuration       ✅ PASSED
Database           ✅ PASSED
Storage            ✅ PASSED
File Upload        ✅ PASSED
Realtime           ✅ PASSED
Job Management     ✅ PASSED

Total: 6/6 tests passed

🎉 All tests passed! Supabase integration is working correctly.
```

## 🤖 Step 6: Test Telegram Bot

### 6.1 Test Bot in Polling Mode
```bash
python main_supabase.py bot
```

**Expected Output:**
```
🤖 Starting Telegram Bot (Polling Mode)...
🔄 Initializing Supabase services...
✅ Supabase services initialized successfully
✅ Webhook set successfully
```

### 6.2 Test Bot Commands
1. Start your bot on Telegram
2. Send `/start` command
3. You should see welcome message with "☁️ **Cloud Storage**" features
4. Upload a test JSON file to trigger file processing

### 6.3 Verify Database Operations
Check your Supabase dashboard:
- **Table Editor**: Look for entries in `bot_users`, `scraping_jobs`
- **Storage**: Check for uploaded files in `loveworld-files` bucket

## 🌐 Step 7: Test FastAPI Server

### 7.1 Start Server
```bash
python main_supabase.py
```

**Expected Output:**
```
🚀 Starting FastAPI Server with Supabase Integration...
📡 Webhook URL: http://localhost:8000
✅ Webhook set successfully
INFO:     Started server process
INFO:     Waiting for application startup.
🔄 Initializing Supabase services...
✅ Supabase services initialized successfully
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 7.2 Test API Endpoints
```bash
# Health check
curl http://localhost:8000/

# Expected response:
# {"message":"Loveworld Scraper Bot API with Supabase","status":"running"}

# Test job creation
curl -X POST http://localhost:8000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"songs":[{"title":"Test Song","artist":"Test Artist","url":"https://example.com"}]}'
```

## 📊 Step 8: Verify Auto-Delete Feature

### 8.1 Check File Upload
1. Upload a file through the bot or API
2. Check Supabase Storage dashboard
3. Note the file upload time

### 8.2 Wait for Auto-Delete
1. Files should be automatically deleted after 1 hour
2. Check `file_cleanup_log` table for cleanup records:
```sql
SELECT * FROM file_cleanup_log ORDER BY deleted_at DESC LIMIT 10;
```

## 🔍 Step 9: Verify Realtime Features

### 9.1 Test WebSocket Connection
```bash
# Install websocat or use browser
# Connect to: ws://localhost:8000/ws/job/test_job_123
```

### 9.2 Check Realtime in Dashboard
1. Go to **Database → Replication**
2. Verify realtime is enabled for:
   - `scraping_jobs`
   - `job_progress`
   - `user_sessions`

## 📈 Step 10: Performance Monitoring

### 10.1 Check Supabase Dashboard
- **API Usage**: Monitor request counts
- **Storage Usage**: Check file counts and storage size
- **Database Performance**: Look for slow queries
- **Realtime Messages**: Monitor message counts

### 10.2 Test Scalability
1. Create multiple jobs simultaneously
2. Upload several files at once
3. Monitor system performance

## 🚨 Troubleshooting

### Common Issues & Solutions

#### "Missing required Supabase environment variables"
- Check `.env` file exists and has correct values
- Verify Supabase credentials are valid

#### "Failed to create Supabase client"
- Check internet connection
- Verify Supabase project is active
- Check API keys are correct

#### "Bucket not found"
- Ensure storage bucket was created
- Check bucket name matches `STORAGE_BUCKET_NAME`

#### "Permission denied" errors
- Check storage policies are set up correctly
- Verify RLS policies in database schema

#### Bot not responding
- Check bot token is correct
- Verify webhook URL is accessible
- Check logs for errors

## ✅ Success Criteria

Your integration is working correctly if:

1. ✅ **Basic Test Passes**: `python basic_test.py` shows all tests passed
2. ✅ **Database Working**: Tables created and accessible
3. ✅ **Storage Working**: Files upload and download successfully
4. ✅ **Realtime Working**: Progress updates work
5. ✅ **Bot Working**: Telegram bot responds to commands
6. ✅ **API Working**: FastAPI endpoints return correct responses
7. ✅ **Auto-Delete Working**: Files are cleaned up automatically

## 🎉 Congratulations!

If all tests pass, your Loveworld Bot now has:
- ☁️ **Cloud Storage** with auto-deletion
- 🗄️ **Database** for persistent data
- ⚡ **Realtime** updates
- 🤖 **Enhanced Telegram Bot**
- 🚀 **Production-ready API**

Your bot is ready for deployment! 🚀