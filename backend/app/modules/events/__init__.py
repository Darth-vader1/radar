from app.modules.events.adapters.devpost import DevpostHackathonsAdapter
from app.modules.events.adapters.kaggle import KaggleCompetitionsAdapter
from app.modules.events.adapters.mlh import MLHEventsAdapter
from app.modules.events.adapters.zindi import ZindiCompetitionsAdapter

__all__ = [
    "DevpostHackathonsAdapter",
    "ZindiCompetitionsAdapter",
    "KaggleCompetitionsAdapter",
    "MLHEventsAdapter",
]
