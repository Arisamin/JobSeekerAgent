import sys

import os
from pathlib import Path

# Restore missing methods from HEAD version of agent_engine.py

def main():
    repo = Path(__file__).parent
    import subprocess
    head_code = subprocess.check_output(['git', 'show', 'HEAD:agent_engine.py'], encoding='utf-8', errors='replace')
    # Extract all methods from HEAD that start with def _build_apply_form_fields ... def _do_linkedin_easy_apply
    import re
    methods = re.findall(r'(def _build_apply_form_fields[\s\S]+?def _do_linkedin_easy_apply[\s\S]+?)(?=^def |\Z)', head_code, re.MULTILINE)
    if not methods:
        print('No methods found to restore.')
        sys.exit(1)
    # Insert into current agent_engine.py after the end of _scan_easy_apply_fields
    agent_path = repo / 'agent_engine.py'
    code = agent_path.read_text(encoding='utf-8')
    insert_point = code.find('def _build_apply_form_fields')
    if insert_point != -1:
        print('Methods already present.')
        sys.exit(0)
    # Find end of _scan_easy_apply_fields
    scan_end = code.find('def _scan_easy_apply_fields')
    scan_end = code.find('return discovered', scan_end)
    scan_end = code.find('\n', scan_end) + 1
    new_code = code[:scan_end] + '\n' + methods[0] + '\n' + code[scan_end:]
    agent_path.write_text(new_code, encoding='utf-8')
    print('Restored methods.')

if __name__ == '__main__':
    main()
