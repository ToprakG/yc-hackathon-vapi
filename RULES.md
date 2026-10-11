# S2 rule types (fix-identity)

Each fix is a rule type that applies to every brief having the rule. A rule type needs a verified policy parameter; with
none, its flag does nothing for that brief and the p6 prompt sentence stays (graceful degradation, tested).

## A. Side questions are answered, then the same step resumes (f18_side_resume)
- Rule: a side intent (AI question, scam question, human offer declined, hardship with own terms, digression/filler) is
  answered with the policy's fixed line for it and the current step then resumes with its pending question. The AI/scam
  question wins at every stage, also when the same turn holds an answer or refusal (the answer is still processed).
- Mechanism: the step's pending line is stored (`id_q`, `id_say`); `aside_new` holds the side line; the step's code node
  moves it to `aside_line`, which the step speaks in front of its own line. A turn that is none of answer / refusal /
  side question (`id_intent=other`) goes to a code node that re-speaks the pending question: no free model turn.
- Parameter: `lines.ai` / `lines.scam` (policy). No line -> nothing changes for that brief. `resume_step` (var) = the
  step to resume (S1 reads it).

## B. Declined identity questions: explain once, close at the limit (f19_refusal_rule)
- Rule: every refusal counts, a question back (why / which account / what is this) included; the explanation is the
  policy's `id_reason` line, said once; at the limit the call closes as the declined outcome.
- Mechanism: refusal intents are tested before the free answer text (a refusal sentence is not a partial answer);
  `id_refusal_count` counts every one; explanation while `n <= min(ask_limits.id_decline, 1)`, close after.
- Parameter: `ask_limits.id_decline` and `lines.id_reason`. Missing -> unchanged.

## E/F. Once-rules are code flags (f20_once_flags)
- Rule: every "once / only once / exactly once / one sentence" rule is `said_once(vars, <line_id>)` (runtime.py):
  true the first time, false after. Used for the sympathy sentence, the help offer for a human request, the id reason.
- Mechanism: a request for a person made while the help offer is open means "insists" (transfer); the sympathy sentence
  is only said by the fixed line, models are told not to improvise one.
- Parameter: `ask_limits.human_offer`, `lines.hardship_sympathy`, queue `human`. Missing -> unchanged.

## G. Spoken answers are normalised in code (f21_spoken_answers)
- Rule: a spoken identity answer is turned into the field's kind by code (words, pieces over several turns,
  corrections): digit-by-digit years ("one nine five nine"), spelling alphabets in codes ("Mike Golf nine seven").
- Parameter: `identity.kinds` (from the tool API). Kind `text` -> unchanged.

## Extraction bug found (for S4, R1)
`ask_limits.id_decline` flips between builds although every brief has the same sentence ("explain once ... a second refusal
closes" = 1). p10: brief-a 2, f2 2, f3 2 (wrong); brief-b/f1/f4/f6/f7 flip 1<->2 across p6/p10x/x1. f19 reads the policy
value (no constant), so a wrong extraction shows up as a second explanation. Targeted evals of f19 use set s2d, whose
policies of brief-a, f2, f3 are corrected to 1 (what a correct extraction gives).

## Folded into f18: a side intent in the first reply
Deceased / third party / robot question in the first reply when extraction does not fire (B-010, B-015): the opening has an
`always` fallback; the robot answer is kept (`aside_open`) and the second ask is the policy's `ask_again` line, fixed.
# S1 rule types (fix-negotiation)

Parameters come from policy.json with a verified `_source` quote (`verified()` in graph.py). Missing or unverified ->
the flag does nothing and the p6 prompt sentence stays (one test per rule).

## C. An agreed promise is always recorded (f16_promise_guard) - DROPPED
- Root cause (p6 DEV: A-025, F5-004, F3-032, F2-015, B-013): the "yes" to the read-back came with a stale side signal (human offer /
  hardship choice), the side transition won, and the call closed with the product open -> refused. Fixed overnight by 20383c4
  (promise_check consumes stale side/choice signals): on p10 all of these pass (s1b1, s1c1). A guard (yes first in promise_confirm +
  wrap routing a confirmed unrecorded promise to promise_write) was built and tested with no loss, but adds nothing on p10, so it
  was removed to cut merge risk. F3-021 failed on p10 for rule E (day asked twice), not C.

## D. The proposed date follows the brief's deadline rule
- Rule: the deadline (band business days + holidays), the attempt dates and cap_at_deadline are computed only in code
  (runtime.product_rows / attempt_date). Nothing to add: the p6 failures (F2-002, F6-002, F5-018) were the model offering the
  persuasion date instead of the deadline after a vague day; fixed overnight by 22f4b4f (offer_intent=vague). Unit test added
  for business days, holidays and month ends. No f17 flag (nothing left to fix on p10).
- F5-018 amount (1200 vs 1245, B-004 2002 vs 2240): the simulated customer's self-correction is cut off in the transcript and
  the customer then confirms the wrong read-back; not a negotiation rule, dropped.

- Cached-policy check (p10 policies vs the brief's own sentence): bands/deadline business days are right for f2 (10/5), f5 (8/4),
  f6 (12/5, the amended late band) and brief-a/b (12/7). cap_at_deadline step 1 = True matches f2 and f6 ("if that day is after the
  deadline, propose the deadline") and f5 ("never later than the deadline"). Step 2 flips between builds (x0/x0b/x1/x2) but the date is the
  deadline itself, so the flag cannot change a date. Brief A/B state no cap sentence for attempt 1 (value flips x0/x1 vs p10), but with
  deadlines of 7+ business days the end-of-week date can never exceed it: no effect. Conclusion: no wrong cached value, nothing to fix in
  the compiler. R1 test case for S4: field /attempt_plan/0/cap_at_deadline; quotes f6 "If that day is after the deadline, propose the
  deadline." and f5 "never later than the deadline"; brief-a/b have no quote (the extractor must not invent True/False there).

## E. Ask the exact day once (f24_day_once)
- Rule: when a brief says "ask once for the exact day; if they still give none, propose the deadline", the compiled agent
  asks once and any later turn without a day (a distraction, a non-answer) gets the deadline offer, not a second ask.
- Root cause (p10 F3-021, p6 B-004): after the code asked the day, a non-answer was extracted as offer_intent=none, which does
  not reach promise_check, so the model asked again.
- Fix: day_asked is set by promise_check when it asks; a turn with day_asked=1, no offer, no side and no router intent goes to
  promise_check, whose counter (vague_n > limit) offers the deadline.
- Parameter: ask_limits.vague_date (verified). Needs f7_router. Floor-offered-once (F7-009) passes on p10: not changed.

## F. A dispute claim is a dispute even next to a refusal (f25_dispute_wins)
- Rule: when a brief says "'this debt is not mine' / 'closed or paid off in the past': no promise, close as dispute", the compiled agent
  must treat that claim as dispute even if the same message also refuses to talk or pay.
- Root cause (p6 F4-018 both runs): "I paid that off last year, it should be closed. I am not discussing payment." was extracted as
  side=none; the model said "disputed" but the code status stayed refused, so the note and the outcome were refused.
- Fix: the side description says the dispute value wins. Parameter: outcome_map.np_dispute (verified). Missing -> p6 text.
- F7-009 (restructuring transfer for "any way to pay a smaller amount?"): passes on p10 (s1b1); not changed.

## G. Spoken amounts are assembled and corrected in code (f26_amount_assembly)
- Rule: when a brief gives a floor and a past-due amount, an amount that arrives in pieces over turns ("twelve" ... "thirty") is joined,
  and the last stated amount wins; an amount cut off in the middle of a self-correction is not taken, it is asked again.
- Join is conservative: two sub-floor integer fragments, no correction marker (no, sorry, I mean, actually, wait, rather) in the
  second, joined value within [floor, past due]; otherwise the last amount stays. Cut-off: offer_amount_text keeps the tail words
  (extraction description) and a trailing correction marker clears the amount.
- Parameter: verified /product_types (floor), needs f9 and f11. Missing -> p6 workflow (tested).
- B-015 (p6r2) failed on the robot question, not on the amount; F5-018 is the cut-off correction (1200 then 1245).

## f19 extension: chatter is a non-answer
An identity turn that is neither an answer, a refusal nor a side question (`id_intent` other) is a non-answer. It is re-asked once; the second non-answer in a row is a refusal and goes through the same counter (explain once, close on refusal `id_decline` + 1). This no longer depends on the policy having robot/scam lines (the `id_resume` node is built for f19 alone).
