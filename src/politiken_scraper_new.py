import argparse
import json
import time
import os
import sys
import logging
import requests
from pathlib import Path
from urllib.parse import urljoin, urlencode, urlparse, parse_qs, urlunsplit, urlencode
from bs4 import BeautifulSoup

#Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("politiken")

base = "https://politiken.dk"
login_api = "https://my.login.jppol.dk/u/login?state=hqFo2SBuRTBWWWx6MkFOVzlBeDZKdmpMQk1CLWFZUU9ObDVmT6Fur3VuaXZlcnNhbC1sb2dpbqN0aWTZIGl4Q255R0g5ZDJ6V1NNQzVEVjZaZHN2eXR4ekhqRWxao2NpZNkgVVpkYmJpTkdIM01WTVczb3hleEtnMVg4UWpXamRGOWqlb3JnaWS0b3JnX05yMmZvYnJrSGl3Y3VPbWmnb3JnbmFtZalwb2xpdGlrZW4&ui_locales=da"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": base,
}

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(headers)
    return s

def login(session, email, password):
    """
    On success the server sets auth cookies that
    are stored in the session and sent automatically with every subsequent request.
    """
    log.info("Logging in as %s …", email)

    # homepage first to get any CSRF / session cookies
    r = session.get(base, timeout=20)
    if r.status_code != 200:
        log.warning("Homepage returned %s (might still work)", r.status_code)

    #Post credentials to the JSON login endpoint
    payload = {
        "email": email,
        "password": password,
    }
    r = session.post(
        login_api,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{base}/log-ind/",
        },
        timeout=20,
    )

    if r.status_code == 200:
        try:
            data = r.json()
            if data.get("success") or data.get("loggedIn"):
                log.info("Login successful.")
                return True
        except ValueError:
            pass
        log.info("Login response 200 – assuming success (check cookies).")
        return True

    log.error("Login failed (status %s). Check your credentials.", r.status_code)
    log.debug("Response body: %s", r.text[:300])
    return False

def parse_search_page(html) -> list[dict]:
    """
    Extract article stubs.
    Structure
      div.search-result__article
        time.time.time--large (date)
        a[href="art<id>/slug"] (link wrapping title + teaser)
          h2.article-intro__title (title)
          h3.article-intro__summary (teaser/summary)
    """
    soup = BeautifulSoup(html, "lxml")
    articles = []

    # Primary selector
    items = soup.select("div.search-result__article")
    log.debug("div.search-result__article items found: %d", len(items))

    for item in items:
        #Link (wraps both h2 title and h3 summary)
        link_tag = item.find("a", href=True)
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        # href is relative
        url = urljoin(base, href)

        #Title
        title_el = (
            link_tag.select_one("h2.article-intro__title, h2.headline, h2")
            or link_tag.find("h2")
        )
        title = title_el.get_text(strip=True) if title_el else link_tag.get_text(strip=True)

        #Teaser
        teaser_el = (
            link_tag.select_one("h3.article-intro__summary p.summary__p")
            or link_tag.select_one("p.summary__p")
            or link_tag.select_one("h3.article-intro__summary, h3.summary, h3")
            or item.select_one("p.teaser")
        )
        teaser = teaser_el.get_text(strip=True) if teaser_el else ""
        time_tag = item.find("time")
        if time_tag:
            date = time_tag.get("datetime") or time_tag.get_text(strip=True)
        else:
            date = ""

        if title:
            articles.append({"title": title, "url": url, "date": date, "teaser": teaser})
    return articles

def next_page_url(html, current_url) -> str | None:
    """
    Return the URL of the next search-result page, or None if we're on the last page.
    """
    soup = BeautifulSoup(html, "lxml")

    # Always reconstruct from current_url so all filter params are preserved. 
    # never follow an href from the page because those drop the date filters.
    parsed = urlparse(current_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    current_page = int(qs.get("page", ["0"])[0])

    # Stop when the page contains no results
    if not soup.select("div.search-result__article"):
        log.debug("No results on page %d – stopping.", current_page)
        return None

    qs["page"] = [str(current_page + 1)]
    new_query = urlencode({k: v[0] for k, v in qs.items()})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

def scrape_article(session, url) -> dict:
    """
    Fetch and parse a single article.
    Returns a dict with keys: url, title, date, body.
    """
    r = session.get(url, timeout=20)
    if r.status_code != 200:
        log.warning("Article fetch returned %s for %s", r.status_code, url)
        return {"url": url, "error": f"HTTP {r.status_code}"}

    soup = BeautifulSoup(r.text, "lxml")

    title = ""
    for sel in [
        "h1.article-intro__title",
        "h1.headline",
        "h1[class*='title']",
        "h1[class*='headline']",
        "h1",
    ]:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break
    
    date = ""
    time_tag = (
        soup.select_one("time[datetime]")
        or soup.select_one("time")
    )
    if time_tag:
        date = time_tag.get("datetime") or time_tag.get_text(strip=True)

    #text is directly in <p class="drop-cap"> and subsequent <p> siblings
    body_parts = []
    # p.drop-cap anchors
    drop_caps = soup.select("p.drop-cap")
    if drop_caps:
        seen = set()
        for dc in drop_caps:
            node = dc
            while node:
                if node.name == "p":
                    text = node.get_text(strip=True)
                    if text and id(node) not in seen:
                        body_parts.append(text)
                        seen.add(id(node))
                elif node.name in ("aside", "figure", "div", "section",
                                   "header", "footer", "nav"):
                    break
                node = node.find_next_sibling()

    return {
        "url": url,
        "title": title,
        "date": date,
        "body": "\n\n".join(body_parts),
    }

def save_checkpoint(articles, out_path: Path) -> None:
    """
    Atomically write articles to out_path via a temp file so a crash mid-write never corrupts the output.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    log.info("Checkpoint saved: %d articles to %s", len(articles), out_path)

#Main pipe
def scrape_search(session, search_url, max_pages=10, delay=0.1, scrape_full_articles=True,
checkpoint_every=200, out_path: Path = None,) -> list[dict]:
    if out_path is not None:
        out_path = Path(out_path)

    all_articles = []
    current_url = search_url
    page = 1
    last_checkpoint = 0 # track how many articles were in the last save

    while current_url and (max_pages is None or page <= max_pages):
        log.info("Fetching search page %d: %s", page, current_url)
        r = session.get(current_url, timeout=20)
        if r.status_code != 200:
            log.error("Search page returned %s – stopping.", r.status_code)
            break

        stubs = parse_search_page(r.text)
        log.info("  Found %d articles on page %d.", len(stubs), page)

        if not stubs:
            log.info("No articles found on page %d - stopping.", page)
            break

        if scrape_full_articles:
            for stub in stubs:
                log.info("  Scraping: %s", stub["url"])
                article = scrape_article(session, stub["url"])
                all_articles.append({**stub, **article})
                time.sleep(delay)

                # Checkpoint every N articles
                if (
                    out_path
                    and checkpoint_every
                    and len(all_articles) - last_checkpoint >= checkpoint_every
                ):
                    save_checkpoint(all_articles, out_path)
                    last_checkpoint = len(all_articles)
        else:
            all_articles.extend(stubs)

        nxt = next_page_url(r.text, current_url)
        if nxt == current_url:
            break
        current_url = nxt
        page += 1
        time.sleep(delay)

    log.info("Scraped %d articles total.", len(all_articles))
    return all_articles

def main():
    parser = argparse.ArgumentParser(description="Scrape articles from Politiken.dk with potential for subscriber login.")
    parser.add_argument("--email", required=True, help="Politiken email")
    parser.add_argument("--password", required=True, help="Politiken password")
    parser.add_argument(
        "--url",
        default=("https://politiken.dk/search/?fDate=2005-01-01&tDate=2006-12-31&sort=pd"),
        help='Search URL to scrape (default: 2005-2006 search). Remember to wrap with "",')
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="Maximum number of search-result pages to fetch (Default None, crawls all)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.1,
        help="Seconds to wait between requests (default: 0.1)"
    )
    parser.add_argument(
        "--no-full-articles", action="store_false",
        help="Only collect article stubs (URL, title, date, teaser)"
    )
    parser.add_argument(
        "--output", default="politiken_results.json",
        help="Output JSON file name (default: politiken_results.json)"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    session = build_session()

    if not login(session, args.email, args.password):
        sys.exit("stopping, login failed.")

    articles = scrape_search(
        session=session,
        search_url=args.url,
        max_pages=args.max_pages,
        delay=args.delay,
        scrape_full_articles=args.no_full_articles,
        checkpoint_every=200,
        out_path=f'in/{args.output}'
    )
    root_dir = Path(__file__).parent.parent
    out_path= root_dir / "in" # outputting to the in folder for r analysis
    os.makedirs(out_path, exist_ok=True)
    filename = Path(f'{out_path}/{args.output}')
    filename.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Results written to %s", out_path)

    print(f"\n{'='*60}")
    print(f"Total articles scraped: {len(articles)}")
    print(f"Output file in: {out_path.resolve()}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
