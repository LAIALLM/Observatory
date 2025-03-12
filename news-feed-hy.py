import os
import tweepy
import feedparser
import re
import openai
import json
import time
import random
from datetime import datetime, timedelta

# Load API keys from GitHub Secrets
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_SECRET = os.getenv("TWITTER_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")

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
TWEET_THRESHOLD = 9 # Define score threshold for tweets

# Random tweets probabilities
RANDOM_NEWS = 0.2
RANDOM_STATISTIC = 0.2
RANDOM_INFRASTRUCTURE = 0.1
RANDOM_CRYPTO = 0.3
RANDOM_NONE = 0.2

# Daily tweet limits
NEWS_TWEETS_LIMIT = 2  # Max news tweets per day
STAT_TWEETS_LIMIT = 1  # Max statistical tweets per day
INFRA_TWEETS_LIMIT= 1
CRYPTO_TWEETS_LIMIT= 1

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

# Check if a new article is similar to previously processed high-scoring articles."""
def is_similar_news(new_title, new_summary, processed_articles, threshold=0.6, limit=30):    
    new_keywords = extract_key_terms(new_title) | extract_key_terms(new_summary)

    # Debugging: Identify any invalid scores in JSON
    for article in processed_articles:
        if not isinstance(article.get("score", 0), (int, float)):
            print(f"⚠️ Warning: Invalid score detected in article - {article}")

    # ✅ Fix: Ensure scores are valid numbers before filtering
    recent_articles = [article for article in processed_articles 
                       if isinstance(article.get("score", 0), (int, float)) 
                       and article.get("score", 0) >= TWEET_THRESHOLD][-limit:]

    for article in recent_articles:
        old_keywords = extract_key_terms(article.get("tweet", "")) | extract_key_terms(article.get("title", "")) | extract_key_terms(article.get("summary", ""))
        
        if old_keywords:
            similarity = len(new_keywords & old_keywords) / len(new_keywords | old_keywords)
            if similarity >= threshold:
                print(f"⚠️ Skipping similar news: {new_title} (Similarity: {similarity:.2f})")
                return True  # Found a similar article

    return False  # No duplicates found

# Load previously processed articles (both tweeted & filtered)
def load_processed_articles():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as file:
                processed_data = json.load(file)
                print(f"Loaded {len(processed_data)} previously processed articles.")

                # ✅ Fix: Ensure all entries have 'link' key before returning
                valid_articles = [article for article in processed_data if isinstance(article, dict) and "link" in article]

                if len(valid_articles) < len(processed_data):
                    print(f"⚠️ Warning: {len(processed_data) - len(valid_articles)} malformed entries found and ignored.")

                return valid_articles

        except json.JSONDecodeError:
            print("⚠️ Corrupted JSON file. Resetting to an empty list.")
            return []
    return []

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

# Consolidated randomness function for post type
def select_tweet_type():
    return random.choices(["news", "statistical", "infrastructure", "crypto", "none"], [RANDOM_NEWS, RANDOM_STATISTIC, RANDOM_INFRASTRUCTURE, RANDOM_CRYPTO, RANDOM_NONE])[0]

# Count how many news tweets were posted today.
def count_news_tweets_today(processed_articles):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return sum(1 for article in processed_articles if article.get("date") == today and article.get("type") == "news")

# Count how many statistical tweets were posted today.
def count_stat_tweets_today(processed_articles):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return sum(1 for article in processed_articles if article.get("date") == today and article.get("type") == "statistical")

# Count how many infrastructural tweets were posted today.
def count_infra_tweets_today(processed_articles):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return sum(1 for article in processed_articles if article.get("date") == today and article.get("type") == "infrastructure")

# Count how many crypto tweets were posted today.
def count_crypto_tweets_today(processed_articles):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return sum(1 for article in processed_articles if article.get("date") == today and article.get("type") == "crypto")

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

# Use GROK-2-1212 to check if news is relevant
def get_news_relevance_score(title, summary):
    client = openai.OpenAI(
        api_key=XAI_API_KEY,  # Use xAI API key
        base_url="https://api.x.ai/v1"  # xAI endpoint
    )

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
        model="grok-2-1212",  # Changed to Grok-2-1212
        messages=[{"role": "user", "content": prompt}]
    )

    score_text = response.choices[0].message.content.strip()
    try:
        score = int(score_text)
        return score if 0 <= score <= 10 else 0
    except ValueError:
        return 0
    except openai.OpenAIError as e:
        print(f"❌ xAI API Error: {e}")
        return 0

# Summarize news and format tweet
def summarize_news(title, summary, source):
    client = openai.OpenAI(
        api_key=XAI_API_KEY,  # Use xAI API key
        base_url="https://api.x.ai/v1"  # xAI endpoint
    )

    prompt = f"""
    Rewrite this construction-related news title into a concise, natural tweet.

    - **Always place a country flag emoji at the START** if a country, city, or company is explicitly mentioned.
    - **Format:** (Flag) NEWS: Main content
    - **DO NOT use** quotes, hashtags, sources, or websites.
    - **DO NOT use any emojis except country flags.**

    - **Only add a stock ticker $TICKER if:**
      1. The company is **publicly traded**.
      2. The **correct** ticker symbol is available.
    
    Title: {title}
    """

    if summary:
        prompt += f"\n\nAlso, integrate one key point from this summary: {summary}"

    response = client.chat.completions.create(
        model="grok-2-1212",  # Changed to Grok-2-1212
        messages=[{"role": "user", "content": prompt}]
    )

    ai_summary = response.choices[0].message.content.strip()
    ai_summary = ai_summary.replace('"', '').replace("'", "")
    tweet = f"{ai_summary}"
    return tweet[:280]

# Generate statistical tweet
# Global list of statistical tweet categories in a preferred order
STATISTICAL_CATEGORIES = [
    "infrastructure",
    "energy",
    "transportation",
    "population",
    "urban development",
    "urban planning",
    "smart cities",
    "countries",
    "cities",
    "construction projects",
    "engineering projects",
    "infrastructural projects",
    "construction companies",
    "infrastructure companies",
    "urban development firms"
]


def generate_statistical_tweet(selected_category):
    """Generate a statistical tweet dynamically using GPT-4."""
    tweet_formats = {
        1: "A single striking statistic or future projection",
        2: "A direct comparison between two statistical facts",
        3: """Generate a ranked list of the top 5 or, if space permits, top 10, ensuring the tweet is under 280 characters.
    
Format:
Summary: <One sentence overview of the ranking outcome>

1. City/Country
2. City/Country
3. City/Country
"""
}
    
    selected_format_key = random.choice(list(tweet_formats.keys()))
    selected_format = tweet_formats[selected_format_key]
    
    prompt = f"""
    Assume the current year is 2025. Generate a concise, direct, factual, and impactful statistical tweet about {selected_category} that uses current data or realistic projections for 2025 and beyond. Avoid using outdated statistics from before 2023.

    {selected_format}

    The tweet should:
    - Present only clear, factual data
    - **NEVER use quotes, hashtags, or generic emojis.**
    - **Keep it strictly under 280 characters.**
    - **NEVER use generic phrases and unnecessary filler words.** Keep it sharp and data-driven.
    - **Always place country flags before a location name.**
    - **Use proper line breaks for readability.** If the tweet contains multiple paragraphs, insert a blank line between them.
    """

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()


# Generate an infrastructure tweet using your provided prompt.
def generate_infrastructure_tweet():
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    prompt = """
    Write a concise social media post from an external perspective about a tech company that highlights a single key quantitative infrastructure metric. Focus strictly on presenting data with minimal wording.

    The tweet should:
    - Present only clear, factual data (e.g., daily data volumes, production figures, energy consumption, or efficiency ratings)
    - **NEVER use quotes, hashtags, or generic emojis.**
    - **Keep it strictly under 280 characters.**
    - **NEVER use generic phrases and unnecessary filler words.** Keep it sharp and data-driven.
    - **Always place country flags before a location name.**
    - **Use proper line breaks for readability.** If the tweet contains multiple paragraphs, insert a blank line between them.     
    
    - **Only add a stock ticker $TICKER if:**
      1. The company is **publicly traded**.
      2. The **correct** ticker symbol is available.  
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    tweet = response.choices[0].message.content.strip()
    return tweet

# Generate crypto tweet
# Global list of crypto infrastructure categories
CRYPTO_INFRA_CATEGORIES = [
    "electricity consumption",
    "hardware costs",
    "node distribution",
    "cloud & data center usage",
    "geographic mining concentration",
    "carbon footprint",
    "network scalability costs",
    "maintenance & security costs",
    "transaction throughput vs. cost",
    "staking vs. mining costs",
    "validator decentralization",
    "historical cost trends of running blockchain networks",
    "government regulations & impact on infrastructure",
]


# Crypto tweet formats to bring variation
CRYPTO_TWEET_FORMATS = {
    1: "A single striking statistic or future projection.",
    2: "A direct comparison between two blockchain networks.",
    3: """Generate a ranked list ensuring the tweet is under 280 characters.
    
Format:
Summary: <One sentence overview of the ranking outcome>

1. Item
2. Item
3. Item
""",
}


# Generate a Crypto tweet using Grok-2-1212
def generate_crypto_tweet():
    client = openai.OpenAI(
        api_key=XAI_API_KEY,  # Using xAI API key
        base_url="https://api.x.ai/v1"  # xAI endpoint
    )

    # Randomly select a category and tweet format
    selected_category = random.choice(CRYPTO_INFRA_CATEGORIES)
    selected_format_key = random.choice(list(CRYPTO_TWEET_FORMATS.keys()))
    selected_format = CRYPTO_TWEET_FORMATS[selected_format_key]  # Get actual format text

    # Construct the dynamic prompt
    prompt = f"""
    The current year is 2025. Generate a concise, direct, factual, and impactful statistical tweet about the infrastructural costs of running Bitcoin, Ethereum, or Solana. Focus specifically on: **{selected_category}**.

    {selected_format}

    The tweet should:
    - Present only clear, factual data
    - **NEVER use quotes, hashtags, or generic emojis.**
    - **Keep it strictly under 280 characters.**
    - **NEVER use generic phrases and unnecessary filler words.** Keep it sharp and data-driven.
    - **Always place country flags before a location name.**
    - **Use proper line breaks for readability.** If the tweet contains multiple paragraphs, insert a blank line between them.
    
    - **Only add a stock ticker $TICKER if:**
      1. The company is **publicly traded**.
      2. The **correct** ticker symbol is available. 
    """

    response = client.chat.completions.create(
        model="grok-2-1212",  # Using Grok-2-1212
        messages=[{"role": "user", "content": prompt}]
    )

    tweet = response.choices[0].message.content.strip()
    return tweet[:280]  # Ensure it's within the character limit



# Post to X (Twitter) using API v2 with a delay
def post_tweet(tweet):
    print(f"🚀 Attempting to tweet: {tweet}")  # Debugging line
    try:
        response = twitter_client.create_tweet(text=tweet)
        print(f"✅ Tweet posted successfully: {response.data}")

        # Introduce a 3-minute delay **after** posting each tweet
        print("⏳ Waiting 2 minutes before posting the next tweet...")
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
    processed_articles = load_processed_articles()
    filtered_links = {article["link"] for article in processed_articles if "link" in article} if processed_articles else set()
    print(f"📂 {len(processed_articles)} articles already processed.")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_news_count = count_news_tweets_today(processed_articles)
    today_stat_count = count_stat_tweets_today(processed_articles)
    today_infra_count = count_infra_tweets_today(processed_articles)
    today_crypto_count = count_crypto_tweets_today(processed_articles)

    # Consolidated random selection for type of tweet
    tweet_type = select_tweet_type()
    print(f"🔀 Selected tweet type: {tweet_type}")

    # Early exit if daily tweet limit for the selected type is reached
    if tweet_type == "news" and today_news_count >= NEWS_TWEETS_LIMIT:
        print(f"🚫 Reached daily news tweet limit ({NEWS_TWEETS_LIMIT}). Exiting to save resources.")
        exit(0)
    elif tweet_type == "statistical" and today_stat_count >= STAT_TWEETS_LIMIT:
        print(f"🚫 Reached daily statistical tweet limit ({STAT_TWEETS_LIMIT}). Exiting to save resources.")
        exit(0)
    elif tweet_type == "infrastructure" and today_infra_count >= INFRA_TWEETS_LIMIT:
        print(f"🚫 Reached daily infrastructure tweet limit ({INFRA_TWEETS_LIMIT}). Exiting to save resources.")
        exit(0)
    elif tweet_type == "crypto" and today_crypto_count >= CRYPTO_TWEETS_LIMIT:
        print(f"🚫 Reached daily crypto tweet limit ({CRYPTO_TWEETS_LIMIT}). Exiting to save resources.")
        exit(0)

    if tweet_type == "news":
        latest_news = get_latest_news()
        print(f"📰 Found {len(latest_news)} new articles.")

        scored_news = []
        seen_links = set()  # ✅ Prevent processing duplicate links in the same workflow run

        for title, link, source, summary in latest_news:     
            if today_news_count >= NEWS_TWEETS_LIMIT:
                print(f"🚫 Stopping news tweets early: {today_news_count} tweets reached.")
                break  # 💡 STOP posting news if limit is reached      

            if link in seen_links or link in filtered_links:
                print(f"⏩ Skipping duplicate article from multiple RSS feeds: {title}")
                continue
            seen_links.add(link) 

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
                    "score": 0,  # ✅ No GPT-4 scoring for similar articles
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
                    today_news_count += 1  # ✅ Update count after posting
                    new_entry = {
                        "link": link,
                        "date": datetime.utcnow().strftime("%Y-%m-%d"),
                        "title": title,
                        "summary": summary,
                        "similarity_excluded": "No",  # ✅ Now included for consistency
                        "score": score,
                        "status": "posted",
                        "tweet": tweet,
                        "type": "news"  # <-- Include this line to mark the tweet type
                    }
                    processed_articles.append(new_entry)
                    new_entries.append(new_entry)
            else:
                print("🚫 No high-scoring news found to post.")
    
    
    elif tweet_type == "statistical":
        if today_stat_count >= STAT_TWEETS_LIMIT:
            print(f"🚫 Reached daily statistical tweet limit ({STAT_TWEETS_LIMIT}). Skipping statistical tweets.")
        else:
            # Select a category from your predefined global list.
            selected_category = random.choice(STATISTICAL_CATEGORIES)
            # Generate a tweet specific to that category.
            tweet = generate_statistical_tweet(selected_category)
            if post_tweet(tweet):
                today_stat_count += 1
                processed_articles.append({
                    "link": None,  
                    "date": today,
                    "status": "posted",
                    "tweet": tweet,
                    "type": "statistical",
                    "category": selected_category
                })

    elif tweet_type == "infrastructure":
        if today_infra_count >= INFRA_TWEETS_LIMIT:
            print(f"🚫 Reached daily infrastructure tweet limit ({INFRA_TWEETS_LIMIT}). Skipping infrastructure tweets.")
        else:
            tweet = generate_infrastructure_tweet()
            if post_tweet(tweet):
                processed_articles.append({
                    "link": None,
                    "date": today,
                    "status": "posted",
                    "tweet": tweet,
                    "type": "infrastructure"
                })

    elif tweet_type == "crypto":
        if today_crypto_count >= CRYPTO_TWEETS_LIMIT:
            print(f"🚫 Reached daily crypto tweet limit ({CRYPTO_TWEETS_LIMIT}). Skipping crypto tweets.")
        else:
            tweet = generate_crypto_tweet()
            if post_tweet(tweet):
                processed_articles.append({
                    "link": None,
                    "date": today,
                    "status": "posted",
                    "tweet": tweet,
                    "type": "crypto"
                })    

    else:
        print("🤖 No tweet posted in this run to simulate human-like activity.")

    # ✅ Save all processed articles to JSON
    processed_articles = cleanup_old_articles(processed_articles)
    save_processed_articles(processed_articles)
    print("✅ filtered_news.json updated successfully!")
