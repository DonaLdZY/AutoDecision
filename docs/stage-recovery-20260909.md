# Stage recovery and report completion

## Request budgets

The selected DeepSeek text model uses a 278,528-token context window and a
278,528-token output ceiling. Each request assigns its output allowance from the
remaining context after the complete estimated input and an 18% estimation
margin. Requests retain at least 32,768 output tokens or fail before transport
without silently removing task constraints. The ceiling is not a target length.

## Recovery behavior

- Review repair is available only for an interrupted/failed task-definition stage
  with a saved cognition checkpoint and no downstream AutoML/report artifacts.
- The backend issues a signed file-impact manifest. A missing or stale manifest,
  completed/running task, or duplicate submission is rejected.
- Repair runs in a separate directory and restores cognition, including original
  constraints and investigation results. Changed source inputs are rejected.
- Failed repairs leave live artifacts intact. Successful repairs archive the old
  definition before publication. Protected cognition files are compared before
  publication, and a failed copy restores the original directory.
- Report recovery selects the report stage before checking upstream readiness.
  Interrupted stage identity is persisted across stops and gateway restarts.
- Report reruns archive previous results and reset service logs. Reports use the
  frozen AutoML input and disclose changes to the live task definition.
- Frontend confirmation lists the replacement/archive scope and every current
  file. The confirmation remains usable on desktop and mobile.

## Delivery report

Task: c4ea05c56bac42839ce2737ca483cad7. Completed through AutoReport with DeepSeek,
including analysis, six candidate comparisons, writing, and complete report
audit. Four independently reviewed editorial edits correct the scalar proof
and display title; the generator adds the task-definition version notice.
Prior audit, exact edits, and original report files remain in stage history.
No cognition or AutoML rerun was performed.

Five successful report requests returned 710,380 input tokens, 534,144 cache-hit
tokens (75.19%), and 156,391 output tokens, including reasoning. Configured output
ceiling was 278,528; actual per-request allowances were around 84K to 96K.
The regenerated live description retained SHA-256
5af41fbf8a725d23e95ac30b6e0afc6b7724e94df94d70b693ab2cf4b1419c50.

The report explicitly distinguishes candidate-reported scores from independently
recomputed business outcomes. Missing dates and other unverified business
constraints remain disclosed; report completion does not certify deployment.

## Verification

- Backend suite: 119 passed.
- AutoReport suite: 89 passed.
- AutoRealize affected tests: cognition restore, request allocation, task-definition
  pipeline, usage logging, stable cognition ordering; live pipeline smoke is
  skipped when its opt-in environment is absent.
- AlgoEvolve request/runtime and usage regression tests passed.
- Frontend: 54 tests passed, production build passed.
- Playwright: completed/report-failed tasks cannot repair upstream; cancellation
  sends no mutation; confirmation sends the manifest token. Desktop/mobile
  screenshots include a 200-file impact list and the actual completed report.
