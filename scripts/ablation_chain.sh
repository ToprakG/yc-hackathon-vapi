#!/bin/bash
# Flag ablation on f4 + f6 (weakest briefs), after the m2b GATE (m2bg1): baseline m2b on f6, then each flag removed (sets abl_<flag>, recompiled from m2b's
# policies, tags abl_<flag>_g1). f25_dispute_wins is skipped: the workflow is identical without it (no-op). No new brief after 18:55.
cd "$(dirname "$0")/.." || exit 1
while pgrep -f "scripts/gate_set.sh m2b m2bg" > /dev/null; do sleep 20; done
export GATE_END=1855
GATE_BRIEFS="f6-corvid-memo" scripts/gate_set.sh m2b m2bg
for f in f18_side_resume f19_refusal_rule f20_once_flags f21_spoken_answers f24_day_once; do
  GATE_BRIEFS="f4-brightwell f6-corvid-memo" scripts/gate_set.sh abl_$f abl_${f}_g
done
