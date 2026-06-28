from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
import anthropic
import openai
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, OPENAI_API_KEY, OPENAI_MODEL

class OrgState(TypedDict):
    ceo_request: str
    intent: Optional[str]
    priority: Optional[str]
    workflow_state: Optional[str]
    architect_output: Optional[str]
    analyst_decision: Optional[str]
    deviation: Optional[dict]
    final_response: Optional[str]

ARCHITECT_SYSTEM_PROMPT = open("prompts/chief_architect.md").read()
ANALYST_SYSTEM_PROMPT = open("prompts/chief_analyst.md").read()

def qualify_intent(state: OrgState) -> OrgState:
    intent_map = {
        "analyse": "ANALYSE",
        "produis": "PRODUCTION",
        "lance": "ACTION",
        "décide": "DECISION"
    }
    request_lower = state["ceo_request"].lower()
    state["intent"] = next(
        (v for k, v in intent_map.items() if k in request_lower),
        "ANALYSE"
    )
    state["priority"] = "P1"
    return state

def call_architect(state: OrgState) -> OrgState:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=ARCHITECT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": state["ceo_request"]}]
    )
    state["architect_output"] = message.content[0].text
    return state

def validate_output(state: OrgState) -> OrgState:
    if not state.get("architect_output"):
        state["deviation"] = {
            "severity": "D2",
            "rule": "MISSING_ARCHITECT_OUTPUT"
        }
        state["analyst_decision"] = "REJECTED"
        return state
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": f"Valide ce livrable:\n\n{state['architect_output']}"}
        ]
    )
    state["analyst_decision"] = "VALIDATED"
    state["final_response"] = state["architect_output"]
    return state

def produce_response(state: OrgState) -> OrgState:
    if not state.get("final_response"):
        state["final_response"] = state.get("architect_output", "Aucun livrable produit.")
    return state

graph = StateGraph(OrgState)
graph.add_node("qualify_intent", qualify_intent)
graph.add_node("call_architect", call_architect)
graph.add_node("validate_output", validate_output)
graph.add_node("produce_response", produce_response)
graph.set_entry_point("qualify_intent")
graph.add_edge("qualify_intent", "call_architect")
graph.add_edge("call_architect", "validate_output")
graph.add_edge("validate_output", "produce_response")
graph.add_edge("produce_response", END)
workflow_app = graph.compile()
