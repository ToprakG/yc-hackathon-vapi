import json
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

from loop.cli import main
from loop.paths import ROOT
from loop.phase2 import run_phase2
from loop.vapi_runtime import VapiRuntime
from test_loop import link_track_b


def ended_transport(calls: list):
    pending: list[str] = []
    runs = {"n": 0}

    def transport(method, url, body, headers):
        calls.append((method, url, body))
        path = url.rstrip("/")
        if method == "POST" and path.endswith("/eval/simulation"):
            simulation_id = f"sim_{len(pending)}"
            pending.append(simulation_id)
            return 201, {"id": simulation_id}
        if method == "POST" and path.endswith("/eval/simulation/run"):
            runs["n"] += 1
            return 201, {"id": f"run_{runs['n']}"}
        if method == "GET" and "/eval/simulation/run/run_" in path and not path.endswith("/item"):
            return 200, {"status": "ended"}
        if method == "GET" and path.endswith("/item"):
            results = [
                {
                    "id": f"item_{simulation_id}",
                    "simulationId": simulation_id,
                    "results": {"passed": True},
                    "messages": [
                        {"role": "user", "content": "Hello"},
                        {"role": "bot", "message": "What details should I use?"},
                    ],
                }
                for simulation_id in pending
            ]
            pending.clear()
            return 200, {"results": results}
        return 201, {"id": f"id_{len(calls)}"}

    return transport


class Phase2Tests(unittest.TestCase):
    def test_phase2_stops_before_vapi_and_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link_track_b(root)
            self.assertEqual(main(["build", "--mock", "--root", str(root)]), 0)
            output = StringIO()
            with redirect_stdout(output):
                code = main(["phase2", "--mock", "--root", str(root)])
            self.assertEqual(code, 0)
            text = output.getvalue()
            self.assertIn("Vapi testing is the next step", text)
            self.assertIn("regression gate does not run", text)
            self.assertFalse((root / "shared" / "runs").exists())
            tasks = json.loads(
                (ROOT / "track_b" / "tasks" / "development" / "book_clinic_appointment.json").read_text()
            )
            bundle = json.loads(
                (root / "shared" / "versions" / tasks["id"] / "v1" / "scenarios.json").read_text()
            )
            self.assertEqual(len(bundle["scenarios"]), 3)
            self.assertEqual(bundle["prompt_version"], "mock-adversary")
            self.assertFalse((root / "shared" / "runs" / tasks["id"] / "gate.json").exists())

    def test_simulate_writes_transcripts_without_a_gate_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link_track_b(root)
            self.assertEqual(main(["build", "--mock", "--root", str(root)]), 0)
            self.assertEqual(main(["phase2", "--mock", "--root", str(root)]), 0)
            for path in (root / "shared" / "versions").glob("*/v1"):
                (path / "runtime_binding.json").write_text(
                    json.dumps({"provider": "vapi", "assistant_id": "asst_test", "agent_version": path.parent.name + "-v1"})
                    + "\n"
                )
            calls = []
            runtime = VapiRuntime(api_key="secret-key", transport=ended_transport(calls))
            output = StringIO()
            with redirect_stdout(output):
                code = run_phase2(root, simulate=True, runtime=runtime)
            self.assertEqual(code, 0, output.getvalue())
            transcripts = list((root / "shared" / "runs").glob("*/*/*.json"))
            self.assertEqual(len(transcripts), 9)
            self.assertFalse(list((root / "shared" / "runs").glob("**/gate*.json")))
            self.assertTrue(any(url.endswith("/eval/simulation/run") for _method, url, _body in calls))


if __name__ == "__main__":
    unittest.main()
