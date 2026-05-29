import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.post import SimulationPost, PostType
from app.models.agent import SpawnedAgent


def build_thread_context(posts: list[SimulationPost], agents: dict[str, SpawnedAgent]) -> str:
    lines = []
    for post in posts:
        if post.type == PostType.LIKE:
            continue
        agent = agents.get(post.agent_id)
        name = agent.name if agent else "Unknown"
        role = agent.role if agent else ""
        prefix = f"  > " if post.parent_id else ""
        lines.append(f"{prefix}[{name} | {role}]: {post.content}")
    return "\n\n".join(lines)


async def create_post(
    db: AsyncSession,
    session_id: str,
    agent_id: str,
    post_type: PostType,
    content: Optional[str],
    parent_id: Optional[str],
    round_num: int,
) -> SimulationPost:
    post = SimulationPost(
        id=str(uuid.uuid4()),
        session_id=session_id,
        agent_id=agent_id,
        type=post_type,
        content=content,
        parent_id=parent_id,
        likes=0,
        round_num=round_num,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return post


async def add_like(db: AsyncSession, post_id: str) -> Optional[SimulationPost]:
    result = await db.execute(select(SimulationPost).where(SimulationPost.id == post_id))
    post = result.scalar_one_or_none()
    if post:
        post.likes += 1
        await db.commit()
        await db.refresh(post)
    return post


async def get_posts(db: AsyncSession, session_id: str) -> list[SimulationPost]:
    result = await db.execute(
        select(SimulationPost)
        .where(SimulationPost.session_id == session_id)
        .order_by(SimulationPost.created_at.asc())
    )
    return list(result.scalars().all())
