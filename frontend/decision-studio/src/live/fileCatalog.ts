export interface CatalogEntry {
  name: string
  is_dir: boolean
  size: number | null
  columns: string[]
  header_error?: string
}

export type CatalogFilter = 'all' | 'data' | 'folders' | 'other'

const DATA_EXTENSIONS = new Set(['.csv', '.xls', '.xlsx', '.parquet', '.feather', '.orc'])

function extension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot).toLowerCase() : ''
}

export function catalogFilter(entry: CatalogEntry): Exclude<CatalogFilter, 'all'> {
  if (entry.is_dir) return 'folders'
  return DATA_EXTENSIONS.has(extension(entry.name)) ? 'data' : 'other'
}

export function catalogType(entry: CatalogEntry): string {
  if (entry.is_dir) return '文件夹'
  const labels: Record<string, string> = {
    '.csv': 'CSV 数据表',
    '.xls': 'Excel 工作簿',
    '.xlsx': 'Excel 工作簿',
    '.parquet': 'Parquet 数据表',
    '.feather': 'Feather 数据表',
    '.orc': 'ORC 数据表',
    '.json': 'JSON 文件',
    '.jsonl': 'JSONL 文件',
    '.ndjson': 'NDJSON 文件',
    '.md': 'Markdown 文档',
    '.txt': '文本文件',
    '.pdf': 'PDF 文档',
    '.zip': '压缩文件',
    '.yaml': 'YAML 文件',
    '.yml': 'YAML 文件',
    '.py': 'Python 文件',
  }
  return labels[extension(entry.name)] || '其他文件'
}

export function catalogReadState(entry: CatalogEntry): {
  label: string
  detail: string
  tone: 'read' | 'warning' | 'quiet'
} {
  if (entry.is_dir) return { label: '文件夹', detail: '', tone: 'quiet' }
  if (extension(entry.name) !== '.csv') {
    return { label: '本地文件', detail: '', tone: 'quiet' }
  }
  if (entry.header_error) {
    return { label: '字段名读取失败', detail: entry.header_error, tone: 'warning' }
  }
  if (entry.columns.length) {
    return { label: `${entry.columns.length} 个字段`, detail: '可用于研发数据预览', tone: 'read' }
  }
  return { label: '未发现字段名', detail: '', tone: 'quiet' }
}

export function catalogSize(size: number | null): string {
  if (size === null) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
