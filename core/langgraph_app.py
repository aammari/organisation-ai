import os
from typing import TypedDict, Optional
from pathlib import Path
from langgraph.graph import StateGraph, END
import anthropic
import openai
import httpx
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, GROQ_API_KEY, GROQ_MODEL
from core.cost_tracker import CostTracker


def load_kernel() -> str:
    kernel_path = Path(__file__).parent.parent / "docs" / "kernel"
    docs = []
    for f in sorted(kernel_path.glob("*.md")):
        docs.append(f.read_text())
    return "\n\n---\n\n".join(docs)


class OrgState(TypedDict):
    ceo_request: str
    intent: Optional[str]
    priority: Optional[str]
    workflow_state: Optional[str]
    architect_output: Optional[str]
    analyst_decision: Optional[str]
    deviation: Optional[dict]
    execution_result: Optional[dict]
    final_response: Optional[str]


ARCHITECT_SYSTEM_PROMPT = open("prompts/chief_architect.md").read()
ANALYST_SYSTEM_PROMPT = open("prompts/chief_analyst.md").read()


def qualify_intent(state: OrgState) -> OrgState:
    intent_map = {
        "ajoute": "ACTION",
        "crée": "ACTION",
        "lance": "ACTION",
        "exécute": "ACTION",
        "déploie": "ACTION",
        "analyse": "ANALYSE",
        "évalue": "ANALYSE",
        "produis": "PRODUCTION",
        "génère": "PRODUCTION",
        "décide": "DECISION",
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
    system = ARCHITECT_SYSTEM_PROMPT + "\n\n# DOCUMENTS FONDATEURS\n\n" + load_kernel()
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": state["ceo_request"]}]
    )
    state["architect_output"] = message.content[0].text
    try:
        CostTracker().log_cycle(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            model=CLAUDE_MODEL,
        )
    except Exception:
        pass
    return state


def validate_output(state: OrgState) -> OrgState:
    if not state.get("architect_output"):
        state["deviation"] = {"severity": "D2", "rule": "MISSING_ARCHITECT_OUTPUT"}
        state["analyst_decision"] = "REJECTED"
        return state
    client = openai.OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    analyst_system = ANALYST_SYSTEM_PROMPT + "\n\n# DOCUMENTS FONDATEURS\n\n" + load_kernel()
    client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": analyst_system},
            {"role": "user", "content": f"Valide ce livrable:\n\n{state['architect_output']}"}
        ]
    )
    state["analyst_decision"] = "VALIDATED"
    state["final_response"] = state["architect_output"]
    return state


def execute_if_needed(state: OrgState) -> OrgState:
    if state.get("intent") == "ACTION" and state.get("analyst_decision") == "VALIDATED":
        port = os.getenv("PORT", "10000")
        try:
            response = httpx.post(
                f"http://localhost:{port}/execute",
                json={"task": state["architect_output"]},
                timeout=120,
            )
            exec_result = response.json()
            state["execution_result"] = exec_result
            state["final_response"] = (
                f"✅ Exécuté\n\n"
                f"{exec_result.get('explanation', '')}\n\n"
                f"Actions :\n" + "\n".join(f"• {a}" for a in exec_result.get("actions", []))
            )
        except Exception as e:
            state["execution_result"] = {"status": "error", "error": str(e)}
    return state


def produce_response(state: OrgState) -> OrgState:
    if not state.get("final_response"):
        state["final_response"] = state.get("architect_output", "Aucun livrable produit.")
    return state


graph = StateGraph(OrgState)
graph.add_node("qualify_intent", qualify_intent)
graph.add_node("call_architect", call_architect)
graph.add_node("validate_output", validate_output)
graph.add_node("execute_if_needed", execute_if_needed)
graph.add_node("produce_response", produce_response)
graph.set_entry_point("qualify_intent")
graph.add_edge("qualify_intent", "call_architect")
graph.add_edge("call_architect", "validate_output")
graph.add_edge("validate_output", "execute_if_needed")
graph.add_edge("execute_if_needed", "produce_response")
graph.add_edge("produce_response", END)
workflow_app = graph.compile()
