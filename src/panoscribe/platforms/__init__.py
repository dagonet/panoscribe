"""Platform profile definitions for per-platform UI filtering."""

from panoscribe.platforms.base import GENERIC_PROFILE, PlatformProfile, RelativeRect
from panoscribe.platforms.instagram import INSTAGRAM_PROFILE
from panoscribe.platforms.registry import PROFILES, get_profile, resolve_profile
from panoscribe.platforms.tiktok import TIKTOK_PROFILE
from panoscribe.platforms.youtube import YOUTUBE_PROFILE

__all__ = [
    "GENERIC_PROFILE",
    "INSTAGRAM_PROFILE",
    "PROFILES",
    "TIKTOK_PROFILE",
    "YOUTUBE_PROFILE",
    "PlatformProfile",
    "RelativeRect",
    "get_profile",
    "resolve_profile",
]
