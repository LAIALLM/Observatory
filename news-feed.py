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

# Authenticate Twitter API (Using API v2)
twitter_client = tweepy.Client(
    consumer_key=TWITTER_API_KEY,
    consumer_secret=TWITTER_SECRET,
    access_token=TWITTER_ACCESS_TOKEN,
    access_token_secret=TWITTER_ACCESS_SECRET
)

# Google News + Industry-Specific RSS Feeds
RSS_FEEDS = [
    
    # Google News Feeds
    "https://news.google.com/rss/search?q=construction+industry&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=infrastructure&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=urban+development&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=smart+city&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=new+city+urban+development&hl=en-IN&gl=IN&ceid=IN:en",

    # Industry-Specific Construction & Infrastructure News Feeds
    "https://www.constructiondive.com/feeds/news/",  # Construction Dive
    "https://www.enr.com/rss/articles",  # Engineering News-Record (ENR)
    "https://www.archdaily.com/rss",  # ArchDaily (Architecture & Urbanism)
    "https://nextcity.org/feeds/features",  # Next City (Urban Planning & Development)
    "https://www.smartcitiesdive.com/feeds/news/",  # Smart Cities World (Tech & Development)
    "https://www.urbantransportnews.com/feed",  # Urban Transport News
    "https://infrastructuremagazine.com.au/feed/",  # Infrastructure Intelligence
]

# Log file to track posted and filtered news
LOG_FILE = "filtered_news.json"
RETENTION_DAYS = 10  # Remove news older than 10 days

# Load previously processed articles (both tweeted & filtered)
def load_filtered_articles():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as file:
            try:
                processed_data = json.load(file)
            except json.JSONDecodeError:
                print("⚠️ Error: `filtered_news.json` is corrupted. Resetting file.")
                processed_data = []  # Reset if JSON is corrupted

        # Remove old articles (older than retention period)
        cutoff_date = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
        return [entry for entry in processed_data if datetime.strptime(entry["date"], "%Y-%m-%d") > cutoff_date]
    
    return []

# Save processed articles incrementally to prevent overwriting the entire file
def save_processed_articles(processed):
    print("💾 Writing to filtered_news.json...")
    try:
        # Check if the file exists
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as file:
                current_data = json.load(file)
            # Append new entries to the current data
            current_data.extend(processed)
            processed = current_data
        
        with open(LOG_FILE, "w") as file:
            json.dump(processed, file, indent=4)
        print("✅ Successfully wrote to filtered_news.json!")
    except Exception as e:
        print(f"❌ Error writing to JSON: {e}")
        return  # Stop execution if writing fails

    # Ensure GitHub Actions commits & pushes changes
    if os.getenv("GITHUB_ACTIONS"):
        print("🔄 Committing changes to GitHub...")
        os.system("git config --global user.email 'github-actions@github.com'")
        os.system("git config --global user.name 'GitHub Actions'")
        os.system("git add filtered_news.json")
        commit_result = os.system("git commit -m 'Update filtered_news.json [Automated]'")
        
        if commit_result != 0:
            print("⚠️ No changes to commit. Skipping push.")
            return

        push_result = os.system("git push origin main")
        if push_result != 0:
            print("❌ Push failed, check GitHub Actions permissions.")
        else:
            print("✅ Changes committed to GitHub.")

# Get latest news (only from the last hour) with error handling
def get_latest_news():
    news_list = []
    now = datetime.utcnow()

    for feed_url in RSS_FEEDS:
        try:
            print(f"🔄 Fetching news from: {feed_url}")
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                print(f"⚠️ Warning: No news found in {feed_url}. It may be down.")
                continue

            for entry in feed.entries:
                title = entry.title
                link = entry.link
                published_time = datetime(*entry.published_parsed[:6]) if "published_parsed" in entry else now
                source = entry.source.title if hasattr(entry, 'source') else "Unknown Source"
                summary = entry.summary if hasattr(entry, 'summary') else None

                if now - published_time < timedelta(hours=1):
                    news_list.append((title, link, source, summary))
        except Exception as e:
            print(f"❌ Error fetching feed {feed_url}: {e}")
            continue
    return news_list

# Use GPT-4 to check if news is relevant
def get_news_relevance_score(title, summary):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
    You are ranking news articles for a construction industry Twitter feed.
    Assign a **relevance score (0-10)** based on its impact, factual data, importance, and timeliness.

    **Scoring Criteria:**
    - **9-10:** Major infrastructure projects, large-scale investments, confirmed government policies, or high-impact urban development. 
    - **7-8:** Medium-scale developments, emerging industry trends, detailed industry reports, corporate deals, or major tech innovations in construction.
    - **5-6:** Minor but relevant construction updates, small investments, or less significant projects.
    - **1-4:** Articles with vague, speculative, or unverified information.
    - **0:** DO NOT SCORE articles about:
      - Entertainment (sports events, matches, concerts, movies, celebrity real estate).
      - Political debates without specific infrastructure or urban development plans.
      - Speculative reports or opinions without confirmed policies, contracts, or investments.

    **Reply only with a single integer between 0-10.**

    **Article:**
    Title: {title}
    Summary: {summary}
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    score_text = response.choices[0].message.content.strip()

    try:
        score = int(score_text)
        return score if 0 <= score <= 10 else 0  # Ensure valid range
    except ValueError:
        return 0  # Default to 0 if unexpected response


    except openai.OpenAIError as e:
        print(f"❌ OpenAI API Error: {e}")
        return 0  # Default to 0 if API call fails


# Extract company name dynamically using GPT-4
def extract_company_name(title, summary):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
    Identify the primary company mentioned in the following news.
    If no company is mentioned, reply exactly with 'None'.

    Title: {title}
    Summary: {summary}
    """
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    
    company_name = response.choices[0].message.content.strip()

    # Ensure consistent checking for "None" in various cases
    return None if company_name.lower() == "none" else company_name


# Extract stock ticker symbol using GPT-4
def get_stock_ticker(company_name):
    if not company_name:
        return None  # Skip API call if no company is detected
    
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    # Define the prompt as a raw string (to prevent formatting issues)
    prompt = (
        f"Identify if the company '{company_name}' is publicly traded and provide its stock ticker.\n"
        "- Use '$' for all stock symbols for Twitter compatibility.\n"
        "- If the company is private or does not have a stock ticker, reply exactly with 'None'.\n\n"
        f"Company: {company_name}"
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    stock_ticker = response.choices[0].message.content.strip()

    # Ensure consistent checking for "None"
    return None if stock_ticker.lower() == "none" else stock_ticker


# Summarize news and format tweet
def summarize_news(title, summary, source):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
    Rewrite this construction-related news title into a concise, professional tweet.
    - Do NOT include quotes.
    - Do NOT use hashtags.
    - Keep it engaging and natural.
    - If a country is mentioned, add its correct flag emoji at the start.
    - Do NOT use a globe emoji or flag for global terms like "world" or "global.
    - DO NOT include the source or website name.

    Title: {title}
    """

    if summary:
        prompt += f"\n\nAlso, integrate one key point from this summary: {summary}"

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    ai_summary = response.choices[0].message.content.strip()
    ai_summary = ai_summary.replace('"', '').replace("'", "")

    tweet = f"{ai_summary}" # \n\nSource: {source}
    return tweet[:280]

# Post to X (Twitter) using API v2 with a delay
def post_tweet(tweet):
    print(f"🚀 Attempting to tweet: {tweet}")  # Debugging line
    try:
        response = twitter_client.create_tweet(text=tweet)
        print(f"✅ Tweet posted successfully: {response.data}")

        # Introduce a 3-minute delay **after** posting each tweet
        print("⏳ Waiting 3 minutes before posting the next tweet...")
        time.sleep(90)  # 90 seconds (1.5 minutes)

        return True
    except tweepy.errors.Forbidden as e:
        if "Status is a duplicate" in str(e):
            print("⚠️ Duplicate Tweet detected. Skipping.")
        else:
            print(f"❌ Twitter API error: {e}")
        return False
    except tweepy.errors.TweepyException as e:
        print(f"❌ Other Tweepy error: {e}")
        return False

if __name__ == "__main__":
    print("🔍 Loading previously processed articles...")
    processed_articles = load_filtered_articles()
    filtered_links = {article["link"] for article in processed_articles}  # ✅ Track both posted & filtered links
    print(f"📂 {len(processed_articles)} articles already processed.")

    latest_news = get_latest_news()
    print(f"📰 Found {len(latest_news)} new articles.")

    scored_news = []

    for title, link, source, summary in latest_news:
        if link in filtered_links:
            print(f"⏩ Skipping already processed article: {title}")
            continue

        score = get_news_relevance_score(title, summary)

        if score > 7:  # ✅ Ignore irrelevant articles (scored 7)
            scored_news.append((score, title, link, source, summary))

    # 🔹 Sort articles by highest relevance score
    scored_news.sort(reverse=True, key=lambda x: x[0])  

    top_articles = scored_news[:3]  # 🔹 Pick top 3 highest-ranked news articles

    new_entries = []

    for score, title, link, source, summary in top_articles:
        tweet = summarize_news(title, summary, source)

        if post_tweet(tweet):  # ✅ Only tweet top-ranked articles
            new_entry = {
                "link": link,
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "status": "posted",
                "score": score,
                "tweet": tweet
            }
            processed_articles.append(new_entry)
            new_entries.append(new_entry)

    if new_entries:
        save_processed_articles(processed_articles)
        print("✅ `filtered_news.json` updated successfully!")
    else:
        print("⚠️ No highly relevant news. Skipping JSON update.")


