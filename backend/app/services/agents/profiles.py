import random
from dataclasses import dataclass, field
from typing import Literal

AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f97316",
    "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6",
    "#a855f7", "#10b981", "#f59e0b", "#ef4444", "#84cc16",
]


@dataclass
class AgentProfile:
    id: str
    session_id: str
    name: str
    age: int
    role: str
    background: str
    stance: Literal["direct", "indirect", "neutral"]
    correlation: str
    personality: list[str]
    debate_style: str
    energy: float = field(default_factory=lambda: round(random.uniform(0.3, 1.0), 2))
    avatar_color: str = field(default_factory=lambda: random.choice(AVATAR_COLORS))
    dials: dict = field(default_factory=dict)
