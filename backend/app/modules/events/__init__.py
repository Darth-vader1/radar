from app.modules.events.adapters.devpost import DevpostHackathonsAdapter
from app.modules.events.adapters.zindi import ZindiCompetitionsAdapter
from app.modules.events.adapters.kaggle import KaggleCompetitionsAdapter
from app.modules.events.adapters.mlh import MLHEventsAdapter

__all__ = [
    "DevpostHackathonsAdapter",
    "ZindiCompetitionsAdapter",
    "KaggleCompetitionsAdapter",
    "MLHEventsAdapter",
]
