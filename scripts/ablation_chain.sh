#!/bin/bash
# Lane order after the first four m2bg1 results (f1, f4, f5 landed): brief-b (validates the brief-reference fix), f6 (also the ablation baseline), brief-a
# (never ran: the lane was busy at its turn), then the flag ablation on f4 + f6 (sets abl_<flag>, tags abl_<flag>_g1), then f25_dispute_wins removed on
# f5 + f7 (where it is active) with m2b f7 as the extra baseline (m2b f5 = m2bg1). f2, f3, f7 are not run on m2b except the f7 baseline at the end.
# f25 is skipped on f4/f6 (the workflow is identical without it there). No new brief after 18:55.
cd "$(dirname "$0")/.." || exit 1
export GATE_END=1855
GATE_BRIEFS="brief-b f6-corvid-memo brief-a" scripts/gate_set.sh m2b m2bg
for f in f18_side_resume f19_refusal_rule f20_once_flags f21_spoken_answers f24_day_once; do
  GATE_BRIEFS="f4-brightwell f6-corvid-memo" scripts/gate_set.sh abl_$f abl_${f}_g
done
GATE_BRIEFS="f7-lumen-codes" scripts/gate_set.sh m2b m2bg
GATE_BRIEFS="f5-halden-email f7-lumen-codes" scripts/gate_set.sh abl_f25_all abl_f25_dispute_wins_g
