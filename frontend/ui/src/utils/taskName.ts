export function displayTaskName(name: string | null | undefined): string {
  return (name || '').replace(/^工业实例[\s_-]*/, '')
}
