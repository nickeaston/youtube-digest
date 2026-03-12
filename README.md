# YouTube Daily Digest — Setup Guide

A script that monitors your YouTube subscriptions, summarizes new videos with Claude, and emails you a daily digest.

---

## 1. Install Python dependencies

```bash
pip install anthropic feedparser youtube-transcript-api
```

---

## 2. Get your API keys

### Anthropic API Key
1. Go to https://console.anthropic.com
2. Click **API Keys** → **Create Key**
3. Copy it into `youtube_digest.py` → `ANTHROPIC_API_KEY`

### Gmail App Password (for sending email)
You need an **App Password**, NOT your regular Gmail password.
1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** if not already on
3. Search for "App passwords" → Create one for "Mail"
4. Copy the 16-character password into `youtube_digest.py` → `EMAIL_PASSWORD`

---

## 3. Add your YouTube channel IDs

Edit the `CHANNELS` dict in `youtube_digest.py`:

```python
CHANNELS = {
    "Lex Fridman": "UCSHZKyawb77ixDdsGog4iWA",
    "My Favorite Channel": "UCxxxxxxxxxxxxxxxxxxxxxx",
}
```

### How to find a channel ID:
1. Go to the YouTube channel page
2. Right-click anywhere → **View Page Source**
3. Press Ctrl+F and search for `"channelId"`
4. Copy the value (starts with `UC...`)

**OR** use https://commentpicker.com/youtube-channel-id.php — paste the channel URL and it gives you the ID instantly.

---

## 4. Run manually

```bash
python youtube_digest.py
```

---

## 5. Schedule it to run daily (pick your OS)

### Mac — using cron
Run this in Terminal to open your cron schedule:
```bash
crontab -e
```
Add this line to run every day at 7:00 AM:
```
0 7 * * * /usr/bin/python3 /path/to/youtube_digest/youtube_digest.py >> /path/to/youtube_digest/digest.log 2>&1
```

### Windows — using Task Scheduler
1. Open **Task Scheduler** → Create Basic Task
2. Set trigger: **Daily** at your preferred time
3. Action: **Start a program**
   - Program: `python`
   - Arguments: `C:\path\to\youtube_digest\youtube_digest.py`

---

## How it works

1. Reads each channel's public RSS feed (no YouTube API key needed)
2. Detects videos published in the last 24 hours not yet processed
3. Fetches the auto-generated transcript from YouTube
4. Sends transcript to Claude for summarization (key takeaways + action items)
5. Identifies common themes across all videos
6. Sends a formatted HTML email digest to you

## Notes
- Videos without transcripts (some live streams, foreign language) are skipped
- Processed video IDs are saved in `processed_videos.json` so you never get duplicates
- The script keeps the last 500 processed IDs to avoid the file growing indefinitely
