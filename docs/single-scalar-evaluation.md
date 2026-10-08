# Single Scalar Evaluation

The final search metric is one finite numeric scalar with one direction.
Multiple business components may be recorded for audit, but tuples, layered
rankings, Pareto outputs, and extra business tie-breaks are not search metrics.

AutoRealize must choose and disclose fixed scalarization assumptions when no
official weights exist. Preserve declared business priorities, exact billing
rules, hard constraints, and the frozen evaluation population. Freeze all weights,
scales, aggregation rules, and parameter derivations before candidate search.
Do not allow each candidate to choose its own scoring rule.

For integer completed-order count N and finite nonnegative cost C, one conditional
example is maximizing `N - C/(B+C)` with a shared fixed positive cost scale B.
In exact arithmetic its cost term is less than one, preserving order priority.
This is not a universal floating-point guarantee: check the supported domain and
smallest required cost differences in the final score. The generated evaluator
must retain raw counts and costs. A composite score's percentage increase does
not measure cost savings or order growth.

`score_representation` records the final output shape. Generation and repair
reject non-scalar declarations, including legacy wording that explicitly refuses
scalarization. The deterministic check detects recognizable structural errors;
it does not prove arbitrary natural-language mathematics or business correctness.
Semantic artifact review and executable evaluator validation remain necessary.

## Verification

- 120 focused AutoRealize tests: scalar shape, false first-round approval, repair
  exhaustion, execution handoff, contract rendering and existing repair behavior.
- 56 AlgoEvolve tests: provider compatibility, prompt constraints, result review,
  decision evaluation and search score phase.
- 42 AutoReport tests: report content, compatible comparisons and report pipeline.
- Frontend TypeScript check and production build passed.

Live probes used the currently configured AutoRealize DeepSeek model and a
32768-token output limit, using the production contract compiler. Three prompt
iterations each exercised delivery scalarization and a separate RMSE regression
fixture. These probes did not execute AutoML or update any live task.

The probes caught additional issues: missing dates being treated as permission
to omit constraints, optional/unbound scalarization branches, restrictions on
legitimate development-set selection, and prediction-dependent denominators.
Instructions were tightened and both cases were rerun. The final RMSE probe
retained its fixed population and allowed development-set model selection. The
delivery probe returned a fixed-parameter scalar and retained the missing-date
restriction, but still included unnecessary requests for a cost bound/vehicle IDs
and incomplete numerical verification. Its output is a prompt test artifact, not
an approved replacement for the live delivery task contract.

Final probe artifacts under `runs/prompt-validation`:

- `scalar-delivery-1788883312433882400/result.json`
- `scalar-prediction-1788883312777012600/result.json`

Provider-reported final probe usage: delivery had 2 calls, 14406 input tokens,
3584 cached input tokens and 6288 output tokens; prediction had 1 call, 5229
input tokens, 2432 cached input tokens and 1969 output tokens. These isolated
requests do not establish a production cache-hit rate.

Existing task definitions, search journals and scores are preserved. Future
generation/repair uses the new policy; changed evaluation contracts require
reevaluation before scores can be compared.
