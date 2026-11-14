"""
Live Google Places lookup for one business, shown to the user and never stored.

Google's terms allow storing the place ID, so a match found by name search is remembered on the
business (saving a search next time); everything else is returned for display only.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

import httpx

from app.core.config import get_credential
from app.core.http import safe_async_client
from app.models.business import Business

logger = logging.getLogger("radar.businesses.google_lookup")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
DETAIL_FIELDS = ",".join([
    "id", "displayName", "formattedAddress", "nationalPhoneNumber", "internationalPhoneNumber",
    "websiteUri", "googleMapsUri", "rating", "userRatingCount", "businessStatus",
    "regularOpeningHours.weekdayDescriptions", "primaryTypeDisplayName",
])
TIMEOUT_SECONDS = 20.0

# Indirection so tests can supply an httpx.MockTransport.
client_factory: Callable[..., httpx.AsyncClient] = safe_async_client


class GoogleLookupError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class LiveGoogleDetails:
    place_id: str
    matched_by: str  # "place_id" (stored ID) or "search" (best name match: worth a glance)
    name: Optional[str]
    address: Optional[str]
    phone: Optional[str]
    international_phone: Optional[str]
    website: Optional[str]
    google_maps_url: Optional[str]
    rating: Optional[float]
    rating_count: Optional[int]
    business_status: Optional[str]
    category: Optional[str]
    opening_hours: List[str]


def _api_key() -> str:
    key = get_credential("GOOGLE_PLACES_API_KEY")
    if not key:
        raise GoogleLookupError("Google Places isn't set up: add GOOGLE_PLACES_API_KEY to .env.", 400)
    return key


def _google_error(resp: httpx.Response) -> GoogleLookupError:
    try:
        message = resp.json().get("error", {}).get("message", "")
    except ValueError:
        message = ""
    logger.warning("Google Places returned %s: %s", resp.status_code, message[:200])
    return GoogleLookupError(f"Google Places request failed ({resp.status_code}). {message[:160]}".strip(), 502)


def _search_query(business: Business) -> str:
    where = business.physical_address or ", ".join(p for p in (business.city, business.state) if p)
    return ", ".join(p for p in (business.name, where, business.country) if p)[:200]


async def _find_place_id(client: httpx.AsyncClient, key: str, business: Business) -> Optional[str]:
    body: dict[str, Any] = {"textQuery": _search_query(business), "pageSize": 1}
    if business.latitude is not None and business.longitude is not None:
        body["locationBias"] = {"circle": {
            "center": {"latitude": business.latitude, "longitude": business.longitude}, "radius": 500.0,
        }}
    resp = await client.post(SEARCH_URL, json=body, headers={
        "X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.id", "Content-Type": "application/json",
    })
    if resp.status_code != 200:
        raise _google_error(resp)
    places = resp.json().get("places") or []
    return places[0].get("id") if places else None


async def lookup(business: Business) -> LiveGoogleDetails:
    """Fetches current Google details. Sets business.google_place_id when found by search."""
    key = _api_key()
    async with client_factory(timeout=TIMEOUT_SECONDS) as client:
        matched_by = "place_id"
        place_id = business.google_place_id
        if not place_id:
            matched_by = "search"
            place_id = await _find_place_id(client, key, business)
            if not place_id:
                raise GoogleLookupError("No matching place found on Google Maps.", 404)
            business.google_place_id = place_id  # storable indefinitely under Google's terms

        resp = await client.get(DETAILS_URL.format(place_id=place_id), headers={
            "X-Goog-Api-Key": key, "X-Goog-FieldMask": DETAIL_FIELDS,
        })
        if resp.status_code == 404:
            raise GoogleLookupError("Google no longer has this place.", 404)
        if resp.status_code != 200:
            raise _google_error(resp)
        d = resp.json()

    return LiveGoogleDetails(
        place_id=place_id,
        matched_by=matched_by,
        name=(d.get("displayName") or {}).get("text"),
        address=d.get("formattedAddress"),
        phone=d.get("nationalPhoneNumber"),
        international_phone=d.get("internationalPhoneNumber"),
        website=d.get("websiteUri"),
        google_maps_url=d.get("googleMapsUri"),
        rating=d.get("rating"),
        rating_count=d.get("userRatingCount"),
        business_status=d.get("businessStatus"),
        category=(d.get("primaryTypeDisplayName") or {}).get("text"),
        opening_hours=list((d.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []),
    )
