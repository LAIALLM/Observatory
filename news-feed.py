import os
import tweepy
import feedparser
import openai
import json
import time
from datetime import datetime, timedelta

# Load API keys from GitHub Secrets
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_SECRET = os.getenv("TWITTER_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Authenticate Twitter API
auth = tweepy.OAuthHandler(TWITTER_API_KEY, TWITTER_SECRET)
auth.set_access_token(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
api = tweepy.API(auth)

# Google News RSS Feeds
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=construction+industry&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=infrastructure&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=smart+city&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=new+city&hl=en-IN&gl=IN&ceid=IN:en",
]

# Log file to track already posted news
LOG_FILE = "posted_news.json"

# Load previously posted articles
def load_posted_articles():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as file:
            return json.load(file)
    return []

# Save posted articles
def save_posted_articles(posted):
    with open(LOG_FILE, "w") as file:
        json.dump(posted, file)

# Get latest news (only from the last hour)
def get_latest_news():
    news_list = []
    now = datetime.utcnow()

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            title = entry.title
            link = entry.link
            published_time = datetime(*entry.published_parsed[:6]) if "published_parsed" in entry else now
            source = entry.source.title if hasattr(entry, 'source') else "Unknown Source"
            summary = entry.summary if hasattr(entry, 'summary') else None

            # Only get news from the last 1 hour
            if now - published_time < timedelta(hours=1):
                news_list.append((title, link, source, summary))

    return news_list

# Summarize news using OpenAI (reinterpret title, add more details if available)
def summarize_news(title, summary, source):
    openai.api_key = OPENAI_API_KEY

    # Base prompt: reinterpret title
    prompt = f"Rephrase this construction-related news title into a more engaging tweet:\n\nTitle: {title}"

    # If additional summary is available, enrich it
    if summary:
        prompt += f"\n\nAlso, add one key point from this summary: {summary}"

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    
    ai_summary = response["choices"][0]["message"]["content"]
    tweet = f"{ai_summary}\nSource: {source}"
    
    return tweet[:280]  # Ensure tweet is within character limit

# Post to X (Twitter)
def post_tweet(tweet):
    try:
        api.update_status(tweet)
        print(f"✅ Posted: {tweet}")
        return True
    except tweepy.TweepError as e:
        print(f"❌ Error posting: {e}")
        return False

if __name__ == "__main__":
    posted_articles = load_posted_articles()
    latest_news = get_latest_news()

    for title, link, source, summary in latest_news:
        if link not in posted_articles:  # Avoid duplicate posting
            tweet = summarize_news(title, summary, source)
            if post_tweet(tweet):
                posted_articles.append(link)
                save_posted_articles(posted_articles)
            time.sleep(5)  # Avoid hitting rate limits

    print("🚀 Finished checking for news.")
