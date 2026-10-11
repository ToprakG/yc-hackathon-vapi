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
