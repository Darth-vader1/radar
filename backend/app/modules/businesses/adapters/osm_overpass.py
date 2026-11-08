from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

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

logger = logging.getLogger("radar.businesses.osm_overpass")


class NormalizedBusiness(BaseModel):
    name: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    phone_number: Optional[str] = None
    website_url: Optional[str] = None
    physical_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "Nigeria"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    raw_tags: Dict[str, Any] = Field(default_factory=dict)


@register_adapter("osm_overpass")
class OpenStreetMapOverpassAdapter(SourceAdapter[NormalizedBusiness]):
    """
    Discovers businesses and commercial POIs using the official OpenStreetMap Overpass API.
    Zero API key required; covers Lagos (Ikeja, VI, Lekki, Yaba), Abuja, and global cities.
    """

    module_type = "BUSINESS"
    collection_method = CollectionMethod.OFFICIAL_API
    required_env_vars = ()

    # Default bounding boxes / area queries for Nigerian commercial hubs
    DEFAULT_AREAS = [
        {"city": "Ikeja", "state": "Lagos", "bbox": "6.5700,3.3300,6.6200,3.3700"},
        {"city": "Lagos Island / Victoria Island", "state": "Lagos", "bbox": "6.4100,3.3900,6.4600,3.4600"},
        {"city": "Abuja Central", "state": "Federal Capital Territory", "bbox": "9.0300,7.4600,9.0900,7.5200"},
    ]

    async def discover(self, query_params: dict[str, Any]) -> AsyncIterator[DiscoverySeed]:
        city_param = query_params.get("city", "Ikeja")
        category_param = query_params.get("category", "Restaurants")

        # Overpass QL query: extract amenities, shops, and offices in target area
        bbox = "6.5700,3.3300,6.6200,3.3700"  # Default Ikeja
        for area in self.DEFAULT_AREAS:
            if area["city"].lower() in city_param.lower():
                bbox = area["bbox"]
                break

        overpass_ql = f"""
        [out:json][timeout:25];
        (
          node["amenity"~"restaurant|cafe|fast_food|pharmacy|hospital|clinic|bank"]({bbox});
          node["shop"]({bbox});
          node["office"]({bbox});
        );
        out body 100;
        >;
        out skel qt;
        """

        yield DiscoverySeed(
            url="https://overpass-api.de/api/interpreter",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=f"data={overpass_ql.strip()}",
            cursor_metadata={"city": city_param, "country": "Nigeria"},
        )

    async def extract(self, artifact: RawFetchArtifact) -> Tuple[list[ExtractedItem], list[DiscoverySeed]]:
        items: List[ExtractedItem] = []
        if artifact.status_code != 200:
            logger.warning("Overpass API returned status %d", artifact.status_code)
            return [], []

        try:
            payload = json.loads(artifact.body_text)
            elements = payload.get("elements", [])
        except json.JSONDecodeError as exc:
            logger.error("Failed parsing Overpass JSON: %s", exc)
            return [], []

        for elem in elements:
            tags = elem.get("tags", {})
            name = tags.get("name")
            if not name:
                continue

            node_id = str(elem.get("id"))
            item = ExtractedItem(
                external_id=f"osm_node_{node_id}",
                source_url=f"https://www.openstreetmap.org/node/{node_id}",
                raw_data={
                    "osm_id": node_id,
                    "name": name,
                    "lat": elem.get("lat"),
                    "lon": elem.get("lon"),
                    "tags": tags,
                    "metadata": artifact.seed.cursor_metadata,
                },
                discovered_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items, []

    def normalize(self, item: ExtractedItem) -> NormalizedBusiness:
        raw = item.raw_data
        tags = raw.get("tags", {})
        meta = raw.get("metadata", {})

        name = raw.get("name", "").strip()

        # Category resolution from OSM tags
        category = tags.get("amenity") or tags.get("shop") or tags.get("office") or "business"
        subcategory = tags.get("cuisine") or tags.get("healthcare") or tags.get("service")

        # Contact info
        phone = tags.get("phone") or tags.get("contact:phone") or tags.get("mobile")
        website = tags.get("website") or tags.get("contact:website") or tags.get("url")

        # Address resolution
        street = tags.get("addr:street") or tags.get("addr:housename") or ""
        city = tags.get("addr:city") or meta.get("city", "Lagos")
        state = tags.get("addr:state") or meta.get("state", "Lagos")
        country = tags.get("addr:country") or meta.get("country", "Nigeria")

        address_parts = [p for p in [tags.get("addr:housenumber"), street, city, state] if p]
        physical_address = ", ".join(address_parts) if address_parts else None

        return NormalizedBusiness(
            name=name,
            category=category.replace("_", " ").capitalize(),
            subcategory=subcategory.capitalize() if subcategory else None,
            phone_number=phone,
            website_url=website,
            physical_address=physical_address,
            city=city,
            state=state,
            country=country,
            latitude=raw.get("lat"),
            longitude=raw.get("lon"),
            raw_tags=tags,
        )

    def validate(self, normalized: NormalizedBusiness) -> ValidationOutcome[NormalizedBusiness]:
        errors = []
        if not normalized.name or len(normalized.name.strip()) < 2:
            errors.append("Business name is empty or too short.")

        if not normalized.country:
            errors.append("Country field is required.")

        return ValidationOutcome(
            is_valid=len(errors) == 0,
            record=normalized,
            errors=errors,
        )
