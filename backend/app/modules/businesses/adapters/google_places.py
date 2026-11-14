"""
Google Places API (New) Text Search, run by hand only.

Google's terms allow storing place IDs indefinitely but restrict storing other Places content,
so this source is guarded for small, private use:
  * manual only: the scheduler never starts it and it can't be given a schedule;
  * small runs: crawl_budget_pages (20 results per page) caps each run, 3 pages by default;
  * isolated rows: results never merge into businesses from other sources (an existing business
    only gains the Google place ID), so "Remove all Google data" can delete them cleanly;
  * labelled: each business links to its Google Maps listing (googleMapsUri).
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional, Tuple

from app.core.config import get_credential
from app.modules.businesses.adapters.osm_overpass import NormalizedBusiness, OpenStreetMapOverpassAdapter
from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    ExtractedItem,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.registry import register_adapter

logger = logging.getLogger("radar.businesses.google_places")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DEFAULT_QUERY = "restaurants in Ikeja, Lagos"
PAGE_SIZE = 20
SEARCH_FIELDS = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.nationalPhoneNumber",
    "places.internationalPhoneNumber", "places.websiteUri", "places.googleMapsUri", "places.location",
    "places.primaryType", "places.primaryTypeDisplayName", "nextPageToken",
])
GOOGLE_ORIGIN = "google_places"


def city_and_state(address: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Known city (and its state) mentioned in a Google formatted address, most specific first."""
    text = (address or "").lower()
    for area in OpenStreetMapOverpassAdapter.DEFAULT_AREAS:
        if any(name and name in text for name in [area["city"].lower(), *area.get("aliases", [])]):
            return area["city"], area["state"]
    return None, None


def is_google_maps_url(url: Optional[str]) -> bool:
    u = (url or "").lower()
    return "maps.google." in u or "google.com/maps" in u


@register_adapter("google_places_api")
class GooglePlacesAdapter(SourceAdapter[NormalizedBusiness]):
    module_type = "BUSINESS"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ("GOOGLE_PLACES_API_KEY",)

    def _query(self, query_params: dict[str, Any]) -> str:
        query = (query_params.get("query") or "").strip()
        if not query and (query_params.get("category") or query_params.get("city")):
            query = f"{query_params.get('category') or 'businesses'} in {query_params.get('city') or 'Lagos'}"
        query = query or (self.source_config.get("default_query") or DEFAULT_QUERY)
        if "nigeria" not in query.lower():
            query = f"{query}, Nigeria"
        return query[:200]

    @staticmethod
    def _seed(body: dict[str, Any], page: int) -> DiscoverySeed:
        return DiscoverySeed(
            url=SEARCH_URL,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": get_credential("GOOGLE_PLACES_API_KEY") or "",
                "X-Goog-FieldMask": SEARCH_FIELDS,
            },
            body=body,
            cursor_metadata={"page": page, "query": body.get("textQuery")},
        )

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        if not get_credential("GOOGLE_PLACES_API_KEY"):
            logger.warning("Google Places API key is missing. Skipping discovery seed.")
            return
        yield self._seed({"textQuery": self._query(query_params), "pageSize": PAGE_SIZE}, page=1)

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Google Places API returned status %d: %s", artifact.status_code, artifact.body_text[:300])
            return [], []
        try:
            payload = json.loads(artifact.body_text)
        except json.JSONDecodeError:
            return [], []

        items: List[ExtractedItem] = []
        for p in payload.get("places", []) or []:
            place_id = p.get("id")
            if not place_id or not (p.get("displayName") or {}).get("text"):
                continue
            items.append(ExtractedItem(
                external_id=f"gplaces_{place_id}",
                source_url=p.get("googleMapsUri") or f"https://www.google.com/maps/place/?q=place_id:{place_id}",
                raw_data=p,
                discovered_at=datetime.now(timezone.utc),
            ))

        # Follow nextPageToken while the run's page budget allows (the pipeline enforces it).
        next_seeds: list[DiscoverySeed] = []
        token = payload.get("nextPageToken")
        seed = artifact.seed
        if token and seed and isinstance(seed.body, dict):
            body = {k: v for k, v in seed.body.items() if k != "pageToken"}
            next_seeds.append(self._seed({**body, "pageToken": token}, page=int(seed.cursor_metadata.get("page", 1)) + 1))
        return items, next_seeds

    def normalize(self, item: ExtractedItem) -> NormalizedBusiness:
        p = item.raw_data
        address = p.get("formattedAddress")
        city, state = city_and_state(address)
        location = p.get("location") or {}
        category = (p.get("primaryTypeDisplayName") or {}).get("text") or (
            (p.get("primaryType") or "business").replace("_", " ").capitalize()
        )
        return NormalizedBusiness(
            name=(p.get("displayName") or {}).get("text", "").strip(),
            category=category,
            phone_number=p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber"),
            website_url=p.get("websiteUri"),
            physical_address=address,
            city=city,
            state=state,
            country="Nigeria",
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            google_place_id=p.get("id"),
            data_origin=GOOGLE_ORIGIN,
        )

    def validate(self, normalized: NormalizedBusiness) -> ValidationOutcome[NormalizedBusiness]:
        errors = []
        if not normalized.name:
            errors.append("Business name is required.")
        if not normalized.google_place_id:
            errors.append("Google place ID is required.")
        return ValidationOutcome(is_valid=not errors, record=normalized if not errors else None, errors=errors)
