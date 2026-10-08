import katex, { type KatexOptions } from 'katex'
import { Marked, type TokenizerAndRendererExtension } from 'marked'
import markedKatex from 'marked-katex-extension'
import 'katex/dist/katex.min.css'
import './markdownMath.css'

const options: KatexOptions = {
  throwOnError: false,
  trust: false,
  strict: 'ignore',
  maxExpand: 1000,
  maxSize: 30,
  output: 'htmlAndMathml',
}

function latexDelimiter(name: string, level: 'block' | 'inline', rule: RegExp, start: RegExp, displayMode: boolean): TokenizerAndRendererExtension {
  return {
    name,
    level,
    start: source => source.match(start)?.index,
    tokenizer(source) {
      if (this.lexer.state.inRawBlock) return
      const match = source.match(rule)
      if (match) return { type: name, raw: match[0], text: match[1]!.trim() }
    },
    renderer: token => katex.renderToString(String(token.text), { ...options, displayMode }),
  }
}

const dollarMath = markedKatex({ ...options, nonStandard: true })
for (const extension of dollarMath.extensions ?? []) {
  if (!('tokenizer' in extension) || extension.level !== 'inline') continue
  const tokenize = extension.tokenizer
  extension.tokenizer = function (source, tokens) {
    if (this.lexer.state.inRawBlock) return
    return tokenize.call(this, source, tokens)
  }
}

// Marked tokenizers keep math out of fenced, indented and inline code without rewriting Markdown.
const parser = new Marked(dollarMath, {
  extensions: [
    latexDelimiter('latexBlock', 'block', /^ {0,3}\\\[([\s\S]*?)\\\](?:[ \t]*(?:\n|$))/, /(?:^|\n) {0,3}\\\[/, true),
    latexDelimiter('latexDisplay', 'inline', /^\\\[([\s\S]*?)\\\]/, /\\\[/, true),
    latexDelimiter('latexInline', 'inline', /^\\\(([\s\S]*?)\\\)/, /\\\(/, false),
  ],
})

export function renderMathMarkdown(source: string): string {
  return parser.parse(source, { async: false, breaks: false })
}
