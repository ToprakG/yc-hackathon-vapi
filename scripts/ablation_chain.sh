#!/bin/bash
# Scheduler for the lane until 18:40 (one brief per step). PRIORITY 1: a fix-verification slot out/template_cc/eval/reserved_slot_<name>.env (SET=<compiled set>
# PFX=<tag prefix ending in g> BRIEFS="<b1> <b2>" [FAMILY="<target family>"]) starts as soon as the brief currently running has finished (max 3 slots, in order of
# arrival; a slot started before 18:40 runs to its end). PRIORITY 2 (only when no slot is waiting): the background items in order: f20 ablation on f4 + f6, a f5
# confirmation if f20's removal gained >= +1 (before 18:10), m2b on f3, m2b brief-b repeat (tag m2bg2). No new step after 18:40.
cd "$(dirname "$0")/.." || exit 1
now() { date +%H%M | sed 's/^0*//'; }
E=out/template_cc/eval
slots=0
next_slot() { ls -tr $E/reserved_slot_*.env $E/reserved_slot.env 2>/dev/null | while read -r f; do [ -f "$f.done" ] || { echo "$f"; break; }; done; }
lane_busy() { [ -d $E/lane1.lock ] && kill -0 "$(cat $E/lane1.lock/pid 2>/dev/null)" 2>/dev/null; }
run_slot() { next=$1
  name=$(basename "$next" .env | sed 's/^reserved_slot_*//'); [ -z "$name" ] && name=default
  touch "$next.done"; slots=$((slots + 1))
  [ "$name" = default ] && cp "$next" "$E/reserved_slot_default.env"
  echo "$(date +%H:%M) slot $slots/3 '$name' (preempts the background items): $(tr '\n' ' ' < "$next")" >> $E/gate_reserved.log
  scripts/run_slot.sh "$next" >> $E/gate_reserved.log 2>&1
  .venv310/bin/python scripts/slot_verdict.py "$name" >> $E/gate_reserved.log 2>&1; }
# background items: "set prefix rep brief"
TASKS=("abl_f20_once_flags abl_f20_once_flags_g 1 f4-brightwell" "abl_f20_once_flags abl_f20_once_flags_g 1 f6-corvid-memo" "m2b m2bg 1 f3-kestrel" "m2b m2bg 2 brief-b")
task_done() { set -- $1; [ -f "$E/freya/$4.$2$3.json" ] || [ -f "$E/gate_$1.state/$4.abandoned" ]; }
confirmed=0
while [ "$(now)" -lt 1840 ]; do
  s=""; [ $slots -lt 3 ] && s=$(next_slot)
  if [ -n "$s" ]; then
    while lane_busy; do sleep 5; done        # the brief currently running finishes first
    run_slot "$s"; continue
  fi
  pick=""
  for t in "${TASKS[@]}"; do task_done "$t" || { pick=$t; break; }; done
  if [ -z "$pick" ] && [ $confirmed -eq 0 ]; then       # the f5 confirmation of f20 (once, only before 18:10)
    confirmed=1
    if [ "$(now)" -lt 1810 ] && .venv310/bin/python scripts/ablation_gains.py 2>> $E/ablation_gains.log | grep -q f20_once_flags; then
      echo "$(date +%H:%M) confirmation on f5: f20_once_flags removed" >> $E/ablation_gains.log
      scripts/recompile_set.sh m2b abl_f20_once_flags "-f20_once_flags" f5-halden-email
      TASKS=("abl_f20_once_flags abl_f20_once_flags_g 1 f5-halden-email" "${TASKS[@]}")
      continue
    fi
  fi
  if [ -z "$pick" ]; then sleep 20; continue; fi
  while lane_busy; do s=""; [ $slots -lt 3 ] && s=$(next_slot); [ -n "$s" ] && break; sleep 5; done
  [ -n "$s" ] && continue                    # a slot arrived while waiting for the lane: it goes first
  set -- $pick
  REP=$3 GATE_END=1840 GATE_BRIEFS="$4" scripts/gate_set.sh "$1" "$2"
done
echo "$(date +%H:%M) scheduler stopped (18:40 cutoff; $slots slot(s) used)" >> $E/gate_reserved.log
