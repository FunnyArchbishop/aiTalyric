"""ex06: hand-edit the expansion, then render it.

`--dump-slots` writes every realized note (with its decoded pitch and chord);
`--from-slots` renders that file back, so anything the ruleset got wrong can be
fixed note by note without touching the code.

    python examples/ex06_hand_edit_slots.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.makedirs("out_examples", exist_ok=True)


def run(*args):
    return subprocess.run([sys.executable] + list(args),
                          capture_output=True, text=True)


# 1. dump
r = run("run_groove.py", "--cell-theme", "sync",
        "--dump-slots", "out_examples/slots.json",
        "--out", "out_examples/groove")
print("[dump]", [l for l in r.stdout.splitlines() if "slots" in l][:1])

doc = json.load(open("out_examples/slots.json", encoding="utf-8"))
print("notes:", len(doc))
print("first three:", [(d["char"], d["name"] if "name" in d else d["midi"],
                       d["start"], d["dur"]) for d in doc[:3]])

# 2. edit: raise the third note an octave, and delay the fifth by a 16th
doc[2]["midi"] += 12
doc[4]["start"] += 0.125
doc[4]["start_cell"] += 0.5
json.dump(doc, open("out_examples/slots_edited.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("edited note 3 ->", doc[2]["midi"], "| note 5 start ->", doc[4]["start"])

# 3. render the edited file
r = run("run_groove.py", "--from-slots", "out_examples/slots_edited.json",
        "--out", "out_examples/groove_edited")
print("[render]", [l for l in r.stdout.splitlines() if l.startswith("melody")][:1])
if r.returncode:
    print(r.stdout[-500:], r.stderr[-500:])
