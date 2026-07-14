import { onMounted, readonly, shallowRef } from 'vue'
import { api } from '../api'
import type { ResourceInventory } from '../types'

export function useAcceleratorInventory() {
  const inventory = shallowRef<ResourceInventory | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef('')

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      inventory.value = await api.getResourceInventory()
    } catch (reason) {
      error.value = (reason as Error).message
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    void refresh()
  })

  return {
    inventory: readonly(inventory),
    loading: readonly(loading),
    error: readonly(error),
    refresh,
  }
}
