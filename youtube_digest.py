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
return " ".join([t.text for t in transcript_list])
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception as e:
        print(f"    Transcript error for {video_id}: {e}")
        return None


def summarize_video(client, video):
    """Use Claude to produce a finance-focused summary with sentiment rating."""
    transcript = get_transcript(video["id"])
    if not transcript:
        return None

    # Truncate very long transcripts to stay within token limits
    max_chars = 30000
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "... [transcript truncated]"

    prompt = f"""You are a financial analyst summarizing a YouTube video for an investor's daily digest.

Video: "{video['title']}" by {video['channel']}
URL: {video['url']}

Transcript:
{transcript}

Provide a structured summary in exactly this format — use these exact section headers:

ONE-LINE SUMMARY
One sentence describing what this video is about.

KEY TAKEAWAYS
- 3 to 5 bullet points covering the most important insights and arguments made

ACTIONABLE ITEMS
- 2 to 4 specific actions an investor could take based on this video

ASSETS & TOPICS MENTIONED
- List the key assets, sectors, or macro topics discussed (e.g. ETH, Oil, S&P500, Fed rates)

SENTIMENT RATING
Rate the overall market sentiment expressed in this video on this exact scale:
Strongly Bearish | Bearish | Neutral | Bullish | Strongly Bullish
Then write one sentence explaining why.

Be concise and direct. Focus on what is most actionable for an investor."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def get_sentiment_emoji(summary_text):
    """Extract sentiment from summary and return emoji + color."""
    text = summary_text.upper()
    if "STRONGLY BULLISH" in text:
        return "🟢🟢", "Strongly Bullish", "#14532d", "#dcfce7"
    elif "STRONGLY BEARISH" in text:
        return "🔴🔴", "Strongly Bearish", "#7f1d1d", "#fee2e2"
    elif "BULLISH" in text:
        return "🟢", "Bullish", "#166534", "#f0fdf4"
    elif "BEARISH" in text:
        return "🔴", "Bearish", "#991b1b", "#fff1f2"
    else:
        return "🟡", "Neutral", "#854d0e", "#fefce8"


def generate_market_analysis(client, summaries):
    """Use Claude to produce full trend analysis, consensus and top investor actions."""
    if len(summaries) < 2:
        return None

    summaries_text = "\n\n---\n\n".join([
        f"Video: {s['title']} ({s['channel']})\n{s['summary']}"
        for s in summaries
    ])

    prompt = f"""You are a senior financial analyst. Below are summaries of {len(summaries)} finance/investing YouTube videos published today.

{summaries_text}

Produce a market intelligence report in exactly this format — use these exact section headers:

TRENDING THEMES
Identify 3 to 5 themes or narratives gaining momentum across today's videos. For each, name the theme and explain how it appeared across multiple videos.

OVERALL MARKET CONSENSUS
Based on all videos combined, what is the overall market sentiment today? 
State: Strongly Bearish | Bearish | Neutral | Bullish | Strongly Bullish
Then write 2 to 3 sentences explaining the key factors driving this consensus.

TOP INVESTOR ACTION ITEMS
List the 5 most important actionable steps an investor should consider today based on everything covered across all videos. Be specific and direct.

Be concise, analytical, and focused on what matters most for an investor."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def format_summary_html(summary_text):
    """Convert plain text summary sections into clean HTML."""
    if not summary_text:
        return ""

    html = ""
    lines = summary_text.strip().split("\n")
    in_list = False

    section_styles = {
        "ONE-LINE SUMMARY": ("📌", "#1e3a5f"),
        "KEY TAKEAWAYS": ("💡", "#1e3a5f"),
        "ACTIONABLE ITEMS": ("⚡", "#1e3a5f"),
        "ASSETS & TOPICS MENTIONED": ("📊", "#1e3a5f"),
        "SENTIMENT RATING": ("🎯", "#1e3a5f"),
        "TRENDING THEMES": ("📈", "#1e3a5f"),
        "OVERALL MARKET CONSENSUS": ("🌐", "#1e3a5f"),
        "TOP INVESTOR ACTION ITEMS": ("✅", "#1e3a5f"),
    }

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html += "</ul>"
                in_list = False
            continue

        matched_section = None
        for section, (emoji, color) in section_styles.items():
            if stripped.upper().startswith(section):
                matched_section = (section, emoji, color)
                break

        if matched_section:
            if in_list:
                html += "</ul>"
                in_list = False
            _, emoji, color = matched_section
            html += f'<p style="margin:16px 0 6px 0; font-weight:bold; font-size:13px; color:{color}; text-transform:uppercase; letter-spacing:0.5px;">{emoji} {stripped}</p>'
        elif stripped.startswith("- ") or stripped.startswith("• "):
            if not in_list:
                html += '<ul style="margin:4px 0 4px 20px; padding:0;">'
                in_list = True
            html += f'<li style="margin:4px 0; font-size:14px; color:#333; line-height:1.6;">{stripped[2:]}</li>'
        else:
            if in_list:
                html += "</ul>"
                in_list = False
            html += f'<p style="margin:4px 0; font-size:14px; color:#333; line-height:1.6;">{stripped}</p>'

    if in_list:
        html += "</ul>"

    return html


def build_email_html(summaries, market_analysis, date_str):
    """Build the full HTML email digest."""

    # Build sentiment scoreboard
    scoreboard_html = ""
    for s in summaries:
        emoji, label, text_color, bg_color = get_sentiment_emoji(s["summary"])
        scoreboard_html += f"""
        <tr>
            <td style="padding:8px 12px; font-size:13px; color:#333; border-bottom:1px solid #eee;">
                <a href="{s['url']}" style="color:#1a56db; text-decoration:none;">{s['title'][:65]}{'...' if len(s['title']) > 65 else ''}</a>
                <span style="color:#888; font-size:12px;"> — {s['channel']}</span>
            </td>
            <td style="padding:8px 12px; text-align:center; border-bottom:1px solid #eee;">
                <span style="background:{bg_color}; color:{text_color}; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:bold; white-space:nowrap;">
                    {emoji} {label}
                </span>
            </td>
        </tr>"""

    # Build individual video summaries
    videos_html = ""
    for s in summaries:
        emoji, label, text_color, bg_color = get_sentiment_emoji(s["summary"])
        formatted = format_summary_html(s["summary"])
        videos_html += f"""
        <div style="margin-bottom:28px; border:1px solid #e5e7eb; border-radius:8px; overflow:hidden;">
            <div style="background:#1e3a5f; padding:16px 20px;">
                <h3 style="margin:0 0 4px 0; font-size:15px; color:#ffffff;">
                    <a href="{s['url']}" style="color:#ffffff; text-decoration:none;">{s['title']}</a>
                </h3>
                <p style="margin:0; color:#93c5fd; font-size:12px;">{s['channel']} · {s['published']}</p>
            </div>
            <div style="padding:16px 20px; background:#ffffff;">
                {formatted}
            </div>
        </div>"""

    # Build market analysis section
    analysis_html = ""
    if market_analysis:
        formatted_analysis = format_summary_html(market_analysis)
        analysis_html = f"""
        <div style="margin-bottom:32px; border:2px solid #1e3a5f; border-radius:8px; overflow:hidden;">
            <div style="background:#1e3a5f; padding:16px 20px;">
                <h2 style="margin:0; font-size:17px; color:#ffffff;">📊 Market Intelligence Report</h2>
                <p style="margin:4px 0 0 0; color:#93c5fd; font-size:12px;">Cross-video trend analysis · {date_str}</p>
            </div>
            <div style="padding:20px; background:#f8faff;">
                {formatted_analysis}
            </div>
        </div>"""

    return f"""
    <html>
    <body style="font-family:Arial,sans-serif; max-width:700px; margin:0 auto; padding:24px; background:#f3f4f6; color:#333;">

        <!-- Header -->
        <div style="background:#1e3a5f; border-radius:10px 10px 0 0; padding:28px 28px 20px 28px; margin-bottom:0;">
            <h1 style="margin:0 0 4px 0; font-size:22px; color:#ffffff;">📺 Finance & Investing Digest</h1>
            <p style="margin:0; color:#93c5fd; font-size:14px;">{date_str} · {len(summaries)} video{'s' if len(summaries) != 1 else ''} summarized</p>
        </div>

        <!-- Sentiment Scoreboard -->
        <div style="background:#ffffff; margin-bottom:24px; border-radius:0 0 10px 10px; padding:20px 24px; border:1px solid #e5e7eb; border-top:none;">
            <h2 style="margin:0 0 14px 0; font-size:15px; color:#1e3a5f; text-transform:uppercase; letter-spacing:0.5px;">🎯 Sentiment Scoreboard</h2>
            <table style="width:100%; border-collapse:collapse;">
                {scoreboard_html}
            </table>
        </div>

        <!-- Market Intelligence Report -->
        {analysis_html}

        <!-- Video Summaries -->
        <h2 style="font-size:16px; color:#1e3a5f; margin:0 0 16px 0; text-transform:uppercase; letter-spacing:0.5px;">📝 Video Summaries</h2>
        {videos_html}

        <!-- Footer -->
        <p style="color:#aaa; font-size:11px; text-align:center; margin-top:32px; padding-top:16px; border-top:1px solid #e5e7eb;">
            Generated automatically by your YouTube Digest · Powered by Claude
        </p>

    </body>
    </html>"""


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

    market_analysis = None
    if len(summaries) >= 2:
        print("\n📊 Generating market intelligence report...")
        market_analysis = generate_market_analysis(client, summaries)

    date_str = datetime.now().strftime("%B %d, %Y")
    subject = f"📺 Finance Digest — {date_str} ({len(summaries)} new videos)"
    html_body = build_email_html(summaries, market_analysis, date_str)

    print(f"\n📧 Sending digest to {EMAIL_RECIPIENT}...")
    send_email(EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT, subject, html_body)

    state["processed"] = list(processed_ids)[-500:]
    save_state(state)

    print(f"✅ Done! Digest sent with {len(summaries)} video(s).")


if __name__ == "__main__":
    main()
