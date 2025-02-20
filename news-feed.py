import os
import tweepy
import feedparser
import re
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
TWEET_THRESHOLD = 10 # Define score threshold for tweets

# Measures for statistical tweets
STAT_TWEETS_LIMIT = 3  # Max statistical tweets per day
FAILED_RUNS_THRESHOLD = 3  # Trigger if 3 runs fail to post news

# Define common words to ignore (stopwords)
STOPWORDS = set([
    "the", "and", "is", "in", "on", "at", "to", "of", "for", "with", "a", "an",
    "this", "that", "from", "by", "as", "it", "its", "was", "were", "are", "be", "new", "latest"
])

# Function to extract important words & numbers
def extract_key_terms(text):
    text = text.lower()
    words = re.findall(r'\b\w+\b', text)  # Extract words
    numbers = re.findall(r'\d+', text)  # Extract numbers
    keywords = [word for word in words if word not in STOPWORDS] + numbers
    return set(keywords)

def is_similar_news(new_title, new_summary, processed_articles, threshold=0.5, limit=30): # threshold 0 is easy, threshold 1 is strict
 
    new_keywords = extract_key_terms(new_title) | extract_key_terms(new_summary)

    # ✅ Filter only the last limit articles that have a high score (≥ TWEET_THRESHOLD)
    recent_articles = [article for article in processed_articles if article.get("score", 0) >= TWEET_THRESHOLD][-limit:]

    for article in recent_articles:
        # Extract previous article's title and summary (instead of just the tweet)
        old_keywords = extract_key_terms(article.get("tweet", "")) | extract_key_terms(article.get("title", "")) | extract_key_terms(article.get("summary", ""))

        if old_keywords:
            # Compute Jaccard similarity (shared words / total words)
            similarity = len(new_keywords & old_keywords) / len(new_keywords | old_keywords)
            if similarity >= threshold:
                print(f"⚠️ Skipping similar news: {new_title} (Similarity: {similarity:.2f})")
                return True  # Found a similar article

    return False  # No duplicates found

# Load previously processed articles (both tweeted & filtered)
def load_filtered_articles():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as file:
                # Try loading the existing JSON data
                processed_data = json.load(file)
                print(f"Loaded {len(processed_data)} previously processed articles.")
        except json.JSONDecodeError:
            # Handle corrupted JSON file gracefully by clearing it
            print("⚠️ Corrupted JSON file. Resetting to an empty list.")
            processed_data = []
    else:
        processed_data = []
    
    # Return the entire list of previously processed articles
    return processed_data

# Remove articles older than RETENTION_DAYS to prevent JSON file growth.
def cleanup_old_articles(processed_articles):
    cutoff_date = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    return [article for article in processed_articles if datetime.strptime(article["date"], "%Y-%m-%d") >= cutoff_date]

# Save processed articles (ensuring correct update & GitHub push)
def save_processed_articles(processed):
    print("💾 Writing to filtered_news.json...")
    try:
        # Always write the entire list, including both new and previously processed entries
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

# Count consecutive runs that didn't post any tweets."
def count_failed_runs(processed_articles):
    failed_runs = 0
    for article in reversed(processed_articles[-FAILED_RUNS_THRESHOLD:]):
        if article.get("status") == "posted":
            return 0  # Reset counter if any tweet was posted
        failed_runs += 1
    return failed_runs

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
                summary = entry.summary if hasattr(entry, 'summary') and entry.summary else ""

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
    
    - **Substract 1 point** for articles that do not contain **concrete data** or **confirmed urban development projects**.
    
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

# Summarize news and format tweet
def summarize_news(title, summary, source):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
    Rewrite this construction-related news title into a concise, professional tweet.
    - Keep it engaging and natural.
    - No quotes, hashtags, sources, or websites.
    - Add a flag emoji at the start **only if** a country, city, or company is explicitly mentioned.
    - **Only add a stock ticker $TICKER if:**
      1. The company is **publicly traded**.
      2. The **correct** ticker symbol is available.

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

# Generate statistical tweet

def generate_statistical_tweet(processed_articles):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    # ✅ Use already loaded processed_articles instead of reloading JSON
    past_tweets = {article["tweet"] for article in processed_articles if article.get("type") == "statistical"}

    prompt = """
    Provide a compelling tweet about statistical facts regarding infrastructure projects, population, urban developments, and cities around the world.
    When possible, make a rank of the top 10 countries or cities as a numbered list and add their respective flags before mentioning each country or city.
    Keep the tweet under 280 characters.
    """

    for _ in range(3):  # Try up to 3 times to avoid duplicates
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        tweet = response.choices[0].message.content.strip()

        if tweet not in past_tweets:
            return tweet

    return None  # If all 3 attempts return repeated content


# Post to X (Twitter) using API v2 with a delay
def post_tweet(tweet):
    print(f"🚀 Attempting to tweet: {tweet}")  # Debugging line
    try:
        response = twitter_client.create_tweet(text=tweet)
        print(f"✅ Tweet posted successfully: {response.data}")

        # Introduce a 3-minute delay **after** posting each tweet
        print("⏳ Waiting 3 minutes before posting the next tweet...")
        time.sleep(120)  # 120 seconds 

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


############## Main execution starts here ##############
if __name__ == "__main__":
    print("🔍 Loading previously processed articles...")
    processed_articles = load_filtered_articles()
    filtered_links = {article["link"] for article in processed_articles} if len(processed_articles) > 0 else set()
    print(f"📂 {len(processed_articles)} articles already processed.")

    latest_news = get_latest_news()
    print(f"📰 Found {len(latest_news)} new articles.")

    scored_news = []

    for title, link, source, summary in latest_news:
        if link in filtered_links:
            print(f"⏩ Skipping already processed article: {title}")
            continue

        # ✅ Check for similarity first
        similar = is_similar_news(title, summary, processed_articles, threshold=0.5, limit=30)

        # ✅ If similar, store and skip further processing
        if similar:
            article_entry = {
                "link": link,
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "title": title,
                "summary": summary,
                "similarity_excluded": "Yes",
                "score": None,  # ✅ No GPT-4 scoring for similar articles
                "status": "skipped",
                "tweet": None
            }
            processed_articles.append(article_entry)
            continue  # 🚨 Skip scoring and tweet generation

        # ✅ If NOT similar, continue processing
        score = get_news_relevance_score(title, summary)

        # ✅ Always store the article
        article_entry = {
            "link": link,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "title": title,
            "summary": summary,
            "similarity_excluded": "No",
            "score": score,  # ✅ Storing score ONLY if not similar
            "status": "processed",
            "tweet": None
        }

        # ✅ Generate tweet only if score meets threshold
        if score >= TWEET_THRESHOLD:
            article_entry["tweet"] = summarize_news(title, summary, source)

        processed_articles.append(article_entry)
        scored_news.append((score, title, link, source, summary))

    # ✅ Sort articles by highest relevance score
    scored_news.sort(reverse=True, key=lambda x: x[0])

    # ✅ Pick top 3 highest-ranked news articles
    top_articles = scored_news[:3]

    new_entries = []

    for score, title, link, source, summary in top_articles:
        if score >= TWEET_THRESHOLD:
            tweet = summarize_news(title, summary, source)

            if post_tweet(tweet):
                new_entry = {
                    "link": link,
                    "date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "title": title,
                    "summary": summary,
                    "similarity_excluded": "No",  # ✅ Now included for consistency
                    "status": "posted",
                    "score": score,
                    "tweet": tweet
                }
                processed_articles.append(new_entry)
                new_entries.append(new_entry)
    
    # Check if statistical tweets are needed

    # ✅ Count script executions where no tweets were posted
    failed_runs = count_failed_runs(processed_articles)

    # ✅ Count today's statistical tweets
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_stat_count = sum(1 for article in processed_articles if article.get("date") == today and article.get("type") == "statistical")
    
    if failed_runs >= 3 and today_stat_count < 3:
        print(f"📊 Posting a statistical tweet. Today's count: {today_stat_count}")
        tweet = generate_statistical_tweet()
        if post_tweet(tweet):
            processed_articles.append({
                "date": today,
                "type": "statistical",
                "status": "posted",
                "tweet": tweet
            })

    # ✅ Save all processed articles to JSON
    processed_articles = cleanup_old_articles(processed_articles)  # ✅ Remove old entries
    save_processed_articles(processed_articles)  # ✅ Save cleaned data

    print("✅ filtered_news.json updated successfully!")
