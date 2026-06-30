python -c "
import re

with open('/home/runner/work/organisation-ai/organisation-ai/core/conversation_engine.py', 'r') as f:
    content = f.read()

# Remove the unused comp_score assignment at line 490
# In _wf_footballiq, comp_score is assigned but never used
content = content.replace('    comp_score = plan[\"compliance_score\"]\n', '')

with open('/home/runner/work/organisation-ai/organisation-ai/core/conversation_engine.py', 'w') as f:
    f.write(content)
"
