python -c "
import re

with open('/home/runner/work/organisation-ai/organisation-ai/core/conversation_engine.py', 'r') as f:
    content = f.read()

# Remove the unused comp_score assignment at line 382 in _wf_footballiq
# The line is: comp_score = plan[\"compliance_score\"]
content = content.replace('    comp_score = plan[\"compliance_score\"]\n', '')

with open('/home/runner/work/organisation-ai/organisation-ai/core/conversation_engine.py', 'w') as f:
    f.write(content)
"
