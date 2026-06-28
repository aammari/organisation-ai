import anthropic
import json
from app.config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Tu es Claude, Chief Architect de l'Organisation AI.
Tu recois des intentions CEO sous forme d'Executive Requests.
Ton role :
1. Analyser l'intention
2. Decomposer en Work Packages
3. Identifier si une decision CEO (D1/D2/D3) est necessaire
4. Retourner un plan d'action structure en JSON

Format de reponse obligatoire (JSON uniquement) :
{
  "analysis": "analyse de l'intention",
  "work_packages": [
    {
      "title": "titre du WP",
      "description": "description",
      "assigned_to": "claude|chatgpt",
      "priority": "critical|high|medium|low",
      "deliverable": "output attendu"
    }
  ],
  "requires_ceo_decision": false,
  "ceo_decision": null
}
"""

def orchestrate(intention: str, context: dict = {}) -> dict:
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Intention CEO : {intention}\n\nContexte : {context}"
            }
        ]
    )

    raw = message.content[0].text
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)
