#!/bin/bash
# Lane order (final): the flag ablation on f4+f6: f19 -> f20 only (f21, f24 dropped; f18 done, kept). A confirmation run on f5 for a flag whose removal gained >= +1
# only if it can start before 18:10. Then fix-verification slots: up to 3 files out/template_cc/eval/reserved_slot_<name>.env (SET=<compiled set> PFX=<tag prefix ending
# in g> BRIEFS="<b1> <b2>"), picked in order of arrival (file mtime) from 18:15; no new slot starts after 18:40. Each slot's verdict (gains and no brief drops) goes to
# out/template_cc/eval/gate_reserved.log. Rule: a fix goes into the final only if its slot gains and no brief drops.
cd "$(dirname "$0")/.." || exit 1
now() { date +%H%M | sed 's/^0*//'; }
E=out/template_cc/eval
for f in f19_refusal_rule f20_once_flags; do
  GATE_BRIEFS="f4-brightwell f6-corvid-memo" GATE_END=1815 scripts/gate_set.sh abl_$f abl_${f}_g
done
for f in $(.venv310/bin/python scripts/ablation_gains.py 2>> $E/ablation_gains.log); do
  [ "$(now)" -ge 1810 ] && break
  echo "$(date +%H:%M) confirmation on f5: $f removed" >> $E/ablation_gains.log
  scripts/recompile_set.sh m2b abl_$f "-$f" f5-halden-email
  GATE_BRIEFS="f5-halden-email" GATE_END=1815 scripts/gate_set.sh abl_$f abl_${f}_g
done
# idle window until 18:15: the first m2b measurement on f3, then the brief-b repeat (m2bg2)
GATE_BRIEFS="f3-kestrel" GATE_END=1815 scripts/gate_set.sh m2b m2bg
REP=2 GATE_BRIEFS="brief-b" GATE_END=1815 scripts/gate_set.sh m2b m2bg
while [ "$(now)" -lt 1815 ]; do sleep 15; done
slots=0
while [ "$(now)" -lt 1840 ] && [ $slots -lt 3 ]; do
  next=$(ls -tr $E/reserved_slot_*.env $E/reserved_slot.env 2>/dev/null | while read -r f; do [ -f "$f.done" ] || { echo "$f"; break; }; done)
  if [ -z "$next" ]; then sleep 20; continue; fi
  name=$(basename "$next" .env | sed 's/^reserved_slot_*//'); [ -z "$name" ] && name=default
  . "$next"; touch "$next.done"; slots=$((slots + 1))
  echo "$(date +%H:%M) slot $slots/3 '$name': set $SET, briefs $BRIEFS, tag prefix $PFX" >> $E/gate_reserved.log
  GATE_END=1925 GATE_BRIEFS="$BRIEFS" scripts/gate_set.sh "$SET" "$PFX"
  if [ "$name" = default ]; then cp "$next" "$E/reserved_slot_default.env"; name=default; fi
  .venv310/bin/python scripts/slot_verdict.py "$name" >> $E/gate_reserved.log 2>&1
done
echo "$(date +%H:%M) slots done ($slots used)" >> $E/gate_reserved.log
