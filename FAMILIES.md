# Failure families of the p6 DEV set (24 dead + 9 flaky cases, from REAL Freya transcripts)

Source: Freya p6r1 / p6r2 on DEV cases 1-10 of the 9 briefs; the failing repeats' transcripts (node, turn) fetched with `scripts/dev_transcripts.py`
(read only; GATE / sealed files never read). Full per-case rows with judge text, quotes and later-set history: `FAMILIES_DETAIL.md`.
"m1 flag" = a flag in `M1_FLAGS.txt`. "Still fails" = a later eval tag with that flag still failed the case. Local-sim calibration (Gemini customer + judge):
80% (16/20) agreement with Freya on DEV.

## 1. One line per case (33)
| brief | case | kind | family | first wrong turn @ node | rule-type cause |
|---|---|---|---|---|---|
| brief-a | A-025 | dead | A human_stale | read-back "yes" -> "Bir saniye lütfen" @ promise_confirm->human_offer | `side` stays human after "continue"; router's human branch sits before `rb_answer=yes`; agent says "scheduled" with no promise |
| brief-b | B-004 | dead | E vague_day | 2nd "exact day" ask @ negotiate | the one-ask rule is left to the model (re-asks, or proposes without the ask) |
| brief-b | B-010 | flaky | J opening_reply | improvised "May I ask your name?" @ opening (who1 unset) | first reply sets no who1 -> free model turn (covered by f18 fallback, passes since) |
| brief-b | B-013 | dead | F hardship | promise confirmed, then closed hardship @ hardship | hardship state wins over a confirmed promise; no create_promise |
| brief-b | B-014 | flaky | C refusal_count | cut-off complaint counted as 2nd refusal @ identity | a complaint after a complete answer is read as a refusal |
| brief-b | B-015 | dead | D robot_q | robot question ignored, DOB asked @ identity | ai_asked extracted but the ai line is not said before the next ask |
| brief-b | B-032 | dead | B digits (+G judge on r2) | "twelfth of October one nine nine seven" -> year lost @ identity | digit-by-digit year parsed as current year, same wrong answer resent 3x; r2 judge wants 'human' queue (brief: general) |
| brief-b | B-040 | flaky | B digits | "one nine five nine" -> 2026 @ identity | same year bug |
| f1 | F1-003 | dead | C refusal_count | "I already told you I won't provide my date of" = partial answer @ identity | truncated refusal read as partial answer; closes on 4th ask |
| f1 | F1-004 | flaky | K persona | persona says April 2nd (script: April 1st) @ identity | agent correct; persona contradicts itself (UNFIXABLE) |
| f1 | F1-012 | flaky | G judge_queue | transfer to `general` @ human_offer | judge text expects a 'human' queue; brief/bank say general (UNFIXABLE) |
| f1 | F1-017 | flaky | B digits | truncated "nineteen sixty-" submitted as 1960 @ identity | incomplete year sent as a full answer, then resent |
| f1 | F1-025 | dead | F hardship | 3 sentences of sympathy @ identity | improvised sympathy outside the hardship node; r2 has no customer turn (partly unfixable) |
| f2 | F2-002 | dead | E vague_day | offers 27 Nov instead of the 30 Nov deadline @ negotiate | after the one exact-day ask the deadline is not offered (vague_date_offer unset) |
| f2 | F2-014 | flaky | B alphabet | NATO-alphabet postcode sent as words @ identity | spelling alphabet not normalised before verify_identity |
| f2 | F2-015 | flaky | A human_stale | "yes" at read-back -> human_offer @ promise_confirm | stale human intent beats the read-back yes |
| f2 | F2-017 | dead | C refusal_count | 2nd explanation + 3rd ask @ identity_explain | cached policy id_decline=2 (brief: 1) |
| f3 | F3-003 | dead | B digits | "one nine seven four" -> 2026 @ identity | digit-by-digit year not parsed |
| f3 | F3-021 | dead | F hardship (+A) | cut-off "because my cousin" -> side=hardship; "I have recorded…" with no tool call @ hardship | false hardship; read-back yes inside hardship has no route to promise_write; claim without create_promise |
| f3 | F3-024 | dead | C refusal_count | 2nd explanation @ identity_explain | id_decline=2 (as F2-017) |
| f3 | F3-032 | dead | A human_stale | "yes" -> "Bir saniye lütfen" @ promise_confirm->human_offer | as A-025 |
| f3 | F3-039 | dead | D robot_q | "Yes, this is X. Are you a robot?" -> DOB asked @ opening->identity | who1 fired, ai_asked not extracted, ai line never said |
| f4 | F4-006 | dead | D robot_q | same as F3-039 | same |
| f4 | F4-018 | flaky | H dispute | "paid that off last year, should be closed. Not discussing payment" -> refused @ negotiate | refusal beats the dispute claim (f25 is exactly this) |
| f4 | F4-025 | dead | C refusal_count | refusal + question counted as 2 even after a correct answer @ identity | refusals counted cumulatively, not consecutively |
| f5 | F5-004 | dead | A human_stale | "yes" -> human_offer @ promise_confirm | as A-025 |
| f5 | F5-012 | dead | C refusal_count | chatter re-asked up to 10 times @ identity_explain | non-answers after the explanation are not counted; no close |
| f5 | F5-018 | dead | E vague_day | exact day asked twice; self-correction "24th… I mean Monday" resolved wrongly @ negotiate_resume | no counter for the exact-day ask; spoken correction |
| f6 | F6-002 | dead | E vague_day | "when things settle down" read as flat refusal @ negotiate | undated conditional not classified as a vague period |
| f6 | F6-009 | dead | G judge_queue (+human_offer) | r1: offer asked twice @ human_offer; both: judge wants 'human' queue | r1 real (ask once then transfer); the queue half is UNFIXABLE |
| f7 | F7-002 | dead | D robot_q | "…twenty-second of February. Am I talking to a robot?" -> next ask @ identity | asks_robot extracted with an answer but dropped |
| f7 | F7-006 | dead | G judge_queue | transfer to `general` @ transfer_human | judge/persona wording expects 'human' queue (UNFIXABLE) |
| f7 | F7-009 | dead | I amounts | spoken "two hundred seventy fifty" read below floor, floor asked twice; "smaller amount" -> restructuring @ negotiate_resume / negotiate | amount fragments not assembled; "a smaller amount" extracted as restructuring |

## 2. Families
| fam | cases | n | briefs | rule-type fix (one line) | m1 flag that covers it? |
|---|---|---|---|---|---|
| C refusal_count | B-014 F1-003 F2-017 F3-024 F4-025 F5-012 | 6 | b, f1, f2, f3, f4, f5 | `id_decline` from the brief (done: policy_fixups); count CONSECUTIVE refusals only; keyword refusals; non-answers after the explanation count; close on refusal id_decline+1; a cut-off complaint is not a refusal | f19_refusal_rule: covers; **still fails** F4-025, F5-012 (later sets) |
| B digits/alphabet | B-032(r1) B-040 F1-017 F2-014 F3-003 | 5 | b, f1, f2, f3 | normalise digit-by-digit years ("one nine five nine" = 1959) and spelling-alphabet words in code before verify_identity; never submit a truncated year; never resend an identical rejected answer | f21_spoken_answers / f9_number_input: cover; **untested on these cases** (B-040, F1-017 fail with f9) |
| A human_stale | A-025 F5-004 F2-015 F3-032 (+F3-021 half) | 4 | a, f5, f2, f3 | reset `side`/`turn_intent`/human flags when the customer continues (human_back); `rb_answer=yes` before the human branch; never say "scheduled/recorded" unless create_promise returned ok; no Turkish filler | **not covered** (f20_once_flags' human_gate changes the path, unmeasured) |
| D robot_q | B-015 F3-039 F4-006 F7-002 | 4 | b, f3, f4, f7 | if the first reply (or an identity answer) also asks "robot?", say the policy `ai` line as a side line before the next ask, even when who1/id_answer is set | f18_side_resume: covers the opening; **still fails** B-015, F7-002 (answer + robot question in one message) |
| E vague_day | B-004 F2-002 F5-018 F6-002 | 4 | b, f2, f5, f6 | ask the exact day once (code counter), then offer the DEADLINE at the attempt amount; an undated conditional ("when things settle") is a vague period; a spoken correction keeps the last full date; `vague_date_offer=deadline` from the brief | f24_day_once + f11: cover; **unmeasured** (F5-018 never passed) |
| F hardship | B-013 F1-025 F3-021 | 3 | b, f1, f3 | hardship only on explicit illness / death / job-loss words; a named amount+date goes to the promise path (never close hardship over a confirmed promise); sympathy is one fixed line said once | f15_hardship_terms, f20 (said_once): cover; **still fail** (B-013, F3-021) |
| H dispute | F4-018 | 1 | f4 | closed / paid-off-in-the-past claim is dispute even next to a refusal | f25_dispute_wins: covers; passes on later sets |
| I amounts | F7-009 | 1 | f7 | assemble spoken amounts ("270" "50" = 270.50) before the floor check; "a smaller amount" is not restructuring | f26_amount_assembly (NOT in M1) / f4_discount: **still fails** |
| J opening_reply | B-010 | 1 | b | first reply with no who1 -> fixed second ask / death keyword | f18 fallback: covered, passes since |
| G judge_queue | F1-012 F7-006 F6-009 | 3 | f1, f7, f6 | none: judge/persona expects a 'human' queue, brief and bank say `general` | n/a |
| K persona | F1-004 | 1 | f1 | none: persona contradicts its own script | n/a |

## 3. Unfixable / leave the target
F1-012, F7-006, F1-004 (whole case). Partly: B-032 r2 (judge queue wording; r1 is fixable), F6-009 (queue half; the double offer is fixable), F1-025 r2 (no customer turn), F2-017 p6r2 (persona answered against its script; p6r1 is a real defect).
=> **30 of 33 cases are in the target**; the three groups below cover 30.

## 4. Groups (balanced by expected cases fixed; one theme per group so the three sessions touch different code)
| group | families | cases | n | area |
|---|---|---|---|---|
| **G1 (S1: negotiation / promise path)** | A human_stale + E vague_day + I amounts | A-025 F5-004 F2-015 F3-032, B-004 F2-002 F5-018 F6-002, F7-009 | 9 | negotiate / negotiate_resume / promise_confirm / human_back routing, `vague_date_offer`, amount assembly (+ the f26 decision) |
| **G2 (S2: identity)** | C refusal_count + B digits/alphabet | B-014 F1-003 F2-017 F3-024 F4-025 F5-012, B-032(r1) B-040 F1-017 F2-014 F3-003 | 11 | identity / identity_explain: consecutive refusals, non-answers, digit-by-digit years, spelling alphabets, no resend of an identical rejected answer |
| **G3 (S3: opening, hardship, dispute, transfer)** | D robot_q + F hardship + H dispute + J opening + the human_offer part of G | B-015 F3-039 F4-006 F7-002, B-013 F1-025 F3-021, F4-018, B-010, F6-009(r1) | 10 | opening / first-reply side lines (ai line with who1 or an answer), hardship routing and fixed sympathy, dispute-wins, human_offer ask-once |
Local sim (Gemini customer + judge, Sonnet agent, DEV cases only, x2): validate each group on ITS cases; GATE cases are never run.

## 5. Anti-overfit rules for the 85 push (apply to ALL fix groups)
1. **Cross-brief:** a flag goes into m2 only if its local_sim validation fixes cases in **at least 2 different briefs**. Single-brief fixes are dropped.
2. **Sealed check at 18:45:** `scripts/sealed_check.sh <m2 set>` runs m1 and m2 with `local_sim.py --sealed` on GATE cases 11-20 of **4 briefs only (brief-b, f3-kestrel, f5-halden-email, f7-lumen-codes: the most non-solid cases)**, x1 = 80 conversations, **counts only**. Nobody reads or dumps those transcripts; the script writes only pass/fail counts per brief (`out/template_cc/localsim/sealed_counts.json`). If Freya works at 18:45, use the Freya GATE instead.
3. **If m2 < m1 on that check:** remove flags one at a time, last kept first, until m2 >= m1. Report each step (flag removed, new counts).
4. The local judge stays `google/gemini-3-flash-preview` (Freya's own judge model). The local agent (Sonnet) is probably stronger than Freya's `experimental-5`, so local passes on agent-capability behaviour are optimistic.
5. **Local-sim budget (all sessions S1-S4 together):** new normal conversations are refused from **18:30**, the sealed check until 19:15, no local_sim claude call at all after **19:15** (quota for the 20:00 final build).  300 conversations in total, concurrency 4, enforced by a shared counter and slot lock in `out/template_cc/localsim/_budget/`. The first claude usage / rate-limit warning in any run stops ALL local sim runs (`out/template_cc/localsim/_budget/STOP`) and is reported.
