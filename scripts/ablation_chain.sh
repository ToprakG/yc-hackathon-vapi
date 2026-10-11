#!/bin/bash
# Lane order: brief-b, f6 (ablation baseline), brief-a on m2b (some may already be done: finished briefs are skipped); the five-flag ablation on f4+f6
# (sets abl_<flag>, tags abl_<flag>_g1); every flag whose removal gained >= +1 on f4 or f6 gets a confirmation run on f5 (removed vs m2b f5 = m2bg1 9/10);
# then m2b f7 (the f25 baseline) and f25_dispute_wins removed on f5 + f7 (where it is active). No new brief after 18:55.
cd "$(dirname "$0")/.." || exit 1
export GATE_END=1855
GATE_BRIEFS="brief-b f6-corvid-memo brief-a" scripts/gate_set.sh m2b m2bg
for f in f18_side_resume f19_refusal_rule f20_once_flags f21_spoken_answers f24_day_once; do
  GATE_BRIEFS="f4-brightwell f6-corvid-memo" scripts/gate_set.sh abl_$f abl_${f}_g
done
for f in $(.venv310/bin/python scripts/ablation_gains.py 2>> out/template_cc/eval/ablation_gains.log); do
  echo "$(date +%H:%M) confirmation on f5: $f removed" >> out/template_cc/eval/ablation_gains.log
  scripts/recompile_set.sh m2b abl_$f "-$f" f5-halden-email
  GATE_BRIEFS="f5-halden-email" scripts/gate_set.sh abl_$f abl_${f}_g
done
GATE_BRIEFS="f7-lumen-codes" scripts/gate_set.sh m2b m2bg
GATE_BRIEFS="f5-halden-email f7-lumen-codes" scripts/gate_set.sh abl_f25_all abl_f25_dispute_wins_g
