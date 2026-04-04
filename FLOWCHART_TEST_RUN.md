# Flowchart: Auto Test Run And Teardown

```mermaid
flowchart TD
    A[Start run_auto_agoda_test.ps1] --> B[Read env and runner args]
    B --> C[Snapshot baseline agent_engine.py PIDs]
    C --> D[Run auto_agoda_test_agent.py]

    D --> E{Run outcome}
    E -- PASS --> F[Set exit code = 0]
    E -- FAIL --> G[Set exit code = non-zero]

    F --> H[finally: Stop-NewAgentProcesses]
    G --> H

    H --> I{Any new agent_engine.py PIDs vs baseline?}
    I -- no --> J[No cleanup needed]
    I -- yes --> K[Force-stop only newly launched PIDs]

    J --> L[Print PASS/FAIL and exit]
    K --> L
```

## Notes

- Cleanup is guaranteed via `finally` in `run_auto_agoda_test.ps1`.
- Cleanup scope is diff-based: baseline PID snapshot vs post-run process list.
- Existing agent processes from before the run are preserved.
