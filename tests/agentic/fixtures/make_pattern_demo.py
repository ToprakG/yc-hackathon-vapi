"""Regenerate pattern_demo.openapi.json and pattern_demo.workflow.json.

Every value here is invented: Example Bank, 2031 dates, enums such as outcome_x. The workflow shows the patterns of the
skill's cookbook and must lint with 0 errors against its own tool API (tests/agentic/test_pattern_demo.py). It is
copied into the builder's workspace as the example; the kit's base-agent.json is not (it carries Brief A's values).

    python3 tests/agentic/fixtures/make_pattern_demo.py
"""

import ast
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAL = HERE.parents[2] / "builder" / "agentic" / "skill" / "build-collections-agent" / "templates" / "calendar.py"
BASE = "https://api.example-bank.invalid/v1"
FAIL_500 = {"description": "The service failed. Nothing was recorded. The call may be repeated."}


def helpers(*names):
    """Source of the named calendar.py functions, plus the imports and constants they need."""
    src = CAL.read_text()
    tree = ast.parse(src)
    defs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    wanted, todo = set(), list(names)
    while todo:  # add the helpers each wanted helper calls
        name = todo.pop()
        if name in wanted:
            continue
        wanted.add(name)
        todo += [x.id for x in ast.walk(defs[name]) if isinstance(x, ast.Name) and x.id in defs]
    keep = [ast.get_source_segment(src, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    return "import datetime\nimport json\nimport re\n\nWEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']\n" \
           "MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']\n\n" \
           + "\n\n".join(keep) + "\n\n"


def op(summary, req, required, resp):
    return {"post": {"summary": summary,
                     "requestBody": {"required": True, "content": {"application/json": {"schema": {
                         "type": "object", "properties": req, "required": required}}}},
                     "responses": {"200": {"description": "`ok` is false when the action was not carried out.",
                                           "content": {"application/json": {"schema": {"type": "object", "properties": resp}}}},
                                   "500": FAIL_500}}}


S, N, I, B = {"type": "string"}, {"type": "number"}, {"type": "integer"}, {"type": "boolean"}
OKERR = {"ok": B, "error": S}
API = {
    "openapi": "3.0.3",
    "info": {"title": "Example Bank tools (invented, for the pattern demo)", "version": "1"},
    "servers": [{"url": BASE}],
    "paths": {
        "/verify_identity": op("Check one security answer.", {
            "customer_id": S, "question": {"type": "string", "enum": ["member_code", "birth_month"]},
            "reply": {"type": "string", "description": "member_code: six digits. birth_month: the month as a number 1-12."}},
            ["customer_id", "question", "reply"],
            {**OKERR, "verified": B, "tries_left": I, "all_passed": B, "hint": {"type": "string", "enum": ["digits_missing"]}}),
        "/get_account": op("The late items. One or two.", {"customer_id": S}, ["customer_id"], {**OKERR, "items": {
            "type": "array", "items": {"type": "object", "properties": {
                "item_ref": S, "kind": {"type": "string", "enum": ["kind_a", "kind_b"]}, "ending": S,
                "overdue": N, "days_over": I, "floor_amount": N}}}}),
        "/create_promise": op("Record one promise. One per item.", {
            "customer_id": S, "item_ref": S, "amount_minor": {"type": "integer", "description": "Amount in minor units."},
            "pay_on": {"type": "string", "format": "date"}}, ["customer_id", "item_ref", "amount_minor", "pay_on"],
            {**OKERR, "promise_ref": S}),
        "/add_note": op("Record why an item ended without a promise.", {
            "customer_id": S, "item_ref": S, "code": {"type": "string", "enum": ["note_x", "note_y", "note_z"]}, "text": S},
            ["customer_id", "item_ref", "code"], OKERR),
        "/schedule_callback": op("Book a callback.", {"customer_id": S, "slot": {"type": "string", "description": "YYYY-MM-DDTHH:MM"}},
                                 ["customer_id", "slot"], OKERR),
        "/transfer_to_agent": op("Hand the call to a desk.", {"customer_id": S, "desk": {"type": "string", "enum": ["desk_x", "desk_y"]}},
                                 ["customer_id", "desk"], OKERR),
        "/close_call": op("Record how the call ended. Exactly once, last.", {
            "customer_id": S, "outcome": {"type": "string", "enum": ["outcome_x", "outcome_y", "outcome_z", "outcome_w", "outcome_u"]},
            "detail": {"type": "string", "enum": ["detail_a", "detail_b", "detail_c", "detail_d", "detail_e"]}},
            ["customer_id", "outcome"], OKERR),
    },
}

HEADERS = {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}}


def api_tool(name, body, description, retries=0, timeout=12000, **extra):
    return {"type": "function", "config": {"timeoutMs": timeout, "maxRetries": retries},
            "function": {"name": name, "handler": "__function__:api_call", "description": description,
                         "parameters": {"type": "object", "properties": {
                             "url": {"type": "string", "default": f"{BASE}/{name}"},
                             "method": {"type": "string", "default": "POST"}, "headers": HEADERS,
                             "body": {"type": "object", "properties": body,
                                      "required": [k for k in body if k != "text"]}}}}, **extra}


def code_node(nid, code, nxt, extra_transitions=()):
    return {"name": nid, "node_type": "code", "passthrough": True, "passthrough_default_transition": nxt,
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                             "parameters": {"type": "object", "properties": {
                                 "code": {"type": "string", "default": code}, "timeout_ms": {"type": "number", "default": 10000}}}}}],
            "transitions": [*extra_transitions, {"target_node": nxt, "description": "always", "condition": {"operator": "always"}}]}


def end_node(nid, fname, spoken=None):
    params = {"message_mode": {"type": "string", "default": "custom" if spoken else "none"}}
    if spoken:
        params["spoken_message"] = {"type": "string", "default": spoken}
    return {"name": nid, "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "transitions": [], "terminal": {"type": "function", "function": {
                "name": fname, "handler": "__function__:end_call", "parameters": {"type": "object", "properties": params}}}}


def when(var, *values, op="equals"):
    return {"logic": "or", "conditions": [{"variable": var, "operator": op, "operand": v} for v in values]}


def go(target, description, condition):
    return {"target_node": target, "description": description, "condition": condition}


def set_close(outcome, detail=""):
    return (f"try:\n    vars['close_outcome'] = '{outcome}'\n    vars['close_detail'] = '{detail}'\n"
            f"except Exception:\n    pass\n")


HOLIDAYS = ["2031-03-14", "2031-04-02"]  # invented

SETUP = helpers("parse_now", "parse_holidays", "is_business_day", "next_business_day", "spoken_date") + f"""try:
    now = parse_now(vars.get('now'))
    hol = parse_holidays({HOLIDAYS!r})
    today = now.date()
    vars['today_spoken'] = spoken_date(today)
    nxt = next_business_day(today, hol)
    same_day = 'yes' if is_business_day(today, hol) and now.hour < 17 else 'no'
    days = ('today (' + spoken_date(today) + ') after ' + now.strftime('%H:%M') + ' and ') if same_day == 'yes' else ''
    vars['callback_window_text'] = 'A callback can be booked ' + days + 'on ' + spoken_date(nxt) + ', from 09:00 to 17:00. Today is ' + spoken_date(today) + ', ' + now.strftime('%H:%M') + '.'
    vars['callback_next_day_iso'] = nxt.isoformat()
    vars['calendar_state'] = 'ok'
except Exception:
    vars['today_spoken'] = ''
    vars['callback_window_text'] = 'Ask for a time tomorrow between 09:00 and 17:00.'
    vars['calendar_state'] = 'error'
vars['close_outcome'] = 'outcome_w'
vars['close_detail'] = 'detail_c'
vars['promise_count'] = '0'
vars['call_state'] = 'open'
"""

FACTS = helpers("parse_now", "parse_holidays", "is_business_day", "next_business_day", "add_business_days",
                "last_business_day_of_week", "spoken_date", "money", "list_from_vars") + f"""BANDS = [(1, 20, 5, 1), (21, 60, 3, 2)]  # days_over from, to, deadline in business days, attempts (invented)
try:
    now = parse_now(vars.get('now'))
    hol = parse_holidays({HOLIDAYS!r})
    today = now.date()
    items = list_from_vars(vars, 'items', ['load_account_response.data.items', 'get_account_response.data.items'])
    lines, facts, offers = [], [], []
    for n, it in enumerate(items, 1):
        days = int(it.get('days_over') or 0)
        band = next((b for b in BANDS if b[0] <= days <= b[1]), BANDS[-1])
        deadline = add_business_days(today, band[2], hol)
        week_end = last_business_day_of_week(today, hol)
        if week_end is None or week_end <= today:
            week_end = last_business_day_of_week(today + datetime.timedelta(days=7), hol)
        attempt1 = min(week_end, deadline) if week_end else deadline
        name = 'item ending ' + str(it.get('ending')) if it.get('kind') == 'kind_a' else 'second item'
        facts.append(dict(ref=it.get('item_ref'), name=name, overdue=it.get('overdue'), floor=it.get('floor_amount'),
                          deadline=deadline.isoformat(), attempts=band[3], attempt1=attempt1.isoformat()))
        offers.append('- Lower amount for ' + name + ': "Could you pay ' + money(it.get('floor_amount') or 0) + ' by ' +
                      spoken_date(attempt1) + '? The remaining amount stays open on this item."')
        lines.append(str(n) + '. ' + name + ' (item_ref ' + str(it.get('item_ref')) + '): ' + money(it.get('overdue') or 0) +
                     ' overdue, ' + str(days) + ' days late. Lowest amount: ' + money(it.get('floor_amount') or 0) +
                     '. Latest date: ' + spoken_date(deadline) + ' (' + deadline.isoformat() + '). Attempts: ' + str(band[3]) +
                     '. Attempt 1 date: ' + spoken_date(attempt1) + ' (' + attempt1.isoformat() + ').')
    vars['facts_text'] = ('Today is ' + spoken_date(today) + '.\\n' + '\\n'.join(lines) +
                          '\\nSay these sentences exactly when they apply:\\n' + '\\n'.join(offers))
    vars['facts_json'] = json.dumps(facts)
    vars['item_count'] = str(len(facts))
    vars['facts_state'] = 'ok' if facts else 'empty'
except Exception:
    vars['facts_text'] = 'The account details could not be read.'
    vars['facts_json'] = '[]'
    vars['item_count'] = '0'
    vars['facts_state'] = 'error'
"""

WHAT_NEXT_VERIFY = """try:
    result.pop('header', None)
    d = result.get('data')
    if isinstance(d, dict):
        if str(d.get('all_passed')).lower() == 'true':
            vars['id_state'] = 'passed'
            d['what_to_do_next'] = 'Identity is confirmed. Say thank you in one short sentence.'
        elif str(d.get('verified')).lower() == 'true':
            d['what_to_do_next'] = 'Correct. Ask the next security question now.'
        elif d.get('hint') == 'digits_missing':
            d['what_to_do_next'] = 'Ask for all six digits again. This try does not count.'
        elif str(d.get('tries_left')) == '0':
            vars['id_state'] = 'failed'
            d['what_to_do_next'] = 'The check failed. Do not mention the account.'
        else:
            d['what_to_do_next'] = 'That answer is wrong. Ask the same question once more.'
    else:
        result['what_to_do_next'] = 'The check did not work. Ask the same question again.'
except Exception:
    pass
"""

PROMISE_PRE = helpers("to_cents") + """try:
    b = config.get('body')
    if isinstance(b, dict) and b.get('amount_minor') not in (None, ''):
        b['amount_minor'] = to_cents(b['amount_minor'])
except Exception:
    pass
"""

PROMISE_POST = """try:
    result.pop('header', None)
    d = result.get('data')
    if isinstance(d, dict) and str(d.get('ok')).lower() == 'true':
        vars['promise_count'] = str(int(vars.get('promise_count') or 0) + 1)
        vars['close_outcome'] = 'outcome_x'
        vars['close_detail'] = ''
        d['what_to_do_next'] = 'Recorded. Say: "You will get a letter about this promise." Then move on.'
    else:
        tries = int(vars.get('promise_failures') or 0) + 1
        vars['promise_failures'] = str(tries)
        if isinstance(d, dict):
            d['what_to_do_next'] = 'NOT recorded. Try once more.' if tries < 2 else 'NOT recorded. Tell the customer it could not be recorded.'
        else:
            result['what_to_do_next'] = 'NOT recorded. Try once more.' if tries < 2 else 'NOT recorded. Tell the customer it could not be recorded.'
except Exception:
    pass
"""

TRANSFER_POST = """try:
    result.pop('header', None)
    d = result.get('data')
    ok = isinstance(d, dict) and str(d.get('ok')).lower() == 'true'
    if ok:
        vars['call_state'] = 'transferred'
        vars['close_outcome'] = 'outcome_y'
        vars['close_detail'] = 'detail_a' if vars.get('transfer_desk_wanted') != 'desk_y' else 'detail_b'
    if isinstance(d, dict):
        d['what_to_do_next'] = 'Say a colleague will take over, then say goodbye.' if ok else 'The transfer failed. Say so and offer to continue.'
except Exception:
    pass
"""

CALLBACK_PRE = """try:
    b = config.get('body')
    if isinstance(b, dict) and isinstance(b.get('slot'), str):
        b['slot'] = b['slot'].strip().replace(' ', 'T')[:16]
except Exception:
    pass
"""

CALLBACK_POST = """try:
    result.pop('header', None)
    d = result.get('data')
    if isinstance(d, dict) and str(d.get('ok')).lower() == 'true':
        vars['close_detail'] = 'detail_a'
        vars['call_state'] = 'callback_booked'
        d['what_to_do_next'] = 'Booked. Thank them and say goodbye.'
    elif isinstance(d, dict):
        d['what_to_do_next'] = 'Not booked. Ask once for another time inside the window.'
except Exception:
    pass
"""

CLOSE_PRE = """try:
    b = config.get('body')
    if isinstance(b, dict):
        if int(vars.get('promise_count') or 0) > 0 and vars.get('call_state') != 'transferred':
            b['outcome'] = 'outcome_x'
        if b.get('outcome') in ('outcome_x',) or not b.get('detail'):
            b.pop('detail', None)
except Exception:
    pass
"""

# Safety net: the agent ends the call itself right after its goodbye, even if a state flag is wrong.
END_CALL_TOOL = {"type": "function", "config": {"timeoutMs": 10000},
                 "function": {"name": "end_call", "handler": "__function__:end_call",
                              "description": "Ends the call. CALL it right after you said goodbye, with no other text.",
                              "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}

AFTER_TOOL = ("After every tool result, either speak to the customer or call the next tool: never end a turn with nothing. "
              "Call one tool per message. Follow what_to_do_next in a tool result.")

WF = {
    "initial_node": "setup",
    "system_prompt": ("You are the automated assistant of Example Bank, calling a customer. Speak English, one or two short "
                      "sentences per turn. Never mention money, an item or the reason for the call before identity is confirmed. Never invent "
                      "amounts, dates or terms: use only the facts you are given. " + AFTER_TOOL),
    "test_variables": {"customer_id": "c_demo", "first_name": "Sam", "last_name": "Doe", "title": "Mx", "now": "2031-03-07T11:00"},
    "nodes": {
        "setup": code_node("setup", SETUP, "opening"),
        "opening": {
            "name": "opening", "node_type": "conversation",
            "on_enter": {"type": "tts", "text": "Hello, this is the automated assistant of Example Bank, and this call is recorded. Am I speaking with {{title}} {{last_name}}?"},
            "on_enter_first_entry_only": True,
            "task_message": "Find out whether you are speaking with {{title}} {{last_name}}. Only a clear yes or their own name confirms it. If the answer is unclear, ask once more. Say nothing about why you are calling. No tool call is allowed in this turn.",
            "extraction_schema": [{"name": "who", "type": "string", "enum_values": ["customer", "someone_else", "not_their_line", "unclear"],
                                   "description": "Who answered: customer (clear yes or own name), someone_else, not_their_line, unclear.",
                                   "min_confidence": 0.6}],
            "max_node_turns": 3, "max_turn_transition": "goodbye_short",
            "transitions": [go("identity", "The customer confirmed", when("who", "customer")),
                            go("third_party_prep", "Someone else answered", when("who", "someone_else")),
                            go("mark_not_their_line", "Wrong number", when("who", "not_their_line"))]},
        "mark_not_their_line": code_node("mark_not_their_line", set_close("outcome_w", "detail_b"), "goodbye_short"),
        "third_party_prep": code_node("third_party_prep", set_close("outcome_w", "detail_d"), "third_party"),
        "third_party": {
            "name": "third_party", "node_type": "conversation",
            "task_message": "You are not speaking with the customer. Do not say why you are calling. Ask when {{title}} {{last_name}} can be reached. " + "{{callback_window_text}} When they give a time inside that window, call schedule_callback with it. If the time is outside it, ask once for another. " + AFTER_TOOL,
            "tools": [api_tool("schedule_callback", {
                "customer_id": {"type": "string", "default": "{{customer_id}}"},
                "slot": {"type": "string", "description": "Agreed time as YYYY-MM-DDTHH:MM, inside the window.", "default": "{{slot}}"}},
                "Book the callback. CALL it as soon as the person gives a time inside the window.",
                pre_process_code=CALLBACK_PRE, post_process_code=CALLBACK_POST)],
            "extraction_schema": [{"name": "third_party_done", "type": "string", "enum_values": ["stay", "no_time"],
                                   "description": "no_time when the person gave no time inside the window after the second ask, else stay.",
                                   "min_confidence": 0.7}],
            "max_node_turns": 6, "max_turn_transition": "goodbye_short",
            "transitions": [go("goodbye_short", "Callback booked", when("call_state", "callback_booked")),
                            go("goodbye_short", "No time in the window", when("third_party_done", "no_time"))]},
        "identity": {
            "name": "identity", "node_type": "conversation",
            "on_enter": {"type": "tts", "text": "Thank you. First, for security, what is your six-digit member code?"},
            "on_enter_first_entry_only": True,
            "task_message": "Ask the security questions one at a time: first the member code, then the month of birth. Call verify_identity once for each answer, with question member_code or birth_month. " + AFTER_TOOL,
            "tools": [api_tool("verify_identity", {
                "customer_id": {"type": "string", "default": "{{customer_id}}"},
                "question": {"type": "string", "enum": ["member_code", "birth_month"], "description": "Which question was answered.", "default": "{{question}}"},
                "reply": {"type": "string", "description": "member_code: six digits. birth_month: 1-12.", "default": "{{reply}}"}},
                "Check one answer. CALL it every time the customer answers a security question.", post_process_code=WHAT_NEXT_VERIFY)],
            "max_node_turns": 12, "max_turn_transition": "goodbye_short",
            "transitions": [go("load_account", "Identity confirmed", when("id_state", "passed")),
                            go("id_failed", "Identity check failed", when("id_state", "failed"))]},
        "id_failed": code_node("id_failed", set_close("outcome_z", "detail_a"), "goodbye_failed"),
        "load_account": {
            "name": "load_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "facts",
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [api_tool("get_account", {"customer_id": {"type": "string", "default": "{{customer_id}}"}},
                                     "Get the late items.", retries=1)],
            "response_mapping": [{"path": "data.ok", "variable": "account_ok"}],  # scalars map; lists: list_from_vars
            "transitions": [go("account_error", "The lookup failed", when("load_account_failure_count", 0, op="greater_than")),
                            go("facts", "always", {"operator": "always"})]},
        "account_error": code_node("account_error", set_close("outcome_y", "detail_c"), "goodbye_error"),
        "facts": code_node("facts", FACTS, "negotiate"),
        "negotiate": {
            "name": "negotiate", "node_type": "conversation",
            "on_enter": {"type": "llm", "prompt": "Say you are calling about a late payment and state each item from the facts in one sentence each."},
            "on_enter_first_entry_only": True,
            "task_message": "Facts (computed; use them exactly):\n{{facts_text}}\n\nAsk for the full overdue amount first. When an offer sentence from the facts applies, say it exactly. When everything is handled, say goodbye and then call end_call. Read back item, amount and date and wait for a clear yes before you call create_promise (amount in currency units, e.g. 412.50). If the customer cannot pay at all, call add_note with code note_x for that item. If they ask for a person, call transfer_to_agent with desk desk_x. " + AFTER_TOOL,
            "tools": [
                api_tool("create_promise", {
                    "customer_id": {"type": "string", "default": "{{customer_id}}"},
                    "item_ref": {"type": "string", "description": "item_ref from the facts, copied unchanged.", "default": "{{item_ref}}"},
                    "amount_minor": {"type": "number", "description": "Amount in currency units as read back, e.g. 412.50.", "default": "{{amount_minor}}"},
                    "pay_on": {"type": "string", "description": "Payment date as YYYY-MM-DD.", "default": "{{pay_on}}"}},
                    "Record one promise. CALL it only after the customer said yes to the read-back.",
                    pre_process_code=PROMISE_PRE, post_process_code=PROMISE_POST),
                api_tool("add_note", {
                    "customer_id": {"type": "string", "default": "{{customer_id}}"},
                    "item_ref": {"type": "string", "description": "item_ref from the facts.", "default": "{{item_ref}}"},
                    "code": {"type": "string", "enum": ["note_x", "note_y"], "description": "note_x: refused. note_y: says already paid.", "default": "{{code}}"},
                    "text": {"type": "string", "description": "One short sentence.", "default": "{{text}}"}},
                    "Record why an item has no promise. CALL it once per item without a promise."),
                api_tool("transfer_to_agent", {
                    "customer_id": {"type": "string", "default": "{{customer_id}}"},
                    "desk": {"type": "string", "enum": ["desk_x"], "description": "desk_x: a person.", "default": "{{desk}}"}},
                    "Hand over to a person. CALL it when the customer insists on a person.", post_process_code=TRANSFER_POST),
                END_CALL_TOOL],
            "extraction_schema": [{"name": "wrap_up", "type": "string", "enum_values": ["stay", "finished"],
                                   "description": "finished once every item has a promise or a note and you said goodbye, else stay.",
                                   "min_confidence": 0.7},
                                  {"name": "topic", "type": "string", "enum_values": ["none", "difficulty"],
                                   "description": "difficulty when the customer says a life event stops them paying, else none.",
                                   "min_confidence": 0.7}],
            "max_node_turns": 40, "max_turn_transition": "goodbye",
            "transitions": [go("goodbye_transfer", "Transferred", when("call_state", "transferred")),
                            go("difficulty_prep", "A life event stops them paying", when("topic", "difficulty")),
                            go("goodbye", "Everything handled", when("wrap_up", "finished"))]},
        # A side route with required agent lines: the trigger goes to a stage node that speaks on entry;
        # the ending depends only on the answer to the offer, never on the trigger message.
        "difficulty_prep": code_node("difficulty_prep", "try:\n    vars['close_outcome'] = 'outcome_u'\n    vars['close_detail'] = 'detail_e'\n"
                                     "    vars['transfer_desk_wanted'] = 'desk_y'\nexcept Exception:\n    pass\n", "difficulty"),
        "difficulty": {
            "name": "difficulty", "node_type": "conversation",
            "on_enter": {"type": "llm", "prompt": "Say one short sentence of sympathy, then offer to put the customer through to a colleague who can help. Make no payment request."},
            "on_enter_first_entry_only": True,
            "task_message": "The customer has a difficulty. Do not ask for any payment. If they accept the offer of a colleague, call transfer_to_agent with desk desk_y. If they decline, thank them and say goodbye. " + AFTER_TOOL,
            "tools": [api_tool("transfer_to_agent", {
                "customer_id": {"type": "string", "default": "{{customer_id}}"},
                "desk": {"type": "string", "enum": ["desk_y"], "description": "desk_y: the help desk.", "default": "{{desk}}"}},
                "Hand over to the help desk. CALL it when the customer accepts the offer.", post_process_code=TRANSFER_POST)],
            "extraction_schema": [{"name": "help_answer", "type": "string", "enum_values": ["stay", "accepted", "declined"],
                                   "description": "The answer to the offer of a colleague: accepted, declined, or stay while unclear.",
                                   "min_confidence": 0.7}],
            "max_node_turns": 6, "max_turn_transition": "goodbye_short",
            "transitions": [go("goodbye_transfer", "Transferred", when("call_state", "transferred")),
                            go("goodbye_short", "Declined the offer", when("help_answer", "declined"))]},
        "goodbye": end_node("goodbye", "call_finished"),
        "goodbye_short": end_node("goodbye_short", "not_reached_end", "Thank you for your time. Goodbye."),
        "goodbye_failed": end_node("goodbye_failed", "identity_failed", "For your security, please visit a branch of Example Bank. Goodbye."),
        "goodbye_error": end_node("goodbye_error", "service_error", "I am sorry, I cannot see your details right now. We will call again. Goodbye."),
        "goodbye_transfer": end_node("goodbye_transfer", "transferred"),
    },
    "global_nodes": {
        "asks_robot": {
            "name": "asks_robot", "node_type": "conversation", "description": "The customer asks whether they talk to a robot",
            "condition": {"operator": "matches_intent", "description": "The user asks whether they are talking to a robot, a machine or an AI"},
            "task_message": "Say you are Example Bank's automated assistant.",
            "on_enter": {"type": "tts", "text": "I am Example Bank's automated assistant."},
            "passthrough": True, "passthrough_default_transition": "__previous__",
            "excluded_nodes": ["setup", "mark_not_their_line", "third_party_prep", "id_failed", "load_account", "account_error", "facts", "difficulty_prep",
                               "goodbye", "goodbye_short", "goodbye_failed", "goodbye_error", "goodbye_transfer"],
            "transitions": [go("__previous__", "always", {"operator": "always"})]}},
    "tools": [{**api_tool("close_call", {
        "customer_id": {"type": "string", "default": "{{customer_id}}"},
        "outcome": {"type": "string", "enum": ["outcome_x", "outcome_y", "outcome_z", "outcome_w", "outcome_u"], "default": "{{close_outcome}}",
                    "description": "outcome_x: a promise was recorded. outcome_y: transferred or service error. outcome_z: identity failed. outcome_w: not reached. outcome_u: verified, no promise."},
        "detail": {"type": "string", "enum": ["detail_a", "detail_b", "detail_c", "detail_d", "detail_e"], "default": "{{close_detail}}",
                   "description": "Leave out for outcome_x."}},
        "Record how the call ended.", pre_process_code=CLOSE_PRE)}],
}
WF["tools"][0]["config"]["alwaysRunsAt"] = ["end_of_call"]
WF["tools"][0]["function"]["parameters"]["properties"]["body"]["required"] = ["outcome"]

FRAGMENTS_DIR = CAL.parent / "fragments"
# fragment file -> where it sits in the demo. Each fragment is an exact piece of the lint-clean demo.
FRAGMENTS = {
    "conversation_node_with_tool.json": ("nodes", "identity"),
    "conversation_node_extraction_fork.json": ("nodes", "opening"),
    "conversation_node_actions.json": ("nodes", "negotiate"),
    "passthrough_api_node.json": ("nodes", "load_account"),
    "code_node.json": ("nodes", "mark_not_their_line"),
    "end_node.json": ("nodes", "goodbye_short"),
    "end_node_silent.json": ("nodes", "goodbye"),
    "global_node.json": ("global_nodes", "asks_robot"),
    "stage_node_offer.json": ("nodes", "difficulty"),
    "lifecycle_close_tool.json": ("tools", 0),
}


def fragment(path):
    part = WF
    for key in path:
        part = part[key]
    return part


if __name__ == "__main__":
    (HERE / "pattern_demo.openapi.json").write_text(json.dumps(API, indent=1) + "\n")
    (HERE / "pattern_demo.workflow.json").write_text(json.dumps(WF, indent=1) + "\n")
    FRAGMENTS_DIR.mkdir(exist_ok=True)
    for name, path in FRAGMENTS.items():
        (FRAGMENTS_DIR / name).write_text(json.dumps(fragment(path), indent=1) + "\n")
    print("wrote", HERE / "pattern_demo.workflow.json", "and", len(FRAGMENTS), "fragments")
