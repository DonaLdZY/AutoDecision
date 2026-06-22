from pathlib import Path
for p in [Path('runs/城市配送/autorealize/realize_report/automl_context.md'), Path('runs/城市配送/autorealize/realize_report/automl_context_pack.json'), Path('runs/城市配送/autorealize/description.md')]:
    if not p.exists():
        continue
    text = p.read_text(encoding='utf-8-sig', errors='replace')
    print('--- ' + str(p))
    print('chars=' + str(len(text)) + ' approx_tokens=' + str(round(len(text)/2.2)))
    heads = [line for line in text.splitlines() if line.startswith('#')]
    print('\n'.join(heads[:40]))
