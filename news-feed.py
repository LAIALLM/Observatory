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

# Save posted articles (ensuring correct update & GitHub push)
def save_posted_articles(posted):
    print("💾 Writing to filtered_news.json...")
    try:
        with open(LOG_FILE, "w") as file:
            json.dump(posted, file, indent=4)
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

            # Check if the feed is empty or has an error
            if not feed.entries:
                print(f"⚠️ Warning: No news found in {feed_url}. It may be down.")
                continue  # Skip this feed and move to the next

            for entry in feed.entries:
                title = entry.title
                link = entry.link
                published_time = datetime(*entry.published_parsed[:6]) if "published_parsed" in entry else now
                source = entry.source.title if hasattr(entry, 'source') else "Unknown Source"
                summary = entry.summary if hasattr(entry, 'summary') else None

                # Only get news from the last 1 hour
                if now - published_time < timedelta(hours=1):
                    news_list.append((title, link, source, summary))

        except Exception as e:
            print(f"❌ Error fetching feed {feed_url}: {e}")
            continue  # Skip this feed and try the next one

    return news_list

# Use GPT-4 to check if news is relevant
def is_relevant_news(title, summary):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
    The following news headline and summary have been found in an RSS feed. 
    Decide whether this article is relevant to the construction industry, infrastructure, smart cities, or urban development.

    **Prioritize articles that contain:**
    - **Concrete data** such as investment amounts, budgets, project costs, area size, completion timelines, or workforce numbers.
    - **Government policies or financial decisions** that specify funding amounts or regulatory changes impacting infrastructure or smart cities.
    - **Industry trends with measurable insights**, such as reports on market growth, sustainability metrics, or technological advancements with evidence.
    - **Confirmed urban development projects**, rather than speculative or proposed ideas without action.

    **Include valuable articles even if they lack numerical data, IF they:**
    - Provide **detailed descriptions of new construction, city planning, or infrastructure projects**.
    - Discuss **key policies, regulations, or contracts signed** that will directly impact urban development.
    - Offer **expert insights from reputable industry leaders, analysts, or research institutions**.

    **Exclude articles that are:**
    - Overly vague with no specific details or measurable impact.
    - Only about sports events, matches, or results.
    - Focused solely on entertainment (e.g., concerts, movies, celebrity real estate).
    - Political debates that do not involve specific infrastructure or urban development plans.
    - Speculative reports or opinions that have no confirmed policy or investment.

    **If the article is valuable and industry-relevant, reply with 'YES'. If it is not relevant, reply with 'NO'.**
    
    Title: {title}
    
    Summary: {summary}
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    decision = response.choices[0].message.content.strip().upper()


    # Ensure valid response (default to NO if unexpected output)
    if decision not in ["YES", "NO"]:
        print(f"⚠️ Unexpected GPT-4 response: {decision}. Defaulting to NO.")
        return False
        
    return decision == "YES"

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

# Post to X (Twitter) using API v2
def post_tweet(tweet):
    try:
        response = twitter_client.create_tweet(text=tweet)
        print(f"✅ Tweet posted successfully: {response.data}")
        return True
    except tweepy.errors.Forbidden as e:
        print(f"❌ Twitter API error: {e}")
        print("⚠️ Check your API access level: https://developer.x.com/en/portal/dashboard")
        return False
    except tweepy.errors.TweepyException as e:
        print(f"❌ Other Tweepy error: {e}")
        return False

if __name__ == "__main__":
    print("🔍 Loading previously processed articles...")
    processed_articles = load_filtered_articles()  # ✅ Load all processed articles
    filtered_links = {article["link"] for article in processed_articles}  # ✅ Define filtered_links properly
    print(f"📂 {len(processed_articles)} articles already processed.")

    latest_news = get_latest_news()
    print(f"📰 Found {len(latest_news)} new articles.")

    new_entries = []
    new_tweets = False  # Track if any new tweets were posted

    for title, link, source, summary in latest_news:
        if link in filtered_links:  # ✅ Prevent duplicate processing (includes both posted & filtered)
            print(f"⏩ Skipping already processed article: {title}")
            continue

        is_relevant = is_relevant_news(title, summary)
        status = "posted" if is_relevant else "filtered"

        if is_relevant:
            print(f"🆕 Relevant article found: {title}")
            tweet = summarize_news(title, summary, source)
            if post_tweet(tweet):
                new_entry = {
                    "link": link,
                    "date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "tweet": tweet,
                    "status": status
                }
                posted_articles.append(new_entry)
                posted_links.add(link)
                new_entries.append(new_entry)  # ✅ Track new posted tweets
                new_tweets = True
            else:
                print("❌ Tweet failed, skipping JSON update for this article.")
        else:
            print(f"🚫 Article filtered: {title}")
            new_entry = {
                "link": link,
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "status": status
            }
            posted_articles.append(new_entry)
            new_entries.append(new_entry)  # ✅ Track new filtered articles

    # ✅ Now properly updating the JSON with new articles
    if new_tweets or new_entries:
        print("💾 Saving updated articles to filtered_news.json...")
        save_posted_articles(posted_articles)
        print("✅ `filtered_news.json` updated successfully!")
    else:
        print("⚠️ No new relevant news. Skipping JSON update.")

