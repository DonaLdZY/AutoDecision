<script setup lang="ts">
import { computed } from 'vue'
import { useAcceleratorInventory } from '../composables/useAcceleratorInventory'
import type { AcceleratorDevice, TaskResourceConfig } from '../types'

const model = defineModel<TaskResourceConfig>({ required: true })
const props = defineProps<{ disabled?: boolean }>()
const { inventory, loading, error, refresh } = useAcceleratorInventory()

const selectableDevices = computed(() => (inventory.value?.devices ?? []).filter((item) => item.visibility_supported))
const allSelectableIds = computed(() => selectableDevices.value.map((item) => item.id))
const selectedIds = computed(() => {
  if (model.value.accelerator_mode === 'all') return new Set(allSelectableIds.value)
  if (model.value.accelerator_mode === 'none') return new Set<string>()
  return new Set(model.value.accelerator_device_ids)
})

const cpuMaximum = computed(() => Math.max(1, inventory.value?.cpu.available_ids.length || inventory.value?.cpu.logical_count || 1))
const memoryMaximum = computed(() => Math.max(0, inventory.value?.memory.total_gb || 0))
const memoryLimitHint = computed(() => {
  const enforcement = inventory.value?.memory.enforcement
  if (enforcement?.hard_limit_supported) {
    return '系统会限制整个任务进程组的总内存；超额申请在对应节点内失败，MLEvolve 主任务继续搜索。'
  }
  if (enforcement?.backend === 'posix_rlimit_as_plus_child_guard') {
    return '当前系统使用每进程地址空间上限和进程树监控；超限执行子进程会失败或被停止，MLEvolve 主任务继续搜索。'
  }
  return '当前平台使用子进程保护模式；超限时仅停止占用过大的执行子进程，MLEvolve 主任务继续搜索。'
})
const cpuLimitHint = computed(() => {
  const enforcement = inventory.value?.cpu.enforcement
  if (enforcement?.hard_limit) {
    return '系统通过进程 affinity 将整个任务限制在所选逻辑核心集合内。'
  }
  return '当前系统不支持精确核心绑定，将通过限制并行 worker 和数值库线程预算控制 CPU 使用量。'
})
const acceleratorLimitHint = computed(() => {
  const nonIsolatable = inventory.value?.accelerator?.non_isolatable_device_ids ?? []
  const base = '勾选项决定该任务可见的设备，不代表设备独占或显存配额。'
  if (nonIsolatable.length > 0) {
    return `${base} ${nonIsolatable.join('、')} 不支持按进程隐藏，界面会标记为不可隔离。`
  }
  return `${base} 运行环境不可用表示任务配置的 Python/PyTorch 暂时不能使用该设备。`
})
const configuredRuntimeLabel = computed(() => {
  const torch = inventory.value?.torch
  if (!torch) return ''
  const executable = torch.python_executable || 'unknown Python'
  return `${executable} · PyTorch ${torch.version || '未安装'}`
})

function updateResources(patch: Partial<TaskResourceConfig>) {
  model.value = { ...model.value, ...patch }
}

function updateCpu(value: string) {
  const parsed = Number(value)
  const normalized = Number.isFinite(parsed) ? Math.max(1, Math.trunc(parsed)) : 1
  const maximum = inventory.value ? cpuMaximum.value : normalized
  updateResources({ cpu_cores: Math.min(normalized, maximum) })
}

function updateMemory(value: string) {
  const parsed = Number(value)
  const normalized = Number.isFinite(parsed) ? Math.max(0, parsed) : 0
  const maximum = inventory.value && memoryMaximum.value > 0 ? memoryMaximum.value : normalized
  updateResources({ memory_limit_gb: Math.min(normalized, maximum) })
}

function setVisibleDevice(deviceId: string, visible: boolean) {
  const next = new Set(selectedIds.value)
  if (visible) next.add(deviceId)
  else next.delete(deviceId)
  const ids = allSelectableIds.value.filter((item) => next.has(item))
  if (ids.length === 0) {
    updateResources({ accelerator_mode: 'none', accelerator_device_ids: [] })
  } else if (ids.length === allSelectableIds.value.length) {
    updateResources({ accelerator_mode: 'all', accelerator_device_ids: [] })
  } else {
    updateResources({ accelerator_mode: 'selected', accelerator_device_ids: ids })
  }
}

function isVisible(device: AcceleratorDevice) {
  if (!device.visibility_supported) return true
  return selectedIds.value.has(device.id)
}

function showAllDevices() {
  updateResources({ accelerator_mode: 'all', accelerator_device_ids: [] })
}

function hideAllDevices() {
  updateResources({ accelerator_mode: 'none', accelerator_device_ids: [] })
}

function formatDeviceMemory(memoryMb: number) {
  if (!memoryMb) return ''
  return `${(memoryMb / 1024).toFixed(1)} GiB`
}
</script>

<template>
  <section class="resource-settings">
    <div class="resource-grid">
      <label class="resource-field">
        <span>CPU 核心总数</span>
        <input
          type="number"
          min="1"
          :max="cpuMaximum"
          :value="model.cpu_cores"
          :disabled="props.disabled"
          @input="updateCpu(($event.target as HTMLInputElement).value)"
        />
        <small v-if="inventory">可用 {{ cpuMaximum }} 个逻辑核心</small>
      </label>
      <label class="resource-field">
        <span>任务内存上限 (GiB)</span>
        <input
          type="number"
          min="0"
          step="0.5"
          :max="memoryMaximum || undefined"
          :value="model.memory_limit_gb"
          :disabled="props.disabled"
          @input="updateMemory(($event.target as HTMLInputElement).value)"
        />
        <small v-if="inventory">主机总内存 {{ inventory.memory.total_gb }} GiB，0 表示不限制</small>
      </label>
    </div>
    <p class="resource-note">
      {{ cpuLimitHint }} CPU 预算由该任务的全部并行搜索共享。{{ memoryLimitHint }}
    </p>

    <div class="device-head">
      <div>
        <h3>显卡与加速卡</h3>
        <span v-if="inventory" class="runtime-label">
          {{ inventory.platform?.system || 'Unknown OS' }} · {{ configuredRuntimeLabel }}
        </span>
      </div>
      <div class="device-actions">
        <button type="button" :disabled="props.disabled || loading" @click="showAllDevices">全选</button>
        <button type="button" :disabled="props.disabled || loading" @click="hideAllDevices">全部隐藏</button>
        <button type="button" :disabled="loading" @click="refresh">{{ loading ? '检测中...' : '刷新设备' }}</button>
      </div>
    </div>
    <p class="resource-note">
      {{ acceleratorLimitHint }}
    </p>

    <p v-if="error" class="device-error">{{ error }}</p>
    <div v-else-if="loading && !inventory" class="device-empty">正在检测本机设备...</div>
    <div v-else-if="!inventory?.devices.length" class="device-empty">未检测到显卡或加速卡</div>
    <div v-else class="device-list">
      <label
        v-for="device in inventory.devices"
        :key="device.id"
        class="device-row"
        :class="{ selected: isVisible(device), unavailable: !device.runtime_available }"
      >
        <input
          type="checkbox"
          :checked="isVisible(device)"
          :disabled="props.disabled || !device.visibility_supported"
          @change="setVisibleDevice(device.id, ($event.target as HTMLInputElement).checked)"
        />
        <span class="device-main">
          <strong>{{ device.name }}</strong>
          <span>{{ device.id }} · {{ device.vendor }} · {{ device.source }}</span>
        </span>
        <span v-if="device.memory_mb" class="device-memory">{{ formatDeviceMemory(device.memory_mb) }}</span>
        <span v-if="!device.visibility_supported" class="device-badge neutral">不可隔离</span>
        <span v-else-if="device.runtime_available" class="device-badge ready">运行时可用</span>
        <span v-else class="device-badge warning">任务运行环境不可用</span>
      </label>
    </div>
  </section>
</template>

<style scoped>
.resource-settings {
  display: grid;
  gap: 18px;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.resource-field {
  display: grid;
  gap: 6px;
  color: #26416b;
  font-size: 13px;
}

.resource-field input {
  min-width: 0;
  border: 1px solid #c4d4ef;
  border-radius: 6px;
  padding: 8px 10px;
  background: #fff;
  font-size: 14px;
}

.resource-field small,
.runtime-label {
  color: #63738c;
  font-size: 12px;
}

.resource-note {
  margin: -8px 0 0;
  color: #63738c;
  font-size: 12px;
  line-height: 1.6;
}

.device-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.device-head h3 {
  margin: 0 0 4px;
  color: #18365e;
  font-size: 15px;
}

.device-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.device-actions button {
  border: 1px solid #b8cdee;
  border-radius: 6px;
  padding: 7px 10px;
  background: #f4f7fc;
  color: #234a7c;
  cursor: pointer;
}

.device-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.device-list {
  display: grid;
  gap: 8px;
}

.device-row {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  border: 1px solid #d0d9e8;
  border-radius: 6px;
  padding: 9px 10px;
  background: #fff;
}

.device-row.selected {
  border-color: #4f7fb9;
  background: #f5f9ff;
}

.device-row.unavailable {
  border-left: 3px solid #c9822e;
}

.device-main {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.device-main strong,
.device-main span {
  overflow-wrap: anywhere;
}

.device-main strong {
  color: #172d4e;
  font-size: 13px;
}

.device-main span,
.device-memory {
  color: #697990;
  font-size: 12px;
}

.device-badge {
  border-radius: 4px;
  padding: 3px 6px;
  white-space: nowrap;
  font-size: 11px;
}

.device-badge.ready {
  background: #e4f5e9;
  color: #24643a;
}

.device-badge.warning {
  background: #fff0d8;
  color: #8b5416;
}

.device-badge.neutral {
  background: #edf0f5;
  color: #566273;
}

.device-empty,
.device-error {
  margin: 0;
  border: 1px dashed #bdc9da;
  border-radius: 6px;
  padding: 14px;
  color: #65758d;
  text-align: center;
}

.device-error {
  border-color: #e2a7a7;
  color: #9f2f2f;
  background: #fff7f7;
}

@media (max-width: 760px) {
  .resource-grid {
    grid-template-columns: 1fr;
  }

  .device-head {
    align-items: stretch;
    flex-direction: column;
  }

  .device-row {
    grid-template-columns: 20px minmax(0, 1fr);
  }

  .device-memory,
  .device-badge {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
