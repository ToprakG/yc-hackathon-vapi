import json
import os
import tempfile
import unittest
from pathlib import Path

from loop.builder import build_agent, template_draft
from loop.cli import main
from loop.gate import evaluate_gate
from loop.llm import extract_chat_text, parse_json_object
from loop.paths import ROOT
from loop.schema import SchemaError, load_json, validate_agent, validate_task
from loop.store import load_development_tasks
from loop.vapi_runtime import VapiRuntime, assistant_payload


def link_track_b(root: Path) -> None:
    destination = root / "track_b"
    destination.mkdir()
    os.symlink(ROOT / "track_b" / "tasks", destination / "tasks")
    os.symlink(ROOT / "track_b" / "prompts", destination / "prompts")


class GateTests(unittest.TestCase):
    def test_phase0_command_commits_and_discards(self):
        self.assertEqual(main(["phase0", "--root", str(ROOT)]), 0)
        commit = json.loads((ROOT / "shared" / "runs" / "phase0" / "commit.json").read_text())
        discard = json.loads((ROOT / "shared" / "runs" / "phase0" / "discard.json").read_text())
        self.assertEqual(commit["decision"], "commit")
        self.assertEqual(discard["decision"], "discard")
        self.assertIn("New severe failure on persona_happy", discard["reason"])

    def test_regressed_test_discards(self):
        decision = evaluate_gate(
            task_id="fixture_booking",
            parent_version="v1",
            candidate_version="v2",
            failure_report={
                "bugs": [
                    {
                        "id": "bug_skip_confirm",
                        "evidence_scenario_ids": ["persona_missing_confirm"],
                    }
                ]
            },
            parent_tests=[
                {"test_id": "t_list_slots", "bug_id": "bug_old_lookup", "passed": True},
                {"test_id": "t_confirm_before_book", "bug_id": "bug_skip_confirm", "passed": False},
            ],
            candidate_tests=[
                {"test_id": "t_list_slots", "bug_id": "bug_old_lookup", "passed": False},
                {"test_id": "t_confirm_before_book", "bug_id": "bug_skip_confirm", "passed": True},
            ],
            parent_runs=[{"scenario_id": "persona_missing_confirm", "passed": False, "severe_failure": True}],
            candidate_runs=[{"scenario_id": "persona_missing_confirm", "passed": True, "severe_failure": False}],
        )
        self.assertEqual(decision["decision"], "discard")
        self.assertIn("regressed", decision["reason"])


class BuildTests(unittest.TestCase):
    def test_development_tasks_and_mock_v1(self):
        tasks = load_development_tasks(ROOT)
        self.assertEqual(
            [task["id"] for task in tasks],
            ["book_clinic_appointment", "reserve_table", "track_order"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link_track_b(root)
            code = main(["build", "--mock", "--root", str(root)])
            self.assertEqual(code, 0)
            for task in tasks:
                config = validate_agent(
                    load_json(root / "shared" / "versions" / task["id"] / "v1" / "agent_config.json"),
                    task,
                )
                self.assertEqual(config["prompt_version"], "mock-builder")
                self.assertEqual(config["parent_id"], None)
                self.assertEqual((root / "shared" / "versions" / task["id"] / "BEST").read_text().strip(), "v1")
                payload = assistant_payload(config)
                self.assertEqual(payload["model"]["messages"][0]["role"], "system")
                self.assertEqual(payload["firstMessage"], config["first_message"])
                self.assertEqual(
                    [tool["function"]["name"] for tool in payload["model"]["tools"]],
                    [tool["name"] for tool in task["tools"]],
                )

    def test_llm_repair_then_store(self):
        task = validate_task(load_json(ROOT / "track_b" / "tasks" / "development" / "track_order.json"))

        class Scripted:
            def __init__(self):
                self.calls = 0

            def complete(self, *, system, user):
                self.calls += 1
                if self.calls == 1:
                    return "not json"
                return json.dumps(template_draft(task))

        llm = Scripted()
        config = build_agent(task, prompt_text="prompt", prompt_version="builder-v1", llm=llm)
        self.assertEqual(config["id"], "track_order-v1")
        self.assertEqual(llm.calls, 2)

    def test_builder_rejects_renamed_tool(self):
        task = validate_task(load_json(ROOT / "track_b" / "tasks" / "development" / "track_order.json"))
        draft = template_draft(task)
        draft["tools"][0]["name"] = "lookup_something_else"
        with self.assertRaises(SchemaError):
            build_agent(task, prompt_text="prompt", prompt_version="builder-v1", draft=draft)

    def test_holdout_is_unreadable(self):
        with self.assertRaises(RuntimeError):
            load_json(ROOT / "track_b" / "tasks" / "holdout" / "secret.json")


class VapiAdapterTests(unittest.TestCase):
    def test_publish_posts_assistant_and_patch_updates(self):
        task = validate_task(load_json(ROOT / "track_b" / "tasks" / "development" / "track_order.json"))
        config = build_agent(
            task,
            prompt_text="prompt",
            prompt_version="builder-v1",
            draft=template_draft(task),
        )
        calls = []

        def transport(method, url, body, headers):
            calls.append((method, url, body, headers["Authorization"]))
            return 201, {"id": "asst_123"}

        runtime = VapiRuntime(api_key="secret-key", transport=transport)
        binding = runtime.publish(config)
        self.assertEqual(binding["assistant_id"], "asst_123")
        method, url, body, auth = calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/assistant"))
        self.assertEqual(auth, "Bearer secret-key")
        self.assertNotIn("secret-key", json.dumps(body))
        self.assertEqual(body["model"]["tools"][0]["type"], "function")
        self.assertEqual(body["voice"]["voiceId"], "Elliot")

        runtime.publish(config, existing_id="asst_123")
        self.assertEqual(calls[1][0], "PATCH")
        self.assertTrue(calls[1][1].endswith("/assistant/asst_123"))

    def test_publish_command_uses_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link_track_b(root)
            self.assertEqual(main(["build", "--mock", "--root", str(root)]), 0)
            calls = []

            def transport(method, url, body, headers):
                calls.append(url)
                return 201, {"id": f"asst_{len(calls)}"}

            # Patch the class used by the CLI.
            import loop.cli as cli

            original = cli.VapiRuntime.from_env

            def from_env():
                return VapiRuntime(api_key="secret-key", transport=transport)

            cli.VapiRuntime.from_env = staticmethod(from_env)
            try:
                os.environ["VAPI_API_KEY"] = "secret-key"
                code = main(["publish", "--root", str(root)])
            finally:
                cli.VapiRuntime.from_env = original
                os.environ.pop("VAPI_API_KEY", None)
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 3)
            cli.VapiRuntime.from_env = staticmethod(from_env)
            try:
                os.environ["VAPI_API_KEY"] = "secret-key"
                before = len(calls)
                code = main(["publish", "--root", str(root)])
            finally:
                cli.VapiRuntime.from_env = original
                os.environ.pop("VAPI_API_KEY", None)
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), before)

    def test_chat_text_and_json_extraction(self):
        text = extract_chat_text({"output": [{"role": "assistant", "content": '{"system_prompt": "x"}'}]})
        self.assertEqual(parse_json_object("```json\n" + text + "\n```")["system_prompt"], "x")
        dropped = '"system_prompt": "Stay brief.", "first_message": "Hello there."}'
        self.assertEqual(parse_json_object(dropped)["first_message"], "Hello there.")

    def test_simulate_posts_a_webchat_suite(self):
        task = validate_task(load_json(ROOT / "track_b" / "tasks" / "development" / "track_order.json"))
        config = build_agent(
            task,
            prompt_text="prompt",
            prompt_version="builder-v1",
            draft=template_draft(task),
        )
        from loop.adversary import mock_scenarios

        scenarios = mock_scenarios(task)
        calls = []
        simulation_index = {"n": 0}

        def transport_stable(method, url, body, headers):
            calls.append((method, url, body))
            if method == "POST" and url.endswith("/eval/simulation"):
                simulation_index["n"] += 1
                return 201, {"id": f"sim_{simulation_index['n'] - 1}"}
            if method == "POST" and url.endswith("/eval/simulation/run"):
                return 201, {"id": "run_1"}
            if method == "GET" and url.endswith("/eval/simulation/run/run_1"):
                return 200, {"status": "ended"}
            if method == "GET" and url.endswith("/item"):
                return 200, {
                    "results": [
                        {
                            "id": f"item_{index}",
                            "simulationId": f"sim_{index}",
                            "results": {"passed": index != 0},
                            "messages": [
                                {"role": "user", "content": "Where is my order?"},
                                {
                                    "role": "tool_calls",
                                    "toolCalls": [
                                        {"function": {"name": "lookup_order", "arguments": {"order_id": "1"}}}
                                    ],
                                },
                                {"role": "bot", "message": "I could not find that order."},
                            ],
                        }
                        for index in range(len(scenarios))
                    ]
                }
            return 201, {"id": f"id_{len(calls)}"}

        runtime = VapiRuntime(api_key="secret-key", transport=transport_stable)
        runs = runtime.simulate(config, scenarios, "asst_1", task, sleep=lambda _seconds: None)
        self.assertEqual(len(runs), 3)
        run_call = next(body for method, url, body in calls if method == "POST" and url.endswith("/eval/simulation/run"))
        self.assertEqual(run_call["transport"]["provider"], "vapi.webchat")
        self.assertEqual(run_call["target"]["assistantId"], "asst_1")
        self.assertTrue(runs[0]["severe_failure"] is False)
        self.assertEqual(runs[0]["tool_events"][0]["name"], "lookup_order")
        self.assertTrue(any(turn["role"] == "assistant" for turn in runs[0]["transcript"]))


if __name__ == "__main__":
    unittest.main()
