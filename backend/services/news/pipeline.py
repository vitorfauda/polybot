"""News collection pipeline - fetches from multiple sources and scores sentiment."""

import feedparser
import httpx
from datetime import datetime, timezone
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from typing import Optional
from core.config import get_settings


class NewsPipeline:
    """Collects news from free sources and scores sentiment."""

    # Google News RSS categories mapped to Polymarket categories
    TOPIC_QUERIES = {
        "politics": ["politics", "election", "congress", "president", "legislation"],
        "crypto": ["bitcoin", "ethereum", "cryptocurrency", "crypto regulation"],
        "economics": ["federal reserve", "inflation", "GDP", "interest rates", "recession"],
        "sports": ["NFL", "NBA", "soccer", "championship"],
        "tech": ["AI artificial intelligence", "tech regulation", "SpaceX"],
        "geopolitics": ["war", "sanctions", "NATO", "trade war", "geopolitics"],
    }

    RSS_FEEDS = {
        "reuters": "https://feeds.reuters.com/reuters/topNews",
        "bbc": "http://feeds.bbci.co.uk/news/rss.xml",
        "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "cointelegraph": "https://cointelegraph.com/rss",
        "npr": "https://feeds.npr.org/1001/rss.xml",
    }

    def __init__(self):
        self.settings = get_settings()
        self.vader = SentimentIntensityAnalyzer()
        self._http = httpx.AsyncClient(timeout=15.0)

    async def collect_google_news(
        self, query: str, max_results: int = 10
    ) -> list[dict]:
        """Fetch news from Google News RSS for a query."""
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = await self._http.get(url)
            feed = feedparser.parse(resp.text)
            articles = []
            for entry in feed.entries[:max_results]:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                sentiment = self.vader.polarity_scores(entry.title)
                articles.append({
                    "source": f"google_news:{query}",
                    "title": entry.title,
                    "url": entry.link,
                    "published_at": published,
                    "sentiment_vader": sentiment["compound"],
                    "sentiment_label": self._sentiment_label(sentiment["compound"]),
                })
            return articles
        except Exception as e:
            print(f"[NewsPipeline] Google News error for '{query}': {e}")
            return []

    async def collect_rss_feed(
        self, name: str, url: str, max_results: int = 10
    ) -> list[dict]:
        """Fetch articles from a specific RSS feed."""
        try:
            resp = await self._http.get(url)
            feed = feedparser.parse(resp.text)
            articles = []
            for entry in feed.entries[:max_results]:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                sentiment = self.vader.polarity_scores(entry.title)
                summary = getattr(entry, "summary", "")
                if summary:
                    summary_sentiment = self.vader.polarity_scores(summary)
                    avg_compound = (sentiment["compound"] + summary_sentiment["compound"]) / 2
                else:
                    avg_compound = sentiment["compound"]

                articles.append({
                    "source": f"rss:{name}",
                    "title": entry.title,
                    "url": entry.link,
                    "content_summary": summary[:500] if summary else None,
                    "published_at": published,
                    "sentiment_vader": round(avg_compound, 4),
                    "sentiment_label": self._sentiment_label(avg_compound),
                })
            return articles
        except Exception as e:
            print(f"[NewsPipeline] RSS error for '{name}': {e}")
            return []

    async def collect_all(self, categories: Optional[list[str]] = None) -> list[dict]:
        """Collect news from all sources for specified categories."""
        if categories is None:
            categories = list(self.TOPIC_QUERIES.keys())

        all_articles = []

        # Google News for each category
        for cat in categories:
            queries = self.TOPIC_QUERIES.get(cat, [cat])
            for query in queries[:2]:  # limit queries per category
                articles = await self.collect_google_news(query, max_results=5)
                for a in articles:
                    a["category"] = cat
                all_articles.extend(articles)

        # RSS feeds
        for name, url in self.RSS_FEEDS.items():
            articles = await self.collect_rss_feed(name, url, max_results=5)
            all_articles.extend(articles)

        # Deduplicate by title similarity
        seen_titles = set()
        unique = []
        for article in all_articles:
            title_key = article["title"].lower()[:60]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(article)

        return unique

    async def collect_for_market(self, market_question: str, max_results: int = 10) -> list[dict]:
        """Collect news specifically related to a market question."""
        # Extract key terms from the market question
        keywords = self._extract_keywords(market_question)
        all_articles = []
        for kw in keywords[:3]:
            articles = await self.collect_google_news(kw, max_results=max_results)
            all_articles.extend(articles)
        return all_articles

    def _extract_keywords(self, question: str) -> list[str]:
        """Extract search keywords from a market question."""
        stop_words = {
            "will", "the", "be", "in", "on", "at", "to", "for", "of", "a",
            "an", "is", "it", "by", "or", "and", "this", "that", "with",
            "before", "after", "yes", "no", "does", "do", "has", "have",
        }
        words = question.lower().replace("?", "").split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        # Return phrases of 2-3 keywords for better search
        if len(keywords) >= 4:
            return [
                " ".join(keywords[:3]),
                " ".join(keywords[1:4]),
                " ".join(keywords[:2]),
            ]
        return [" ".join(keywords)] if keywords else [question[:50]]

    @staticmethod
    def _sentiment_label(compound: float) -> str:
        if compound >= 0.05:
            return "positive"
        elif compound <= -0.05:
            return "negative"
        return "neutral"

    async def close(self):
        await self._http.aclose()
