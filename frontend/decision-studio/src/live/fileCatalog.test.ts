import { describe, expect, it } from 'vitest'
import { catalogFilter, catalogReadState, catalogSize, catalogType } from './fileCatalog'

const entry = (name: string, overrides: Record<string, unknown> = {}) => ({
  name,
  is_dir: false,
  size: 1024,
  columns: [],
  ...overrides,
})

describe('project file catalog labels', () => {
  it('labels common local data and document formats for people', () => {
    expect(catalogType(entry('sales.csv'))).toBe('CSV 数据表')
    expect(catalogType(entry('features.xlsx'))).toBe('Excel 工作簿')
    expect(catalogType(entry('readme.md'))).toBe('Markdown 文档')
    expect(catalogFilter(entry('sales.csv'))).toBe('data')
    expect(catalogFilter(entry('readme.md'))).toBe('other')
  })

  it('reports only the file information the catalog actually reads', () => {
    expect(catalogReadState(entry('sales.csv', { columns: ['date', 'sales'] }))).toEqual({
      label: '2 个字段',
      detail: '可用于研发数据预览',
      tone: 'read',
    })
    expect(catalogReadState(entry('sales.csv'))).toEqual({
      label: '未发现字段名',
      detail: '',
      tone: 'quiet',
    })
    expect(catalogReadState(entry('sales.csv', { header_error: 'read failure' }))).toMatchObject({
      label: '字段名读取失败',
      tone: 'warning',
    })
    expect(catalogReadState(entry('instructions.pdf'))).toMatchObject({
      label: '本地文件',
      tone: 'quiet',
    })
    expect(catalogReadState(entry('archive', { is_dir: true }))).toMatchObject({
      label: '文件夹',
      tone: 'quiet',
    })
  })

  it('formats file sizes without turning unknown directory size into zero', () => {
    expect(catalogSize(0)).toBe('0 B')
    expect(catalogSize(2048)).toBe('2.0 KB')
    expect(catalogSize(2 * 1024 * 1024)).toBe('2.0 MB')
    expect(catalogSize(null)).toBe('')
  })
})
