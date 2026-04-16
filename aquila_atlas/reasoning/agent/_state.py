"""AgentState and route type for the LangGraph agent."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

_RouteType = Literal["structural", "implementation", "analysis", "generation", "diagram", "direct"]


class AgentState(TypedDict):
    """LangGraph state threaded through every node."""

    messages: Annotated[list[BaseMessage], add_messages]
    repo_id: str
    retrieved_context: str
    route: _RouteType
