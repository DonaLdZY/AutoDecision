import { record } from './presentation'

export function canEditSchema(value: unknown, depth = 0): boolean {
  const schema = record(value)
  if (depth > 8 || schema.$ref || schema.oneOf || schema.anyOf || schema.allOf) return false
  if (Array.isArray(schema.enum) && schema.enum.every((v) => ['string', 'number', 'boolean'].includes(typeof v))) return true
  if (['string', 'number', 'integer', 'boolean'].includes(String(schema.type))) return true
  if (schema.type === 'array') return canEditSchema(schema.items, depth + 1)
  if (schema.type === 'object' || schema.properties) {
    const fields = Object.values(record(schema.properties))
    return fields.length > 0 && fields.every((s) => canEditSchema(s, depth + 1))
  }
  return false
}

export function emptySchemaValue(value: unknown): unknown {
  const schema = record(value)
  // Defaults are not measurements. Only create containers; users fill values.
  if (schema.type === 'array') return []
  if (schema.type === 'object' || schema.properties) return {}
  return undefined
}


/** Bound the inline form size without changing or dropping submitted records. */
export function isBulkInput(value: unknown): boolean {
  let fields = 0
  const pending: unknown[] = [value]
  while (pending.length) {
    const current = pending.pop()
    if (!current || typeof current !== 'object') continue
    const entries = Array.isArray(current) ? current : Object.values(current)
    fields += entries.length
    if (entries.length > 100 || fields > 500) return true
    pending.push(...entries)
  }
  return false
}
