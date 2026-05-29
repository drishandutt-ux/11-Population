from app.services.knowledge_graph.lightrag_service import get_lightrag, insert_chunks
from app.core.redis_client import publish, session_channel


async def update_graph_from_post(session_id: str, agent_name: str, agent_role: str, content: str):
    text = f"[{agent_name} | {agent_role}]: {content}"
    rag = await get_lightrag(session_id)
    new_entities, new_relations = await insert_chunks(rag, [text])
    if new_entities or new_relations:
        await publish(session_channel(session_id), {
            "type": "kg_updated",
            "new_entities": new_entities,
            "new_relations": new_relations,
            "source": f"{agent_name} ({agent_role})",
        })
