#!/usr/bin/env python3
"""
YouTube Daily Digest
Monitors your subscribed YouTube channels via RSS, fetches transcripts
for new videos, summarizes them with Claude, and emails you a daily digest.
"""

import os
import json
import smtplib
import feedparser
import anthropic
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# ─────────────────────────────────────────────
# CONFIGURATION — edit this section
# ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get ("ANTHROPIC_API_KEY")

EMAIL_SENDER    = os.environ.get ("GMAIL_SENDER")
EMAIL_PASSWORD  = os.environ.get ("GMAIL_PASSWORD")   # Use a Gmail App Password, not your real password
EMAIL_RECIPIENT = os.environ.get ("EMAIL_RECIPIENT")
SMTP_SERVER     = "smtp.gmail.com"
SMTP_PORT       = 587

# How many hours back to look for new videos (24 = past day)
LOOKBACK_HOURS = 24

# File to track already-processed video IDs
STATE_FILE = "processed_videos.json"

# Your subscribed channels — add as many as you like
# Format: "Channel Name": "CHANNEL_ID"
# Find a channel ID: go to the channel page, right-click → View Page Source → search for "channelId"
CHANNELS = {
    "Anthony Pompliano": "UCevXpeL8cNyAnww-NqJ4m2w",
    "Jordi Visser": "UCSLOw8JrFTBb3qF-p4v0v_w",
    "The Defi Report": "UCGQqZBVIFO8agRSJ1gQCMKw",
    "Bankless": "UCAl9Ld79qaZxp9JzEOwd3aA",
    "Altcoin Daily ": "UCbLhGKVY-bJPcawebgtNfbw",
    "Limitless Podcast": "UCCRxYlYOmLE2l5wxs3ckJtg",
    "From the Desk of Anthony Pompliano": "UCML9PlpcOxM_H53IM0fa4XA",
    "The Bitcoin Layer": "UCDo6-SUypaXlTmH6AyrYBZA",
    "Benjamin Cowen": "UCRvqjQPSeaWn-uEx-w0XOIg",
    "Productive Dude": "UC3LCokV1C_1HGI4W5rftmvQ",
    "Real Vision": "UCGXWKlq1Oxr3ddEtmKhAkPg",
    "ElioTrades": "UCMtJYS0PrtiUwlk6zjGDEMA",
    "Peter H. Diamandis": "UCvxm0qTrGN_1LMYgUaftWyQ",
    "Raoul Pal The Journey Man": "UCVFSzL3VuZKP3cN9IXdLOtw",
    "Coin Bureau": "UCqK_GSMbpiV8spgD3ZGloSw",
    "Bob Loukas": "UC0zGwzu0zzCImC1BwPuWyXQ",
    "Daniel LAcalle": "UCLOgSB3-pjMInbDq_kWotsA",
    "Colin Talks Crypto": "UCnqJ2HjWhm7MbhgFHLUENfQ",
    "Krown": "UCnwxzpFzZNtLH8NgTeAROFA",
    "Macro Voices": "UCICRehoZjq3ZtAWgRJX118A",
    "All-in-podcast": "UCESLZhusAkFfsNsApnjF_Cg",
    "Forward Guidance ": "UCkrwgzhIBKccuDsi_SvZtnQ",
    "Bell Curve": "UC9aOLLMQht_1FKRxbQe60NA",
}
# ─────────────────────────────────────────────


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_new_videos(channels, lookback_hours, processed_ids):
    """Fetch new videos from each channel's RSS feed."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    new_videos = []

    for channel_name, channel_id in channels.items():
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            video_id = entry.yt_videoid if hasattr(entry, "yt_videoid") else None
            if not video_id or video_id in processed_ids:
                continue

            published = entry.get("published_parsed")
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue

            new_videos.append({
                "id": video_id,
                "title": entry.get("title", "Untitled"),
                "channel": channel_name,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published": entry.get("published", "Unknown date"),
            })
            print(f"  ✓ Found: [{channel_name}] {entry.get('title', 'Untitled')}")

    return new_videos


def get_transcript(video_id):
    """Fetch the transcript for a YouTube video."""
    try:
       ytt = YouTubeTranscriptApi()
transcript_list = ytt.fetch(video_id)
        return " ".join([t["text"] for t in transcript_list])
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception as e:
        print(f"    Transcript error for {video_id}: {e}")
        return None


def summarize_video(client, video):
    """Use Claude to summarize a single video transcript."""
    transcript = get_transcript(video["id"])
    if not transcript:
        return None

    # Truncate very long transcripts to stay within token limits
    max_chars = 30000
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "... [transcript truncated]"

    prompt = f"""You are summarizing a YouTube video for a busy professional.

Video: "{video['title']}" by {video['channel']}
URL: {video['url']}

Transcript:
{transcript}

Please provide:
1. **One-line summary** (1 sentence, what this video is about)
2. **Key Takeaways** (3–5 bullet points, the most important insights)
3. **Actionable Items** (2–4 specific things the viewer could do based on this video)
4. **Notable Quotes or Stats** (1–2 standout lines from the video, if any)

Be concise. Focus on what's most useful and actionable."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def find_common_themes(client, summaries):
    """Use Claude to identify themes across all videos in the digest."""
    if len(summaries) < 2:
        return None

    summaries_text = "\n\n---\n\n".join([
        f"Video: {s['title']} ({s['channel']})\n{s['summary']}"
        for s in summaries
    ])

    prompt = f"""Here are summaries of {len(summaries)} YouTube videos watched today:

{summaries_text}

Identify 2–4 common themes, patterns, or recurring ideas across these videos.
For each theme, name it and explain briefly how it shows up across the videos.
Be concise — this is a quick overview section in a daily digest email."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def build_email_html(summaries, themes, date_str):
    """Build a clean HTML email digest."""
    videos_html = ""
    for s in summaries:
        videos_html += f"""
        <div style="margin-bottom:32px; padding:20px; background:#f9f9f9; border-left:4px solid #e00; border-radius:4px;">
            <h3 style="margin:0 0 4px 0; font-size:16px;">
                <a href="{s['url']}" style="color:#c00; text-decoration:none;">{s['title']}</a>
            </h3>
            <p style="margin:0 0 12px 0; color:#888; font-size:13px;">{s['channel']} · {s['published']}</p>
            <div style="font-size:14px; line-height:1.7; color:#333;">
                {s['summary'].replace(chr(10), '<br>')}
            </div>
        </div>"""

    themes_html = ""
    if themes:
        themes_html = f"""
        <div style="margin-bottom:32px; padding:20px; background:#fff8e1; border-left:4px solid #f5a623; border-radius:4px;">
            <h2 style="margin:0 0 12px 0; font-size:18px; color:#333;">🔗 Common Themes Today</h2>
            <div style="font-size:14px; line-height:1.7; color:#333;">
                {themes.replace(chr(10), '<br>')}
            </div>
        </div>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif; max-width:680px; margin:0 auto; padding:24px; color:#333;">
        <h1 style="font-size:22px; border-bottom:2px solid #e00; padding-bottom:10px;">
            📺 Your YouTube Digest — {date_str}
        </h1>
        <p style="color:#666; font-size:14px;">{len(summaries)} new video(s) summarized from your subscriptions.</p>
        {themes_html}
        <h2 style="font-size:18px; margin-top:28px;">📝 Video Summaries</h2>
        {videos_html}
        <p style="color:#aaa; font-size:12px; margin-top:40px;">
            Generated automatically by your YouTube Digest script.
        </p>
    </body></html>"""


def send_email(sender, password, recipient, subject, html_body):
    """Send the digest email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())


def main():
    print(f"\n{'='*50}")
    print(f"YouTube Digest — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    state = load_state()
    processed_ids = set(state.get("processed", []))

    print(f"\n📡 Checking {len(CHANNELS)} channels for new videos (last {LOOKBACK_HOURS}h)...")
    new_videos = get_new_videos(CHANNELS, LOOKBACK_HOURS, processed_ids)

    if not new_videos:
        print("✅ No new videos found. Nothing to send.")
        return

    print(f"\n📝 Summarizing {len(new_videos)} video(s) with Claude...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    summaries = []

    for video in new_videos:
        print(f"  → {video['title'][:60]}...")
        summary_text = summarize_video(client, video)
        if summary_text:
            summaries.append({**video, "summary": summary_text})
            processed_ids.add(video["id"])
        else:
            print(f"    ⚠️  No transcript available, skipping.")

    if not summaries:
        print("⚠️  No transcripts were available for any new videos.")
        return

    themes = None
    if len(summaries) >= 2:
        print("\n🔗 Finding common themes across videos...")
        themes = find_common_themes(client, summaries)

    date_str = datetime.now().strftime("%B %d, %Y")
    subject = f"📺 YouTube Digest — {date_str} ({len(summaries)} new videos)"
    html_body = build_email_html(summaries, themes, date_str)

    print(f"\n📧 Sending digest to {EMAIL_RECIPIENT}...")
    send_email(EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT, subject, html_body)

    state["processed"] = list(processed_ids)[-500:]  # Keep last 500 IDs max
    save_state(state)

    print(f"✅ Done! Digest sent with {len(summaries)} video(s).")


if __name__ == "__main__":
    main()
