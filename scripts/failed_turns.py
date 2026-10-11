"""Our OWN self-test transcripts only (never GATE): the conversation turns (user/assistant, numbered like the judge's 'Message N') of the failed scenarios.
python3 scripts/failed_turns.py <selftest dir> <case:from-to> ..."""
import json, sys
D = sys.argv[1]
for spec in sys.argv[2:]:
    case, rng = spec.split(":"); a, b = map(int, rng.split("-"))
    m = [x for x in json.load(open(f"{D}/transcripts/{case}.json"))["messages"] if x.get("role") in ("user", "assistant")]
    print("==", case, f"({len(m)} turns)")
    for i in range(a, b + 1):
        if 0 < i <= len(m):
            print(f" #{i} {m[i-1]['role'][:4]}: {str(m[i-1].get('message'))[:240]}")
