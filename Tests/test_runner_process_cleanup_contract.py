import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestRunnerProcessCleanupContract(unittest.TestCase):
    def test_ps1_runner_has_baseline_snapshot_and_finally_cleanup(self):
        script = (ROOT / "run_auto_agoda_test.ps1").read_text(encoding="utf-8")

        self.assertIn("function Get-AgentEngineProcessIds", script)
        self.assertIn("$baselineAgentPids = Get-AgentEngineProcessIds", script)
        self.assertIn("finally", script)
        self.assertIn("Stop-NewAgentProcesses -BaselineProcessIds $baselineAgentPids", script)

    def test_ps1_runner_cleanup_targets_only_newly_launched_pids(self):
        script = (ROOT / "run_auto_agoda_test.ps1").read_text(encoding="utf-8")

        self.assertIn("$launchedByThisRun = @($current | Where-Object { -not $baseline.ContainsKey($_) })", script)
        self.assertIn("Stop-Process -Id $pid -Force", script)
        self.assertIn("Cleanup: stopped launched agent_engine.py PIDs", script)

    def test_bat_launcher_has_baseline_snapshot_and_cleanup(self):
        script = (ROOT / "Start_Agent_Normal_Mode.bat").read_text(encoding="utf-8")

        self.assertIn('set "BASELINE_AGENT_PIDS="', script)
        self.assertIn("BASELINE_AGENT_PIDS", script)
        self.assertIn('findstr /r "^[0-9][0-9,]*$"', script)
        self.assertIn("Stop-Process -Id $_ -Force", script)
        self.assertIn("Cleanup: stopped launched agent_engine.py PIDs", script)


if __name__ == "__main__":
    unittest.main()
