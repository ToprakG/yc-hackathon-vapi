#!/bin/bash
# The three files to attach to the e-mail to yavuz@freyavoice.ai (NOTHING is sent): submission.json, the exported workflow, the trace file -> out/final_send/.
#   scripts/collect_send.sh        prints the paths; refuses (exit 1) if submission.json fails scripts/finish_submission.py --check-only or a file is missing / untracked
cd "$(dirname "$0")/.." || exit 1
rm -rf out/final_send; mkdir -p out/final_send
.venv310/bin/python scripts/finish_submission.py --check-only > out/final_send/check.txt 2>&1 || { cat out/final_send/check.txt; echo "submission.json does not pass finish_submission --check-only: NOT collected"; exit 1; }
read -r W T < <(python3 -c "import json;s=json.load(open('submission.json'));print(s['workflow'],s['trace'])")
for f in submission.json "$W" "$T"; do [ -f "$f" ] || { echo "missing: $f"; exit 1; }; cp "$f" out/final_send/; done
echo "attach these three files (send NOTHING from here):"; ls -l out/final_send/ | tail -3 | awk '{print "  " $NF, $5 " bytes"}'
echo "folder: $(pwd)/out/final_send   commit: $(git rev-parse --short HEAD)   tag final-submit: $(git rev-parse --short final-submit 2>/dev/null)"
python3 -c "import json;s=json.load(open('submission.json'));print('mock_url:',s['mock_url'],'| team:',s.get('team'),'| members:',[m.get('name') for m in s.get('members',[])])"
