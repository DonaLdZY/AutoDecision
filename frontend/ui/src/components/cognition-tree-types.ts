export type ReadState = 'unread' | 'reading' | 'read' | 'skipped' | 'failed' | 'partial'

export type CognitionTreeNode = {
  name: string
  path: string
  isDir: boolean
  children: CognitionTreeNode[]
  readState: ReadState
}

export function readStateLabel(state: ReadState) {
  if (state === 'read') return '已读'
  if (state === 'skipped') return '不读(抽样)'
  if (state === 'reading') return '读取中'
  if (state === 'failed') return '读取失败'
  if (state === 'partial') return '部分完成'
  return '未读'
}
