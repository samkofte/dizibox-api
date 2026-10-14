"""Dizibox API Package."""

from dizibox_api.client import DiziboxClient
from dizibox_api.models import (
    SeriesSummary,
    EpisodeSummary,
    SeriesDetail,
    SubtitleTrack,
    EpisodeStreamDetail,
    RecentEpisodeItem,
)
from dizibox_api.exceptions import (
    DiziboxAPIError,
    CloudflareBlockedError,
    NotFoundError,
    ParseError,
    DecryptionError,
)

__all__ = [
    "DiziboxClient",
    "SeriesSummary",
    "EpisodeSummary",
    "SeriesDetail",
    "SubtitleTrack",
    "EpisodeStreamDetail",
    "RecentEpisodeItem",
    "DiziboxAPIError",
    "CloudflareBlockedError",
    "NotFoundError",
    "ParseError",
    "DecryptionError",
]
