"""Data models for Dizibox API responses."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class SeriesSummary:
    """Summary of a TV series."""
    title: str
    slug: str
    url: str
    poster_url: Optional[str] = None
    imdb_rating: Optional[float] = None
    genres: List[str] = field(default_factory=list)
    year: Optional[str] = None


@dataclass
class EpisodeSummary:
    """Summary of a TV episode."""
    title: str
    slug: str
    url: str
    season_number: int
    episode_number: int
    release_date: Optional[str] = None
    thumbnail_url: Optional[str] = None


@dataclass
class SeriesDetail:
    """Full detail of a TV series."""
    title: str
    slug: str
    url: str
    description: Optional[str] = None
    poster_url: Optional[str] = None
    imdb_rating: Optional[float] = None
    genres: List[str] = field(default_factory=list)
    creator: Optional[str] = None
    cast: List[str] = field(default_factory=list)
    total_episodes: int = 0
    seasons: Dict[int, List[EpisodeSummary]] = field(default_factory=dict)
    episodes: List[EpisodeSummary] = field(default_factory=list)


@dataclass
class SubtitleTrack:
    """Subtitle track information."""
    label: str
    srclang: str
    src: str


@dataclass
class EpisodeStreamDetail:
    """Streaming details extracted from episode embed."""
    episode_title: str
    episode_slug: str
    stream_url: str
    embed_url: Optional[str] = None
    king_url: Optional[str] = None
    player_url: Optional[str] = None
    subtitles: List[SubtitleTrack] = field(default_factory=list)
    next_episode_url: Optional[str] = None
    prev_episode_url: Optional[str] = None


@dataclass
class RecentEpisodeItem:
    """Item in recent episodes feed."""
    title: str
    episode_slug: str
    series_title: str
    season_number: int
    episode_number: int
    url: str
    thumbnail_url: Optional[str] = None
    badge: Optional[str] = None  # e.g., "Altyazılı", "Dublaj"
