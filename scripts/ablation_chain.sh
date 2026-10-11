#!/bin/bash
# Lane order: brief-b, f6, brief-a on m2b (finished briefs are skipped); the five-flag ablation on f4+f6 (sets abl_<flag>, tags abl_<flag>_g1); a
# confirmation run on f5 for every flag whose removal gained >= +1 on f4 or f6; then (only what finishes before 18:30) m2b f7 and f25_dispute_wins removed on
# f5 + f7. RESERVED SLOT at 18:35: if out/template_cc/eval/reserved_slot.env exists (SET=<compiled set> PFX=<tag prefix ending in g> BRIEFS="<b1> <b2>"), that
# targeted-fix GATE runs first at 18:35; the f25 tail then continues until 18:55. No new brief after 18:55.
cd "$(dirname "$0")/.." || exit 1
now() { date +%H%M | sed 's/^0*//'; }
export GATE_END=1830
GATE_BRIEFS="brief-b f6-corvid-memo brief-a" scripts/gate_set.sh m2b m2bg
for f in f18_side_resume f19_refusal_rule f20_once_flags f21_spoken_answers f24_day_once; do
  GATE_BRIEFS="f4-brightwell f6-corvid-memo" scripts/gate_set.sh abl_$f abl_${f}_g
done
for f in $(.venv310/bin/python scripts/ablation_gains.py 2>> out/template_cc/eval/ablation_gains.log); do
  [ "$(now)" -ge 1830 ] && break
  echo "$(date +%H:%M) confirmation on f5: $f removed" >> out/template_cc/eval/ablation_gains.log
  scripts/recompile_set.sh m2b abl_$f "-$f" f5-halden-email
  GATE_BRIEFS="f5-halden-email" scripts/gate_set.sh abl_$f abl_${f}_g
done
GATE_BRIEFS="f7-lumen-codes" scripts/gate_set.sh m2b m2bg
GATE_BRIEFS="f5-halden-email f7-lumen-codes" scripts/gate_set.sh abl_f25_all abl_f25_dispute_wins_g
# the reserved slot
while [ "$(now)" -lt 1835 ]; do sleep 15; done
R=out/template_cc/eval/reserved_slot.env
if [ -f "$R" ]; then
  . "$R"
  echo "$(date +%H:%M) reserved slot: set $SET, briefs $BRIEFS, tag prefix $PFX" >> out/template_cc/eval/gate_reserved.log
  GATE_END=1855 GATE_BRIEFS="$BRIEFS" scripts/gate_set.sh "$SET" "$PFX"
else
  echo "$(date +%H:%M) reserved slot not used (no reserved_slot.env)" >> out/template_cc/eval/gate_reserved.log
fi
export GATE_END=1855
GATE_BRIEFS="f7-lumen-codes" scripts/gate_set.sh m2b m2bg
GATE_BRIEFS="f5-halden-email f7-lumen-codes" scripts/gate_set.sh abl_f25_all abl_f25_dispute_wins_g
