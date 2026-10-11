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
