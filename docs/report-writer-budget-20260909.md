# Report Writer Context Budget Fix

Delivery report failure at 2026-09-09 10:38 local time occurred before the writer
sent an API request. Six original-source partitions had been read successfully.
`generate_report` appended all six reading notes to the method analysis, and the
writer attempted to send that combined analysis with the shared task rules and
selected result facts in a single request. The partition planner's fixed reserve
did not account for the accumulated reading output.

Using the matching archived task definition and saved report analysis reproduced
approximately 77,687 input tokens versus a 74,712 input budget. Configuration was
131,072 context tokens, 32,768 output tokens, and 18 percent context headroom.
These are local estimates, not provider-reported usage for the rejected request.

The saved analyzer response also contained malformed outer JSON. The old parser
scanned inner opening braces and accepted the valid `problem` object as the whole
analysis, silently losing method cards, reuse details and retrieval requests.

Changes:

- Oversized writing input is split losslessly into derived-analysis partitions.
  The writer creates an initial article, then incorporates each partition via
  exact edits. Complete original-task audits still follow this writing step.
- A coverage manifest checks every original analysis value and string range.
  Derived notes cannot override original task rules or measured evidence.
- JSON parsing requires a complete object, and the analyzer requires its
  top-level fields. Malformed output is retried instead of accepting a subobject.
- Retry diagnostics fit the available budget; a long invalid response is omitted
  from a retry if it would crowd out the complete original request.
- Context errors include token/character breakdowns and cannot be classified as
  exhausted semantic review, including under continue-on-exhaustion policy.

The output token limit, context size, source rules and active task configuration
are unchanged. Services spawn fresh report workers, so the next report invocation
loads the fix without restarting the running data-understanding task.

Verification used the actual failed input with a local transport stub. Its three
writer-stage requests measured approximately 38,781, 59,933 and 56,770 tokens;
all fit, and all source notes passed structural coverage verification. This was
an input-orchestration replay, not an actual generated or approved business report.

Reproduce:

```powershell
python scripts/diagnose-report-budget.py <report-directory> --archived-autorealize <matching-archive> --exercise-writer
```

The delivery task was already rerunning AutoRealize while this fix was being
verified. Its current artifacts were not overwritten with the archived report.
