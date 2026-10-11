#!/bin/bash
# Lane order (final): the flag ablation on f4+f6 in the order f19 -> f20 -> f21 -> f24 (f18 is done: removal -2 on f4, kept; sets abl_<flag>, tags abl_<flag>_g1;
# finished briefs are skipped); new ablation runs stop at 18:40; a confirmation run on f5 for a flag whose removal gained >= +1 only if it can start before 18:35.
# RESERVED SLOT at 18:35: out/template_cc/eval/reserved_slot.env (SET=<compiled set> PFX=<tag prefix ending in g> BRIEFS="<b1> <b2>"), written by S3 for m2c by 18:30,
# runs at 18:35 whatever the ablation is doing (its briefs may start after 18:40). Nothing else after the slot.
cd "$(dirname "$0")/.." || exit 1
now() { date +%H%M | sed 's/^0*//'; }
export GATE_END=1840
for f in f19_refusal_rule f20_once_flags f21_spoken_answers f24_day_once; do
  [ "$(now)" -ge 1835 ] && break      # the reserved slot comes first
  GATE_BRIEFS="f4-brightwell f6-corvid-memo" GATE_END=1835 scripts/gate_set.sh abl_$f abl_${f}_g
done
for f in $(.venv310/bin/python scripts/ablation_gains.py 2>> out/template_cc/eval/ablation_gains.log); do
  [ "$(now)" -ge 1830 ] && break
  echo "$(date +%H:%M) confirmation on f5: $f removed" >> out/template_cc/eval/ablation_gains.log
  scripts/recompile_set.sh m2b abl_$f "-$f" f5-halden-email
  GATE_BRIEFS="f5-halden-email" GATE_END=1835 scripts/gate_set.sh abl_$f abl_${f}_g
done
while [ "$(now)" -lt 1835 ]; do sleep 15; done
R=out/template_cc/eval/reserved_slot.env
if [ -f "$R" ]; then
  . "$R"
  echo "$(date +%H:%M) reserved slot: set $SET, briefs $BRIEFS, tag prefix $PFX" >> out/template_cc/eval/gate_reserved.log
  GATE_END=1925 GATE_BRIEFS="$BRIEFS" scripts/gate_set.sh "$SET" "$PFX"
else
  echo "$(date +%H:%M) reserved slot not used (no reserved_slot.env)" >> out/template_cc/eval/gate_reserved.log
fi
