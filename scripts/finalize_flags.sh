#!/bin/bash
# FINAL_FLAGS rule (user): keep f28 (hardened by S3; merge it into main, full suite, then `touch out/f28_merged`) + f29.
# f22: kept only if the isolation cleared it = f3 -f22 (tag f3m22g1) exists and is < 8; -f22 >= 8, or no result by 19:25 -> drop f22.
# Then scripts/amend_flags.sh (M1 flags + remaining fixes + ,-f18_opening_fallback) and scripts/dress_run.sh at once.
cd "$(dirname "$0")/.." || exit 1
E=out/template_cc/eval; L=out/finalize_flags.log; mkdir -p out; log() { echo "$(date +%T) $*" | tee -a $L; }
now() { date +%H%M | sed 's/^0*//'; }
sc() { python3 -c "import json;print(json.load(open('$E/freya/f3-kestrel.$1.json'))['passed'])" 2>/dev/null; }
while :; do a=$(sc f3m22g1); [ -n "$a" ] && break; [ "$(now)" -ge 1925 ] && break; sleep 10; done
log "f3 -f28 = $(sc f3m28g1 || true)  -f22 = ${a:-none}  -f29 = $(sc f3m29g1 || true)"
if [ -n "$a" ] && [ "$a" -lt 8 ]; then DROP=""; WHY="f3 -f22 = $a/10 (<8): f22 cleared, kept"; else DROP=f22_forbidden_disclosure; WHY="f3 -f22 = ${a:-no result by 19:25}: dropped"; fi
log "DECISION: drop ${DROP:-nothing}  [$WHY]"
pkill -f m2final_phase2.sh; pkill -f "gate_set.sh f3m"; pkill -f "run_cases.sh . f3m"   # no further variant starts; a running Freya sim is not killed
while [ ! -f out/f28_merged ] && [ "$(now)" -lt 1932 ]; do sleep 10; done
[ -f out/f28_merged ] && log "f28 hardening merged" || log "WARNING: no f28 merge marker by 19:32: proceeding with main as it is"
FL="$(tr -d '\n ' < M1_FLAGS.txt),f28_tool_failure,f29_scam_open"
[ -n "$DROP" ] || FL="$FL,f22_forbidden_disclosure"
log "FINAL flag list (before the ,-f18_opening_fallback ending): $FL"
scripts/amend_flags.sh "$FL" 2>&1 | tee -a $L
grep -q "AMENDED" $L || { log "AMEND DID NOT COMPLETE: no dress run (tell S0)"; exit 2; }
log "FINAL_FLAGS.txt: $(cat FINAL_FLAGS.txt)"; log "starting the dress run"
exec scripts/dress_run.sh
