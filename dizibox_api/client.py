"""Dizibox API Client with Cloudflare TLS Impersonation, Caching, and Stream Decryption."""

import re
import time
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests

from dizibox_api.cache import TTLCache
from dizibox_api.crypto import decrypt_cryptojs_aes
from dizibox_api.exceptions import (
    DiziboxAPIError,
    CloudflareBlockedError,
    NotFoundError,
    ParseError,
    DecryptionError,
)
from dizibox_api.models import (
    SeriesSummary,
    EpisodeSummary,
    SeriesDetail,
    SubtitleTrack,
    EpisodeStreamDetail,
    RecentEpisodeItem,
)

# Use lxml parser if available, fallback to html.parser
try:
    import lxml  # noqa: F401
    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"


class DiziboxClient:
    """High-performance API Client for Dizibox (dizibox.live)."""

    DEFAULT_BASE_URL = "https://www.dizibox.live"
    DEFAULT_IMPERSONATE = "chrome120"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        impersonate: str = DEFAULT_IMPERSONATE,
        timeout: int = 15,
        cache_ttl: int = 300,
        max_retries: int = 3,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.impersonate = impersonate
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache = TTLCache(default_ttl=cache_ttl, maxsize=1500)

        self._default_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if headers:
            self._default_headers.update(headers)

        self._session: Optional[requests.Session] = None
        self._init_session()

    def _init_session(self) -> None:
        """Initialize or reset persistent curl_cffi session."""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = requests.Session(impersonate=self.impersonate)
        self._session.headers.update(self._default_headers)

    def _request(
        self,
        method: str,
        path_or_url: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> requests.Response:
        """Send HTTP request with automatic retry and Cloudflare verification."""
        url = path_or_url if path_or_url.startswith("http") else urljoin(self.base_url, path_or_url)
        t_out = timeout or self.timeout

        for attempt in range(1, self.max_retries + 1):
            try:
                if self._session is None:
                    self._init_session()

                resp = self._session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    headers=headers,
                    timeout=t_out,
                )

                if resp.status_code in (403, 503):
                    text_lower = resp.text.lower()
                    if "just a moment" in text_lower or "challenge-platform" in text_lower:
                        raise CloudflareBlockedError(f"Cloudflare challenge encountered on {url}")
                    if resp.status_code == 403:
                        raise DiziboxAPIError(f"HTTP 403 Forbidden on {url}")

                if resp.status_code == 404:
                    raise NotFoundError(f"Resource not found: {url}")

                return resp

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, CloudflareBlockedError) as exc:
                if attempt == self.max_retries:
                    raise
                # Re-initialize session on connection/CF anomalies and backoff
                time.sleep(0.5 * (2 ** (attempt - 1)))
                self._init_session()

        raise DiziboxAPIError(f"Failed to fetch {url} after {self.max_retries} attempts")

    def _get_soup(self, path_or_url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> BeautifulSoup:
        resp = self._request("GET", path_or_url, params=params, headers=headers)
        return BeautifulSoup(resp.content, HTML_PARSER)

    # ---------------------------------------------------------
    # Public API Methods
    # ---------------------------------------------------------

    def get_recent_episodes(self, page: int = 1) -> List[RecentEpisodeItem]:
        """Fetch latest uploaded episodes feed."""
        cache_key = f"recent_episodes_p{page}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        path = f"/tum-bolumler/page/{page}/" if page > 1 else "/tum-bolumler/"
        soup = self._get_soup(path)

        items: List[RecentEpisodeItem] = []
        cards = soup.select(".article-episode-card")

        for card in cards:
            a_tag = card.select_one("a")
            if not a_tag:
                continue

            url = a_tag.get("href", "")
            slug = url.strip("/").split("/")[-1]

            title_tag = card.select_one(".episode-card-title, .title")
            raw_title = title_tag.get_text(strip=True) if title_tag else ""

            # Check season & episode number
            meta_tag = card.select_one(".episode-card-meta, .episode, .meta")
            meta_text = meta_tag.get_text(strip=True) if meta_tag else ""

            # Extract numbers from slug or meta
            season_match = re.search(r"(\d+)-sezon", slug)
            episode_match = re.search(r"(\d+)-bolum", slug)
            season_num = int(season_match.group(1)) if season_match else 1
            episode_num = int(episode_match.group(1)) if episode_match else 1

            # Extract series title from raw_title or slug
            series_title = re.split(r"\d+\.se?zon", raw_title, flags=re.IGNORECASE)[0].strip()
            if not series_title:
                parts = slug.split("-")
                series_parts = []
                for p in parts:
                    if p in ("sezon", "bolum", "izle", "hd"):
                        break
                    series_parts.append(p.capitalize())
                series_title = " ".join(series_parts)

            # Poster extraction: Dizibox uses lazy-loading with data-src on .afis img
            poster_img = card.select_one("img.afis, img[data-src*='uploads'], img[data-src*='afisler']")
            if poster_img and poster_img.get("data-src"):
                thumb_url = poster_img.get("data-src")
            else:
                # Fallback to series poster from slug
                series_slug = re.sub(r"-\d+-sezon.*$", "", slug)
                thumb_url = f"{self.base_url}/wp-content/uploads/afisler/{series_slug}-200x290.jpg"

            badge = "Altyazılı"
            if "dublaj" in raw_title.lower() or "dublaj" in slug.lower():
                badge = "Türkçe Dublaj"

            items.append(
                RecentEpisodeItem(
                    title=raw_title,
                    episode_slug=slug,
                    series_title=series_title,
                    season_number=season_num,
                    episode_number=episode_num,
                    url=url,
                    thumbnail_url=thumb_url,
                    badge=badge,
                )
            )

        self.cache.set(cache_key, items, ttl=180)
        return items

    def get_archive_series(self, page: int = 1) -> List[SeriesSummary]:
        """Fetch all indexed series from the master archive (4800+ series)."""
        cache_key = f"archive_p{page}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        path = f"/arsiv/page/{page}/" if page > 1 else "/arsiv/"
        soup = self._get_soup(path)

        series_list: List[SeriesSummary] = []
        links = soup.find_all("a")
        seen_slugs = set()

        for a in links:
            href = a.get("href", "")
            if "/diziler/" in href and not href.endswith("/diziler/"):
                slug = href.strip("/").split("/")[-1]
                if slug in seen_slugs or "-bolum" in slug:
                    continue
                seen_slugs.add(slug)

                title = a.get_text(strip=True)
                if not title or len(title) < 2:
                    continue

                base_slug = re.sub(r"-izle(-\d+)?$", "", slug)
                poster_url = f"{self.base_url}/wp-content/uploads/afisler/{base_slug}-200x290.jpg"

                series_list.append(
                    SeriesSummary(
                        title=title,
                        slug=slug,
                        url=href,
                        poster_url=poster_url,
                    )
                )

        self.cache.set(cache_key, series_list, ttl=600)
        return series_list

    def search(self, query: str) -> List[SeriesSummary]:
        """Search series by matching title in archive."""
        q_clean = query.strip().lower()
        if not q_clean:
            return []

        cache_key = f"search_{q_clean}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        # Archive has entire site index
        all_series = self.get_archive_series()
        matched = [
            s for s in all_series
            if q_clean in s.title.lower() or q_clean in s.slug.lower().replace("-", " ")
        ]

        self.cache.set(cache_key, matched, ttl=300)
        return matched

    def get_series(self, slug_or_url: str) -> SeriesDetail:
        """Fetch full series metadata, cast, poster, and episode hierarchy."""
        slug = slug_or_url.strip("/").split("/")[-1]
        cache_key = f"series_{slug}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        url = slug_or_url if slug_or_url.startswith("http") else f"{self.base_url}/diziler/{slug}/"
        soup = self._get_soup(url)

        title_tag = soup.select_one("h1")
        title = title_tag.get_text(strip=True) if title_tag else slug.replace("-", " ").title()

        # Description from tv-story
        story_div = soup.select_one(".tv-story")
        if story_div:
            desc = story_div.get_text(strip=True)
        else:
            desc_tag = soup.select_one(".series-summary, .entry-content, .description")
            desc = desc_tag.get_text(strip=True) if desc_tag else None

        # Poster: Check og:image or main-cover img
        og_img = soup.select_one("meta[property='og:image']")
        main_img = soup.select_one("img.main-cover, .poster img")
        if og_img and og_img.get("content"):
            poster_url = og_img.get("content")
        elif main_img and main_img.get("src"):
            poster_url = main_img.get("src")
        else:
            base_slug = re.sub(r"-izle(-\d+)?$", "", slug)
            poster_url = f"{self.base_url}/wp-content/uploads/afisler/{base_slug}-200x290.jpg"

        # IMDb rating
        imdb_tag = soup.select_one(".imdb-point, .imdb, .rating")
        imdb_rating = None
        if imdb_tag:
            try:
                imdb_rating = float(re.search(r"(\d+[.,]\d+)", imdb_tag.get_text()).group(1).replace(",", "."))
            except Exception:
                pass

        # Genres
        genres = [g.get_text(strip=True) for g in soup.select("a[href*='/tur/'], a[href*='/genre/']")]

        # Discover all season URLs
        season_urls = []
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "/dizi/" in href and "sezon" in href and href not in season_urls:
                season_urls.append(href)

        # If no separate season URLs, parse current page
        pages_to_parse = season_urls if season_urls else [url]

        episodes_list: List[EpisodeSummary] = []
        seasons_dict: Dict[int, List[EpisodeSummary]] = {}
        seen_ep_slugs = set()

        for s_page_url in pages_to_parse:
            s_soup = soup if s_page_url == url else self._get_soup(s_page_url)
            for a in s_soup.find_all("a"):
                href = a.get("href", "")
                if "-bolum" in href:
                    ep_slug = href.strip("/").split("/")[-1]
                    if (
                        ep_slug in seen_ep_slugs
                        or "queen-of-oz" in ep_slug
                        or ep_slug in ("tum-bolumler", "?tip=populer")
                        or not any(char.isdigit() for char in ep_slug)
                    ):
                        continue

                    ep_text = a.get_text(strip=True)
                    # Ignore date links (e.g. "28 Şubat 2013")
                    if any(m in ep_text.lower() for m in ["ocak", "şubat", "subat", "mart", "nisan", "mayıs", "mayis", "haziran", "temmuz", "ağustos", "agustos", "eylül", "eylul", "ekim", "kasım", "kasim", "aralık", "aralik"]):
                        continue

                    seen_ep_slugs.add(ep_slug)

                    s_match = re.search(r"(\d+)-sezon", ep_slug)
                    e_match = re.search(r"(\d+)-bolum", ep_slug)
                    s_num = int(s_match.group(1)) if s_match else 1
                    e_num = int(e_match.group(1)) if e_match else 1

                    ep_title = ep_text or f"{s_num}. Sezon {e_num}. Bölüm"
                    if "tüm bölümler" in ep_title.lower() or "popüler" in ep_title.lower():
                        continue

                    ep_item = EpisodeSummary(
                        title=ep_title,
                        slug=ep_slug,
                        url=href,
                        season_number=s_num,
                        episode_number=e_num,
                    )
                    episodes_list.append(ep_item)
                    seasons_dict.setdefault(s_num, []).append(ep_item)

        # Sort episodes
        episodes_list.sort(key=lambda x: (x.season_number, x.episode_number))
        for s_num in seasons_dict:
            seasons_dict[s_num].sort(key=lambda x: x.episode_number)

        detail = SeriesDetail(
            title=title,
            slug=slug,
            url=url,
            description=desc,
            poster_url=poster_url,
            imdb_rating=imdb_rating,
            genres=genres,
            total_episodes=len(episodes_list),
            seasons=seasons_dict,
            episodes=episodes_list,
        )

        self.cache.set(cache_key, detail, ttl=300)
        return detail

    def get_episode_stream(self, episode_slug_or_url: str) -> EpisodeStreamDetail:
        """Resolve player embed, decrypt MolySTREAM payload and return direct m3u8 stream."""
        slug = episode_slug_or_url.strip("/").split("/")[-1]
        cache_key = f"stream_{slug}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        ep_url = episode_slug_or_url if episode_slug_or_url.startswith("http") else f"{self.base_url}/{slug}/"
        soup = self._get_soup(ep_url)

        title_tag = soup.select_one("h1, title")
        ep_title = title_tag.get_text(strip=True) if title_tag else slug

        # Find player iframe
        iframe = soup.find("iframe")
        if not iframe or not iframe.get("src"):
            raise NotFoundError(f"No player iframe found on episode page: {ep_url}")

        king_url = iframe.get("src")
        r_king = self._request("GET", king_url, headers={"Referer": ep_url})
        soup_king = BeautifulSoup(r_king.content, HTML_PARSER)

        embed_iframe = soup_king.find("iframe")
        if not embed_iframe or not embed_iframe.get("src"):
            raise NotFoundError(f"No embed iframe found inside player: {king_url}")

        embed_url = embed_iframe.get("src")
        r_embed = self._request("GET", embed_url, headers={"Referer": self.base_url})
        soup_embed = BeautifulSoup(r_embed.content, HTML_PARSER)

        # Find encrypted payload in script
        decrypted_html = ""
        for sc in soup_embed.find_all("script"):
            txt = sc.get_text()
            match = re.search(r'CryptoJS\.AES\.decrypt\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"', txt)
            if match:
                ciphertext, key = match.group(1), match.group(2)
                decrypted_html = decrypt_cryptojs_aes(ciphertext, key)
                break

        if not decrypted_html:
            raise DecryptionError(f"Failed to find or decrypt player payload on {embed_url}")

        # Extract file: 'https://dbx.molystream.org/embed/sheila/...'
        m_file = re.search(r'file\s*:\s*[\'"]([^\'"]+)[\'"]', decrypted_html)
        if not m_file:
            raise NotFoundError(f"No stream file URL found in decrypted payload")

        stream_url = m_file.group(1)

        # Subtitles
        subtitles: List[SubtitleTrack] = []
        for m in re.finditer(r'\{[^}]*file\s*:\s*[\'"]([^\'"]+\.(?:vtt|srt))[\'"][^}]*label\s*:\s*[\'"]([^\'"]+)[\'"][^}]*\}', decrypted_html):
            sub_url, label = m.group(1), m.group(2)
            srclang = "tr" if "türk" in label.lower() or "turk" in label.lower() else "en"
            subtitles.append(SubtitleTrack(label=label, srclang=srclang, src=sub_url))

        stream_detail = EpisodeStreamDetail(
            episode_title=ep_title,
            episode_slug=slug,
            stream_url=stream_url,
            embed_url=embed_url,
            king_url=king_url,
            player_url=f"/api/proxy/player/{slug}",
            subtitles=subtitles,
        )

        self.cache.set(cache_key, stream_detail, ttl=300)
        return stream_detail

    def cache_stats(self) -> Dict[str, Any]:
        """Return cache hit/miss statistics."""
        return self.cache.stats()
