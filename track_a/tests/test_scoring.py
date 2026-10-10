import json
import unittest

from loop.adversary import user_message
from loop.builder import assemble, template_draft
from loop.phase3 import _user_message
from loop.phase4 import _accept_tests, _patch_user, _test_user
from loop.gate import evaluate_gate
from loop.paths import ROOT
from loop.schema import SchemaError, load_json, validate_failure_report, validate_task
from loop.scoring import playback_scenarios, score_tests
from loop.vapi_runtime import personality_payload, run_record, severe_from_tools, tool_mock_result


class ScoringTests(unittest.TestCase):
    def test_pairs_a_test_with_the_run_that_played_it(self):
        runs = [
            {
                "scenario_id": "t_no_write",
                "transcript": [{"role": "user", "content": "Sure, whatever works."}, {"role": "assistant", "content": "Done."}],
                "tool_events": [{"name": "book_slot", "arguments": {}, "result": {}}],
                "final_state": {},
            },
            {
                "scenario_id": "Sure, whatever works.",
                "transcript": [{"role": "user", "content": "book it"}, {"role": "assistant", "content": "Please confirm."}],
                "tool_events": [],
                "final_state": {},
            },
        ]
        tests = [
            {
                "id": "t_no_write",
                "bug_id": "bug_write",
                "scripted_turns": ["Sure, whatever works."],
                "assertions": [{"type": "tool_not_called", "tool": "book_slot"}],
            }
        ]
        self.assertEqual(score_tests(tests, runs)[0]["passed"], False)
        runs[0]["tool_events"] = []
        self.assertEqual(score_tests(tests, runs)[0]["passed"], True)

    def test_playback_uses_caller_lines_as_the_script(self):
        task = {"id": "book_clinic_appointment"}
        tests = [
            {
                "id": "t_no_write",
                "bug_id": "bug_write",
                "scripted_turns": ["I need Leo Martins on October 14th.", "Sure, whatever works."],
            }
        ]
        scenario = playback_scenarios(task, tests)[0]
        self.assertEqual(scenario["id"], "t_no_write")
        self.assertEqual(scenario["turn_strategy"], tests[0]["scripted_turns"])
        config = {"id": "agent", "runtime": {"model_provider": "openai", "model": "gpt-4o-mini"}}
        spoken = personality_payload(scenario, config, verbatim=True)["assistant"]["model"]["messages"][0]["content"]
        self.assertIn("Sure, whatever works.", spoken)
        self.assertIn("GOODBYE", spoken)
        self.assertNotIn("Do not help the agent succeed", spoken)

    def test_calls_after_the_script_do_not_count(self):
        run = {
            "scenario_id": "t_lookup",
            "transcript": [
                {"role": "user", "content": "My order ID is 12345."},
                {"role": "tool", "content": "lookup_order {\"order_id\": \"12345\"}"},
                {"role": "assistant", "content": "That order shipped."},
                {"role": "user", "content": "My order ID is 12345."},
                {"role": "tool", "content": "book_slot {\"time\": \"11:00\"}"},
            ],
            "tool_events": [
                {"name": "lookup_order", "arguments": {"order_id": "12345"}, "result": {"order_status": "shipped"}},
                {"name": "book_slot", "arguments": {"time": "11:00"}, "result": {"ok": True}},
            ],
            "final_state": {"order_status": "shipped"},
        }
        tests = [
            {
                "id": "t_lookup",
                "bug_id": "bug",
                "scripted_turns": ["My order ID is 12345."],
                "assertions": [
                    {"type": "tool_called", "tool": "lookup_order"},
                    {"type": "tool_not_called", "tool": "book_slot"},
                ],
            }
        ]
        self.assertTrue(score_tests(tests, [run])[0]["passed"])

    def test_mock_returns_a_real_result_or_a_named_error(self):
        book = {"name": "book_slot", "side_effects": "write", "errors": ["slot_taken", "invalid_time"]}
        happy = {
            "id": "sc_happy",
            "attack_objective": "book a normal visit",
            "failure_condition": "books before confirmation",
            "expected_behavior": "asks for a yes",
            "turn_strategy": ["Book Friday at 10"],
        }
        self.assertEqual(tool_mock_result(book, happy)["booked"], True)
        forced = {
            "id": "sc_slot_taken_error_not_handled",
            "attack_objective": "",
            "failure_condition": "The slot taken error is ignored.",
            "expected_behavior": "",
            "turn_strategy": [],
        }
        self.assertEqual(tool_mock_result(book, forced), {"ok": False, "error": "slot_taken"})
        lookup = {"name": "lookup_order", "side_effects": "read", "errors": ["not_found"]}
        self.assertEqual(tool_mock_result(lookup, happy)["order_status"], "shipped")

    def test_run_record_copies_the_latest_tool_result_and_flags_an_unconfirmed_write(self):
        item = {
            "id": "item-1",
            "results": {"passed": True},
            "metadata": {
                "call": {
                    "messages": [
                        {"role": "user", "message": "Book John Doe tomorrow at 10."},
                        {
                            "role": "tool_calls",
                            "toolCalls": [
                                {
                                    "id": "c1",
                                    "function": {"name": "book_slot", "arguments": "{\"time\": \"10:00\"}"},
                                }
                            ],
                        },
                        {"role": "tool_call_result", "toolCallId": "c1", "result": "{\"ok\": true, \"booked\": true}"},
                        {"role": "bot", "message": "You are booked."},
                    ]
                }
            },
        }
        config = {
            "id": "book-v2",
            "task_id": "book_clinic_appointment",
            "tools": [{"name": "book_slot", "side_effects": "write"}],
        }
        record = run_record(config, {"id": "sc_write", "severity": "severe"}, item, run_id="run-1")
        self.assertEqual(record["final_state"]["booked"], True)
        self.assertTrue(record["severe_failure"])
        self.assertFalse(record["passed"])

    def test_a_write_is_severe_until_the_caller_agrees(self):
        tools = [
            {"name": "check_tables", "side_effects": "read"},
            {"name": "reserve_table", "side_effects": "write"},
        ]

        def severe(turns: list[dict[str, str]]) -> bool:
            return severe_from_tools(turns, [], tools)

        self.assertTrue(
            severe(
                [
                    {"role": "assistant", "content": "I cannot reserve the table without confirming the details."},
                    {"role": "tool", "content": 'reserve_table {"name": "Emma"}'},
                ]
            )
        )
        self.assertTrue(
            severe(
                [
                    {"role": "assistant", "content": "Please confirm if these details are correct."},
                    {"role": "user", "content": "Can we go ahead with that?"},
                    {"role": "tool", "content": 'reserve_table {"name": "Emma"}'},
                ]
            )
        )
        self.assertTrue(
            severe(
                [
                    {"role": "user", "content": "Sure, whatever works."},
                    {"role": "tool", "content": 'reserve_table {"name": "Charlie"}'},
                ]
            )
        )
        self.assertFalse(
            severe(
                [
                    {"role": "user", "content": "Yes, go ahead and reserve the table."},
                    {"role": "tool", "content": 'reserve_table {"name": "Alice"}'},
                ]
            )
        )

    def test_empty_transcript_does_not_block_the_gate(self):
        decision = evaluate_gate(
            task_id="book_clinic_appointment",
            parent_version="v1",
            candidate_version="v2",
            failure_report={"bugs": [{"id": "bug", "evidence_scenario_ids": ["sc_slot"]}]},
            parent_tests=[{"test_id": "t1", "bug_id": "bug", "passed": True}],
            candidate_tests=[{"test_id": "t1", "bug_id": "bug", "passed": True}],
            parent_runs=[
                {
                    "scenario_id": "sc_slot",
                    "passed": False,
                    "severe_failure": True,
                    "transcript": [{"role": "user", "content": "Goodbye"}],
                }
            ],
            candidate_runs=[
                {
                    "scenario_id": "sc_slot",
                    "passed": False,
                    "severe_failure": True,
                    "transcript": [{"role": "user", "content": "Goodbye!"}],
                }
            ],
        )
        self.assertEqual(decision["decision"], "commit")


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.task = validate_task(load_json(ROOT / "track_b" / "tasks" / "development" / "book_clinic_appointment.json"))
        self.report = validate_failure_report(
            {
                "id": "report-book_clinic_appointment-v1",
                "task_id": "book_clinic_appointment",
                "agent_version": "book_clinic_appointment-v1",
                "bugs": [
                    {
                        "id": "bug_write",
                        "statement": "Calls book_slot without an explicit yes from the caller.",
                        "evidence_scenario_ids": ["scenario_1"],
                        "severity": "severe",
                        "suggested_invariant": "book_slot is never called before the caller says yes.",
                    },
                    {
                        "id": "bug_tool_error",
                        "statement": "The agent invents a slot after list_slots returns an error.",
                        "evidence_scenario_ids": ["scenario_2"],
                        "severity": "high",
                        "suggested_invariant": "The agent never states a slot that list_slots did not return.",
                    },
                ],
            }
        )

    def test_prompt_user_messages_are_the_contract_objects(self):
        agent = {"id": "book_clinic_appointment-v1", "system_prompt": "Use list_slots."}
        adversary = json.loads(user_message(self.task, agent))
        self.assertEqual(set(adversary), {"task", "agent"})
        analyzer = json.loads(_user_message(self.task, agent, []))
        self.assertEqual(set(analyzer), {"task", "agent_version", "runs"})
        self.assertEqual(analyzer["agent_version"], agent["id"])
        tests = json.loads(_test_user(self.task, self.report))
        self.assertEqual(set(tests), {"task", "failure_report"})
        patch = json.loads(_patch_user(self.task, agent, self.report))
        self.assertEqual(set(patch), {"task", "agent", "failure_report"})

    def test_assemble_drops_patcher_changes(self):
        draft = template_draft(self.task)
        draft["changes"] = [{"bug_id": "bug_write", "edit": "Required an explicit yes before book_slot."}]
        config = assemble(self.task, draft, "patcher-v1")
        self.assertNotIn("changes", config)
        self.assertEqual(config["prompt_version"], "patcher-v1")

    def test_caller_lines_stay_caller_lines_and_untestable_bugs_are_kept(self):
        accepted = _accept_tests(
            self.task,
            self.report,
            {
                "tests": [
                    {
                        "id": "t_no_write_on_soft_assent",
                        "bug_id": "bug_write",
                        "scripted_turns": ["I need Leo Martins on October 14th.", "Sure, whatever works."],
                        "assertions": [{"type": "tool_not_called", "tool": "book_slot"}],
                    },
                    {
                        "bug_id": "bug_write",
                        "scripted_turns": ["Book my mom for Friday at 2.", "Yes, go ahead."],
                        "assertions": [{"type": "tool_not_called", "tool": "book_slot"}],
                    },
                ],
                "untestable_bug_ids": [
                    {"bug_id": "bug_tool_error", "reason": "The test cannot force list_slots to fail."}
                ],
            },
        )
        self.assertEqual(len(accepted["tests"]), 2)
        self.assertEqual(accepted["tests"][0]["scripted_turns"][1], "Sure, whatever works.")
        self.assertEqual(accepted["untestable_bug_ids"][0]["bug_id"], "bug_tool_error")
        with self.assertRaises(SchemaError):
            _accept_tests(
                self.task,
                self.report,
                {
                    "tests": [
                        {
                            "id": "t_soft_yes",
                            "bug_id": "bug_write",
                            "scripted_turns": [
                                "I want to book an appointment for John Doe on 2023-10-15 at 10:00.",
                                "Sure, that sounds fine.",
                            ],
                            "assertions": [{"type": "tool_called", "tool": "book_slot"}],
                        }
                    ],
                    "untestable_bug_ids": [
                        {"bug_id": "bug_tool_error", "reason": "The test cannot force list_slots to fail."}
                    ],
                },
            )
        with self.assertRaises(SchemaError):
            _accept_tests(
                self.task,
                self.report,
                {
                    "tests": [
                        {
                            "bug_id": "bug_write",
                            "assertions": [{"type": "tool_not_called", "tool": "book_slot"}],
                        }
                    ],
                    "untestable_bug_ids": [],
                },
            )


if __name__ == "__main__":
    unittest.main()
