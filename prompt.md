# prompt.md: copy-paste prompts for Claude

Claude reads `CLAUDE.md` automatically (project, rules, commands). These templates add the
task-specific part. Fill in `<...>`, delete lines you don't need.

Structure used everywhere: **ROLE → TASK → CONTEXT → CONSTRAINTS → DONE WHEN → OUTPUT**.
The headers matter less than actually filling in CONTEXT and DONE WHEN; those are what
change the result.

---

## Mode switches (add one line at the end of any prompt)

| Line | When |
|---|---|
| `MODE: caveman. Short words. No filler. Code + result only.` | Quick fixes, status checks, saving tokens |
| `MODE: plan first. Give 3–5 bullets, wait for my OK before editing.` | Anything touching more than one file |
| `MODE: explain. Full sentences, say why, one concrete example.` | Learning, reviews, pitch material |

Don't use caveman for reviews, rule questions or anything for the jury: it drops the *why*.

---

## 1. New task (default)

```
ROLE: <solver | simulator | data-layer> developer on this repo.
TASK: <one or two sentences>
CONTEXT: <relevant files, current numbers, what you already tried>
CONSTRAINTS: <files not to touch, time budget, no API calls>
DONE WHEN: <test passes / score on big ≥ X / file exists>
OUTPUT: summary of changes + how you verified them.
MODE: plan first.
```

## 2. Improve the solver score

```
ROLE: optimisation engineer working on solver/.
TASK: raise the score on <scenario_big>.
CONTEXT: currently <score>, <n>/<N> orders. Read out/compare.md and out/operators.json first.
CONSTRAINTS: one change at a time; keep evaluator parity (pytest + tools.parity compare);
             no API Simulate/Score calls; solver stays standard-library only.
DONE WHEN: score improves with `python run.py <folder> --time 60`, same seed, before vs after.
OUTPUT: table: before | after | what changed. Then where points are still lost.
```

## 3. Debug

```
ROLE: debugger. Find the cause before changing code.
TASK: <what's wrong>
CONTEXT:
  Expected: <...>
  Reproduce: <command>
  Output / error:
  <paste the real output>
CONSTRAINTS: smallest fix that works; don't refactor around it.
DONE WHEN: the reproduce command gives the expected result and pytest passes.
OUTPUT: root cause in 2–3 sentences, then the fix.
MODE: caveman.
```

## 4. Rule question (simulator vs API)

```
ROLE: API rules auditor.
TASK: does the API <do X> when <situation>?
CONTEXT: check docs/semantics.md and simulator/simulator.py first.
CONSTRAINTS: don't send any API call. Validate is free; Simulate/Score are limited.
DONE WHEN: answered from verified sources, or a probe plan is ready.
OUTPUT: answer + source (file:line). If unverified: the smallest probe plan and which call it needs.
MODE: explain.
```

## 5. Review before merge

```
ROLE: strict reviewer, as if the jury will run this plan.
TASK: review branch <name> vs main.
CONSTRAINTS: don't fix anything yet.
DONE WHEN: pytest and tools.parity compare were run and findings listed.
OUTPUT: findings, most serious first, each with file:line and a failing scenario.
MODE: explain.
```

## 6. Pitch / explanation

```
ROLE: <the jury: logistics experts, not programmers | a teammate new to the code>.
TASK: explain <part / algorithm> to them.
CONTEXT: use real numbers from scenario_<x> (out/compare.md).
CONSTRAINTS: max <N> sentences, no jargon, one concrete example.
OUTPUT: <slide text | paragraph | 3 bullets>.
```
Here ROLE is the **audience**, not Claude: that works better than "you are an expert".

---

### Tips that actually matter
- One task per conversation; start a new one when the topic changes (`/clear`).
- Paste real output (scores, errors). Don't describe it from memory.
- Say what "done" means. "Make it better" gives random changes.
- Plan first for anything bigger than a small edit.
- Competitive scenario: 3 Simulate + 3 Score calls total. Claude must ask before using one.
