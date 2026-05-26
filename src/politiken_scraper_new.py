'''
25/05 THIS IS THE NEWEST VERSION OF THE SCRIPT
Cleaned for irrelevant columns
'''


import argparse
import json
import time
import re
import sys
import logging
from pathlib import Path
from urllib.parse import urljoin, urlencode, urlparse, parse_qs, urlunsplit, urlencode
import requests
from bs4 import BeautifulSoup

#Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("politiken")

base = "https://politiken.dk"
login_api = "https://my.login.jppol.dk/u/login?state=hqFo2SBkSlA2dUNjOWYycTBSX2pzLXZUbE9FRWkzeEtEeVp5SKFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIGcxTklzTDFtUExDZW4zaTVYbllxdG9BYVhKclp4T29vo2NpZNkgVVpkYmJpTkdIM01WTVczb3hleEtnMVg4UWpXamRGOWqlb3JnaWS0b3JnX05yMmZvYnJrSGl3Y3VPbWmnb3JnbmFtZalwb2xpdGlrZW4&ui_locales=da"

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

    #Fallback to form-based login (older endpoint)
    if r.status_code in (400, 401, 403, 404):
        log.debug("JSON endpoint failed (%s), trying form login …", r.status_code)
        login_page = session.get(f"{base}/log-ind/", timeout=20)
        soup = BeautifulSoup(login_page.text, "lxml")

        form = soup.find("form", id=lambda x: x and "login" in x.lower()) or \
               soup.find("form", action=lambda x: x and "login" in x.lower())

        if form:
            action = urljoin(base, form.get("action", "/log-ind/"))
            data = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                if name:
                    data[name] = inp.get("value", "")
            data["email"] = email
            data["password"] = password

            r2 = session.post(action, data=data, timeout=20,
                              headers={"Referer": f"{base}/log-ind/"})
            if r2.status_code in (200, 302):
                log.info("Form login posted (status %s).", r2.status_code)
                return True

    log.error("Login failed (status %s). Check your credentials.", r.status_code)
    log.debug("Response body: %s", r.text[:300])
    return False

def parse_search_page(html) -> list[dict]:
    """
    Extract article stubs from a Politiken search result page.
    Returns a list of dicts: {title, url, date, teaser}.

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

    # Fallback selectors in case Politiken tests a new layout
    if not items:
        for sel in [
            "article.search-result",
            "div[class*='search-result']",
            "div.card div[class*='search']",
        ]:
            items = soup.select(sel)
            if items:
                log.debug("Fallback selector '%s' matched %d items", sel, len(items))
                break

    for item in items:
        #Link (wraps both h2 title and h3 summary)
        link_tag = item.find("a", href=True)
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        #Politiken href is relative
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

    Politiken paginates via a page parameter (0-indexed).
    There is no explicit "next" instead detect whether the current
    page returned any results and increment the counter.
    """
    soup = BeautifulSoup(html, "lxml")

    # Always reconstruct from current_url so all filter params are preserved. 
    # Never follow an <a href> from the page because those drop the date/query filters.
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

#Article scraping
def scrape_article(session, url) -> dict:
    """
    Fetch and parse a single Politiken article.
    Returns a dict with keys: url, title, date, body.
    """
    r = session.get(url, timeout=20)
    if r.status_code != 200:
        log.warning("Article fetch returned %s for %s", r.status_code, url)
        return {"url": url, "error": f"HTTP {r.status_code}"}

    soup = BeautifulSoup(r.text, "lxml")

    #Title
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

    #date
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

    #Fallback: older semantic container selectors
    if not body_parts:
        for sel in [
            "div.article__body",
            "div[class*='article-body']",
            "div[class*='article__content']",
            "div.body-text",
            "section[class*='body']",
        ]:
            container = soup.select_one(sel)
            if container:
                for tag in container.select(
                    "aside, figure, script, style, "
                    "[class*='ad-'], [class*='reklame'], "
                    "[class*='related'], [class*='most-read']"
                ):
                    tag.decompose()
                paragraphs = [p.get_text(strip=True) for p in container.find_all("p")
                              if p.get_text(strip=True)]
                body_parts = paragraphs or [container.get_text(separator="\n", strip=True)]
                break

    #Last-resort: all <p> tags with substantial prose text
    if not body_parts:
        log.debug("No body container found, falling back to all <p> tags")
        body_parts = [
            p.get_text(strip=True) for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 60
        ]

    return {
        "url": url,
        "title": title,
        "date": date,
        "body": "\n\n".join(body_parts),
    }

def save_checkpoint(articles, out_path) -> None:
    """
    Atomically write articles to out_path via a temp file so a crash mid-write never corrupts the output.
    """
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    log.info("Checkpoint saved: %d articles → %s", len(articles), out_path)

#Main pipeline
def scrape_search(
    session,
    search_url,
    max_pages=10,
    delay=0.1,
    scrape_full_articles=True,
    checkpoint_every=200,
    out_path: Path = None,
) -> list[dict]:
    all_articles = []
    current_url = search_url
    page = 1
    last_checkpoint = 0  # track how many articles were in the last save

    while current_url and (max_pages is None or page <= max_pages):
        log.info("Fetching search page %d: %s", page, current_url)
        r = session.get(current_url, timeout=20)
        if r.status_code != 200:
            log.error("Search page returned %s – stopping.", r.status_code)
            break

        stubs = parse_search_page(r.text)
        log.info("  Found %d articles on page %d.", len(stubs), page)

        if not stubs:
            log.info("No articles found on page %d – stopping pagination.", page)
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
    parser = argparse.ArgumentParser(description="Scrape articles from Politiken.dk with subscriber login.")
    parser.add_argument("--email", required=True, help="Politiken email")
    parser.add_argument("--password", required=True, help="Politiken password")
    parser.add_argument(
        "--url",
        default=("https://politiken.dk/search/?fDate=2005-01-01&tDate=2006-12-31&sort=pd"),
        help="Search URL to scrape (default: 2005-2006 search)",)
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
        help="Output JSON file path (default: politiken_results.json)"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    session = build_session()

    if not login(session, args.email, args.password):
        sys.exit("Aborting – login failed.")

    articles = scrape_search(
        session=session,
        search_url=args.url,
        max_pages=args.max_pages,
        delay=args.delay,
        scrape_full_articles=args.no_full_articles,
        checkpoint_every=200,
        out_path=Path(args.output)
    )

    out_path=Path(args.output)
    out_path.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Results written to %s", out_path)

    # Print a quick summary to stdout
    print(f"\n{'='*60}")
    print(f"Total articles scraped: {len(articles)}")
    print(f"Output file: {out_path.resolve()}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
