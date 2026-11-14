"""
Who can actually take part in an event, from the point of view of someone based in Nigeria.

Sources store `country` inconsistently (MLH uses ISO-2 codes such as "US", others use names or
nothing), so matching accepts both codes and names, plus city names in the location text.
"""
from typing import Any, Optional

from sqlalchemy import false, func, or_

from app.models.event import DeliveryMode, Event

AFRICA_ISO2 = {
    "dz", "ao", "bj", "bw", "bf", "bi", "cv", "cm", "cf", "td", "km", "cg", "cd", "ci", "dj", "eg", "gq", "er",
    "sz", "et", "ga", "gm", "gh", "gn", "gw", "ke", "ls", "lr", "ly", "mg", "mw", "ml", "mr", "mu", "ma", "mz",
    "na", "ne", "ng", "rw", "st", "sn", "sc", "sl", "so", "za", "ss", "sd", "tz", "tg", "tn", "ug", "zm", "zw",
}
AFRICA_NAMES = {
    "algeria", "angola", "benin", "botswana", "burkina faso", "burundi", "cabo verde", "cape verde", "cameroon",
    "central african republic", "chad", "comoros", "congo", "democratic republic of the congo", "dr congo",
    "côte d'ivoire", "cote d'ivoire", "ivory coast", "djibouti", "egypt", "equatorial guinea", "eritrea",
    "eswatini", "swaziland", "ethiopia", "gabon", "gambia", "the gambia", "ghana", "guinea", "guinea-bissau",
    "kenya", "lesotho", "liberia", "libya", "madagascar", "malawi", "mali", "mauritania", "mauritius",
    "morocco", "mozambique", "namibia", "niger", "nigeria", "rwanda", "sao tome and principe", "senegal",
    "seychelles", "sierra leone", "somalia", "south africa", "south sudan", "sudan", "tanzania", "togo",
    "tunisia", "uganda", "zambia", "zimbabwe", "africa", "pan-africa",
}
AFRICA_KEYS = AFRICA_ISO2 | AFRICA_NAMES
NIGERIA_KEYS = {"ng", "nigeria"}
NIGERIA_PLACES = ("nigeria", "lagos", "abuja", "ibadan", "port harcourt", "kano", "enugu", "ikeja")

# Online or hybrid events can be joined from anywhere unless their rules say otherwise.
REMOTE_MODES = (DeliveryMode.VIRTUAL.value, DeliveryMode.HYBRID.value)

REACH_FROM_NIGERIA = "nigeria"  # online/hybrid, or held somewhere in Africa
REACH_IN_NIGERIA = "in_nigeria"  # held in Nigeria
REACH_ALL = "all"
REACH_VALUES = (REACH_FROM_NIGERIA, REACH_IN_NIGERIA, REACH_ALL)


def _country() -> Any:
    return func.lower(func.trim(func.coalesce(Event.country, "")))


def _location_mentions(places: tuple[str, ...]) -> Any:
    location = func.lower(func.coalesce(Event.location_text, ""))
    return or_(*(location.like(f"%{p}%") for p in places))


def in_nigeria_clause() -> Any:
    return or_(_country().in_(NIGERIA_KEYS), _location_mentions(NIGERIA_PLACES))


def reachable_from_nigeria_clause() -> Any:
    return or_(
        Event.delivery_mode.in_(REMOTE_MODES),
        _country().in_(AFRICA_KEYS),
        in_nigeria_clause(),
    )


def reach_clause(reach: Optional[str]) -> Optional[Any]:
    """SQL filter for a reach value; None means no filter. Unknown values match nothing."""
    if not reach or reach == REACH_ALL:
        return None
    if reach == REACH_FROM_NIGERIA:
        return reachable_from_nigeria_clause()
    if reach == REACH_IN_NIGERIA:
        return in_nigeria_clause()
    return false()
