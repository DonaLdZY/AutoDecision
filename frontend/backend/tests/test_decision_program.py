import pytest

from decision_program import run_program, validate_program


def test_decision_uses_one_real_call_and_aggregates_unmodified_output():
    code = '''def decide(data):
    result = run_model(data)
    top = sorted(result, key=lambda row: row["price"], reverse=True)[:2]
    average = sum(row["price"] for row in result) / len(result) if result else 0
    return {"answer": f"预测 {len(result)} 条，均值 {average:.2f}。", "facts": {"top": top}}
'''
    calls = []
    rows = [{"price": 10}, {"price": 40}, {"price": 20}]

    def model(data):
        calls.append(data)
        return rows

    actual, decision = run_program(code, {"input": True}, model)
    assert actual is rows and calls == [{"input": True}]
    assert decision["answer"] == "预测 3 条，均值 23.33。"
    assert decision["facts"]["top"] == [{"price": 40}, {"price": 20}]
    assert rows == [{"price": 10}, {"price": 40}, {"price": 20}]


@pytest.mark.parametrize("suffix", [
    'import os\n    return {"answer": "x"}',
    'return {"answer": open("secret").read()}',
    'return {"answer": result.__class__}',
    'return {"answer": getattr(result, "secret")}',
    'return {"answer": decide(data)}',
    'return {"answer": run_model(data)}',
    'sum = 2\n    return {"answer": "x"}',
    'return {"answer": result.pop("x")}',
    'return {"answer": str(data)}',
    'return {"answer": "没有使用输出"}',
    'result = []\n    return {"answer": str(result)}',
    'result[0]["price"] = 1\n    return {"answer": str(result)}',
    'alias = result\n    alias[0] = 1\n    return {"answer": str(result)}',
    'return {"answer": str([result for result in []])}',
    'while True:\n        pass',
])
def test_untrusted_program_cannot_escape_frozen_call_or_repeat_it(suffix):
    with pytest.raises(ValueError):
        validate_program("def decide(data):\n    result = run_model(data)\n    " + suffix + "\n")


def test_decision_must_return_readable_answer_and_finite_facts():
    with pytest.raises(ValueError, match="answer"):
        run_program('def decide(data):\n    result = run_model(data)\n    return {"facts": result}\n',
                    {}, lambda data: [])


def test_ranked_predictions_can_form_readable_markdown_without_extra_model_calls():
    code = '''def decide(data):
    result = run_model(data)
    top = sorted(result, key=lambda row: row["price"], reverse=True)[:3]
    lines = "\\n".join(f"- 房源{row['id']}：预测{row['price']:.2f}元" for row in top)
    return {"answer": f"预测价格排名：\\n{lines}"}
'''
    rows = [{'id': 1, 'price': 20}, {'id': 2, 'price': 40}]
    _, decision = run_program(code, {}, lambda data: rows)
    assert decision['answer'] == '预测价格排名：\n- 房源2：预测40.00元\n- 房源1：预测20.00元'
    with pytest.raises(ValueError):
        run_program('def decide(data):\n    result = run_model(data)\n    return {"answer": "结果", "facts": float("nan")}\n',
                    {}, lambda data: [])
