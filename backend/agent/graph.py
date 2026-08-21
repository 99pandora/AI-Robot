"""最小 LangGraph 闭环：模型决策 -> 工具调用 -> 模型整理答案。"""

from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from backend.agent.tools import build_tools
from backend.knowledge.service import DocumentService


SYSTEM_PROMPT = """你是小苏，公司内部 AI 助手。
根据用户问题自主选择工具，不要按关键词硬编码业务分流。
涉及公司制度、福利、流程或知识库事实时，必须先调用 search_knowledge；没有检索到证据就明确拒答，不要编造。
涉及考勤或订单时调用对应工具，并基于工具返回的数据回答。
回答简洁、准确；不要暴露工具调用过程。"""


class AgentState(TypedDict):
    """图中传递的状态；add_messages 会按消息 ID 合并历史。"""

    messages: Annotated[list[BaseMessage], add_messages]


def build_graph(model: BaseChatModel, knowledge: DocumentService):
    """构建一次请求使用的 Agent 图和工具节点。"""
    tools = build_tools(knowledge)
    model_with_tools = model.bind_tools(tools)

    async def call_model(state: AgentState) -> dict[str, list[BaseMessage]]:
        """让模型决定直接回答，或生成下一次工具调用。"""
        response = await model_with_tools.ainvoke(
            [{"role": "system", "content": SYSTEM_PROMPT}, *state["messages"]]
        )
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    # tools_condition 根据模型是否产生 tool_calls 自动选择工具节点或结束。
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile()
