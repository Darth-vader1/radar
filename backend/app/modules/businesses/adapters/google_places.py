from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.modules.businesses.adapters.osm_overpass import NormalizedBusiness
from app.modules.scraping.adapter_base import (
    CollectionMethod,
    DiscoverySeed,
    ExtractedItem,
    RateLimitPolicy,
    RawFetchArtifact,
    SourceAdapter,
    ValidationOutcome,
)
from app.modules.scraping.registry import register_adapter

logger = logging.getLogger("radar.businesses.google_places")


@register_adapter("google_places_api")
class GooglePlacesAdapter(SourceAdapter[NormalizedBusiness]):
    """
    Discovers businesses using the Google Places API (New) Text Search.
    Awaiting configuration if GOOGLE_PLACES_API_KEY is not supplied in environment.
    """

    module_type = "BUSINESS"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ("GOOGLE_PLACES_API_KEY",)

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
        if not api_key:
            logger.warning("Google Places API key is missing. Skipping discovery seed.")
            return

        city = query_params.get("city", "Lagos")
        category = query_params.get("category", "Restaurants")
        text_query = f"{category} in {city}, Nigeria"

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,places.location,places.primaryType,places.types",
        }

        yield DiscoverySeed(
            url="https://places.googleapis.com/v1/places:searchText",
            method="POST",
            headers=headers,
            body={"textQuery": text_query, "pageSize": 20},
            cursor_metadata={"city": city, "category": category},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        if artifact.status_code != 200:
            logger.warning("Google Places API returned status %d", artifact.status_code)
            return [], []

        try:
            payload = json.loads(artifact.body_text)
            places = payload.get("places", [])
        except json.JSONDecodeError:
            return [], []

        items: List[ExtractedItem] = []
        for p in places:
            place_id = p.get("id")
            display_name = p.get("displayName", {}).get("text", "")
            if not display_name:
                continue

            item = ExtractedItem(
                external_id=f"gplaces_{place_id}",
                source_url=f"https://maps.google.com/?cid={place_id}",
                raw_data=p,
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedBusiness:
        p = item.raw_data
        display_name = p.get("displayName", {}).get("text", "").strip()
        address = p.get("formattedAddress")
        phone = p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber")
        website = p.get("websiteUri")
        location = p.get("location", {})
        primary_type = p.get("primaryType", "business")

        # Parse city from address if possible
        city = "Lagos"
        if address and "ikeja" in address.lower():
            city = "Ikeja"
        elif address and "abuja" in address.lower():
            city = "Abuja"

        return NormalizedBusiness(
            name=display_name,
            category=primary_type.replace("_", " ").capitalize(),
            phone_number=phone,
            website_url=website,
            physical_address=address,
            city=city,
            country="Nigeria",
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            raw_tags=p,
        )

    def validate(self, normalized: NormalizedBusiness) -> ValidationOutcome[NormalizedBusiness]:
        errors = []
        if not normalized.name:
            errors.append("Business name is required.")
        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized,
            errors=errors,
        )
