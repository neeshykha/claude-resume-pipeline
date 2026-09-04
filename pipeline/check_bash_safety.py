#!/usr/bin/env python3
"""PreToolUse hook (Bash matcher): denies shell constructs the permission
engine can't reliably allow-list (literal text differs every invocation),
so an autonomous run gets an instant, actionable rejection instead of
hanging on a prompt nobody is there to answer.

WIDENED 2026-09-04, after an audit showed it caught almost none of what it
was built for. On the 2026-09-04 run it denied exactly one shape (`while`)
while letting through `until` loops, `;`/`&&` chains, pipes, inline
`python -c`, and the bare `$(...)` that produced a live permission prompt
("Contains command_substitution") mid-run. Two of those prompts were
screenshotted by Aneesh; the rest would have hung an unattended pass.

Two design rules, both load-bearing:

1. OPERATOR CHECKS RUN ON THE COMMAND WITH QUOTED SPANS REMOVED. `grep -E
   "Mercury|CodePath"` is a legitimate, frequently-used command whose pipe
   lives inside a quoted regex, and a naive substring check would deny it.
   Strip quotes first, then look for bare operators.

2. THE HEREDOC CARVE-OUT SURVIVES. `$(cat <<'EOF' ... EOF)` is the standard
   way to write a multi-line git commit message, and the attribution trailer
   requires one. Bare `$(...)` is denied; `$(cat <<` is not.

Redirects (`>`, `>>`) are deliberately NOT blocked. They are statically
analyzable, so they are an allow-list question rather than a shape problem.
The reason `printf 'x' >> file` prompted on 2026-09-04 is that `printf` is
not in settings.json's allow list, which is a separate fix.
"""
import json
import re
import sys

# Quoted spans are stripped before most checks; see design rule 1. The two
# strip modes are not interchangeable, and the difference is shell semantics
# rather than taste: `|`, `;`, `&&` and `||` are inert inside BOTH quote
# types, while `$(...)` and backticks are inert inside single quotes and
# still EXPAND inside double quotes. Stripping double quotes before the
# substitution check hides exactly the case that prompted on 2026-09-04
# (`git commit -m "... $(date +%F)"`), which is how this was caught.
_Q_ALL = re.compile(r"'[^']*'|\"[^\"]*\"")
_Q_SINGLE = re.compile(r"'[^']*'")

STRIPPERS = {
    "raw": lambda c: c,
    "single": lambda c: _Q_SINGLE.sub("", c),
    "all": lambda c: _Q_ALL.sub("", c),
}

# (pattern, label, remedy, strip_mode)
CHECKS = [
    (re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*=\([^)]*\)'),
     "bash array assignment (arr=(...))",
     "Use a named script at pipeline/_taskname.py instead.", "all"),
    (re.compile(r'\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}'),
     "bash array expansion (${arr[@]})",
     "Use a named script at pipeline/_taskname.py instead.", "all"),
    (re.compile(r'\bfor\s+\w+\s+in\b.*\bdo\b', re.DOTALL),
     "inline for loop",
     "Use a named script at pipeline/_taskname.py instead.", "all"),
    (re.compile(r'\b(?:while|until)\b.*\bdo\b', re.DOTALL),
     "inline while/until loop",
     "To wait on a background task, read its output file with the Read "
     "tool or use the Monitor tool; do not spin in the shell.", "all"),
    (re.compile(r'\bif\s*\[.*\bthen\b', re.DOTALL),
     "inline if conditional",
     "Use a named script at pipeline/_taskname.py instead.", "all"),
    (re.compile(r'\bpython3?\s+-c\b'),
     "inline python (-c)",
     "Write pipeline/_taskname.py and run it with "
     "`.venv/bin/python pipeline/_taskname.py`, then delete it.", "all"),
    # Command substitution: single-quote strip only, because $(...) still
    # expands inside double quotes. Carve-out for the git heredoc form.
    # The (?<!\\) guards are load-bearing: a backslash-escaped \$( or \` is
    # inert, and without them this hook denies any command whose text merely
    # MENTIONS command substitution. Found immediately, when the commit
    # message describing this very change was blocked by it.
    (re.compile(r"(?<!\\)\$\((?!\s*cat\s+<<)"),
     "command substitution ($(...))",
     "Substitute the literal value yourself. To inspect a background "
     "process, read the task output file the harness returned rather than "
     "shelling out to ps/pgrep.", "single"),
    (re.compile(r'(?<!\\)`[^`]+`'),
     "backtick command substitution",
     "Substitute the literal value yourself.", "single"),
    (re.compile(r'\|\|'),
     "|| chaining",
     "Split into separate Bash calls and branch on the result yourself.",
     "all"),
    (re.compile(r'&&'),
     "&& chaining",
     "Split into separate Bash calls.", "all"),
    (re.compile(r';'),
     "; chaining",
     "Split into separate Bash calls.", "all"),
    (re.compile(r'\|'),
     "pipe",
     "Run the first command alone and read its output, or move the whole "
     "thing into pipeline/_taskname.py.", "all"),
]


def evaluate(command: str):
    """Return (label, remedy) for the first violated check, or None."""
    for pattern, label, remedy, mode in CHECKS:
        if pattern.search(STRIPPERS[mode](command)):
            return label, remedy
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    command = (data.get("tool_input") or {}).get("command") or ""
    hit = evaluate(command)
    if not hit:
        return
    label, remedy = hit
    reason = (
        f"Blocked by project policy: command contains {label}. This can't be "
        f"reliably allow-listed and would hang an unattended run waiting on a "
        f"prompt nobody is there to answer. {remedy}"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
