# Store Sales Forecast

Use `train.csv` to predict `sales` for every row in `predict.csv`.

- `row_id` is the unique output identifier and must not be used as a target proxy.
- `store_id` identifies the store.
- `day_index` is the chronological day number.
- `promotion` is `1` when a promotion is active and `0` otherwise.
- `weekday` uses `0` for Monday through `6` for Sunday.
- Evaluate predictions with mean absolute error (MAE); lower is better.
- The output must contain exactly `row_id,sales` in the same row order as `predict.csv`.
- Predicted sales must be finite and non-negative.

`sample_submission.csv` defines the required output schema. Its placeholder sales
values are not labels and must not be used for training or validation.
