#!/usr/bin/env python3
"""PreToolUse hook (Bash matcher): denies shell constructs the permission
engine can't reliably allow-list (literal text differs every invocation),
so an autonomous run gets an instant, actionable rejection instead of
hanging on a prompt nobody is there to answer.

Deliberately narrow: does NOT block bare command substitution like
$(date) or $(cat <<'EOF' ...) used inline as an argument (e.g. the
standard git commit heredoc pattern) - only substitution assigned to a
variable for reuse, bash arrays, and inline for/while/if control flow.
"""
import json
import re
import sys

CHECKS = [
    (re.compile(r'[A-Za-z_][A-Za-z0-9_]*=\$\('),
     "command substitution assigned to a variable (VAR=$(...))"),
    (re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*=\([^)]*\)'),
     "bash array assignment (arr=(...))"),
    (re.compile(r'\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}'),
     "bash array expansion (${arr[@]})"),
    (re.compile(r'\bfor\s+\w+\s+in\b.*\bdo\b', re.DOTALL),
     "inline for loop"),
    (re.compile(r'\bwhile\b.*\bdo\b', re.DOTALL),
     "inline while loop"),
    (re.compile(r'\bif\s*\[.*\bthen\b', re.DOTALL),
     "inline if conditional"),
]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    command = (data.get("tool_input") or {}).get("command") or ""
    for pattern, label in CHECKS:
        if pattern.search(command):
            reason = (
                f"Blocked by project policy: command contains {label}. "
                "This can't be reliably allow-listed and would hang an "
                "unattended run waiting on a prompt. Rewrite as a named "
                "script at pipeline/_taskname.py and run it via "
                "`.venv/bin/python pipeline/_taskname.py`, or split into "
                "separate plain commands."
            )
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }))
            return


if __name__ == "__main__":
    main()
