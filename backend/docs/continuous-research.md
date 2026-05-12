1. **Continuous pipeline is effectively off right now.**  
`gateway` startup shows scheduler did not start: [gateway.log:14](/Users/ryan_chua/Desktop/capybara-home/logs/gateway.log:14) (`Control-plane scheduler disabled; skipping start.`).  
So daily autoresearch jobs will not run continuously even if objectives exist.

2. **Current objective says `active`, but its runtime schedule is disabled.**  
The objective is `active` at [state.json:2579](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:2579), but its runtime job has `"enabled": false` at [state.json:2563](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:2563).  
This creates a “looks active but not actually running” state in the Knowledge Vault tab.

3. **Template/state migration bug: persisted templates are stale.**  
Seeder only inserts templates if missing and never updates existing ones ([service.py:101](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/service.py:101)-[109](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/service.py:109)).  
Your persisted `knowledge-vault-autoresearch` template only has discover/ingest/compile/lint ([state.json:71](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:71)-[113](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:113)), while code now defines extra steps (graph synthesis + sufficiency). This can prevent progress logic from ever being reached.

4. **Progress is hardcoded to 0% in both backend ledger and frontend UI.**  
Backend writes `"progress_percent": 0.0` and markdown `0% (default)` unconditionally at [autoresearch_agent.py:490](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/agents/autoresearch_agent.py:490) and [autoresearch_agent.py:526](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/agents/autoresearch_agent.py:526).  
Frontend also hardcodes `0% (default)` at [page.tsx:170](/Users/ryan_chua/Desktop/capybara-home/frontend/src/app/workspace/vault/page.tsx:170).  
So the “current task” appears stuck even after successful runs.

5. **Queue approval pipeline has a step-definition mismatch bug (already seen in persisted failed run).**  
`start_run` fails when a step exists but definition is missing ([service.py:995](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/service.py:995)-[1005](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/service.py:1005)).  
In persisted run `run_9ee44d38ed1c`, step `queue-lint` failed with `"Step definition not found."` at [state.json:304](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:304)-[310](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:310), while metadata only had `queue-ingest` + `queue-compile` definitions ([state.json:332](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:332)-[344](/Users/ryan_chua/Desktop/capybara-home/backend/.capybara-home/control-plane/state.json:344)).  
This is consistent with update logic mutating step definitions without reconciling existing run steps ([service.py:1357](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/service.py:1357)-[1386](/Users/ryan_chua/Desktop/capybara-home/backend/src/control_plane/service.py:1386)).

