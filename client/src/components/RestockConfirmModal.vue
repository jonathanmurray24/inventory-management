<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="modal-overlay" @click="close">
        <div class="modal-container" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">{{ t('restocking.confirmTitle') }}</h3>
            <button class="close-button" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <p class="confirm-description">
              {{ t('restocking.confirmDescription', { warehouse: translatedWarehouse, days: leadTimeDays }) }}
            </p>

            <table class="lines-table">
              <thead>
                <tr>
                  <th>{{ t('restocking.table.sku') }}</th>
                  <th>{{ t('restocking.table.item') }}</th>
                  <th class="align-right">{{ t('restocking.table.quantity') }}</th>
                  <th class="align-right">{{ t('restocking.table.unitCost') }}</th>
                  <th class="align-right">{{ t('restocking.table.lineCost') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="line in lines" :key="line.sku">
                  <td class="sku-cell">{{ line.sku }}</td>
                  <td>{{ translateProductName(line.name) }}</td>
                  <td class="align-right">{{ line.recommended_qty }}</td>
                  <td class="align-right">{{ formatCurrencyWithDecimals(line.unit_cost, currentCurrency, 2) }}</td>
                  <td class="align-right">{{ formatCurrencyWithDecimals(line.recommended_qty * line.unit_cost, currentCurrency, 2) }}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="total-row">
                  <td colspan="4">{{ t('restocking.table.total') }}</td>
                  <td class="align-right">{{ formatCurrencyWithDecimals(totalCost, currentCurrency, 2) }}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <div class="modal-footer">
            <button class="btn-secondary" @click="close">{{ t('common.cancel') }}</button>
            <button class="btn-primary" :disabled="submitting || !lines.length" @click="emit('confirm')">
              {{ submitting ? t('restocking.submitting') : t('restocking.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const { t, currentCurrency, translateProductName, translateWarehouse } = useI18n()

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  lines: {
    type: Array,
    default: () => []
  },
  warehouse: {
    type: String,
    default: ''
  },
  totalCost: {
    type: Number,
    default: 0
  },
  leadTimeDays: {
    type: Number,
    default: 0
  },
  submitting: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'confirm'])

const translatedWarehouse = computed(() => translateWarehouse(props.warehouse))

const close = () => {
  // Ignore dismiss attempts while a submit request is in flight, so the
  // in-progress order can't be abandoned or double-submitted mid-request.
  if (props.submitting) return
  emit('close')
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 90%;
  max-width: 700px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 2rem;
  border-bottom: 2px solid #e2e8f0;
}

.modal-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  padding: 2rem;
  overflow-y: auto;
  flex: 1;
}

.confirm-description {
  font-size: 0.938rem;
  color: #475569;
  line-height: 1.5;
  margin: 0 0 1.5rem 0;
}

.lines-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.lines-table th {
  text-align: left;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  padding: 0.625rem 0.75rem;
  border-bottom: 2px solid #e2e8f0;
}

.lines-table td {
  padding: 0.625rem 0.75rem;
  border-bottom: 1px solid #e2e8f0;
  color: #0f172a;
}

.lines-table th.align-right,
.lines-table td.align-right {
  text-align: right;
}

.sku-cell {
  font-family: 'Monaco', 'Courier New', monospace;
  font-size: 0.813rem;
  color: #64748b;
}

.lines-table tfoot td {
  border-bottom: none;
  border-top: 2px solid #e2e8f0;
  font-weight: 700;
  color: #0f172a;
  padding-top: 0.75rem;
}

.total-row td {
  text-align: right;
}

.total-row td:first-child {
  text-align: left;
}

.modal-footer {
  padding: 1.5rem 2rem;
  border-top: 2px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
}

.btn-secondary {
  padding: 0.75rem 1.5rem;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-primary {
  padding: 0.75rem 1.5rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal transitions */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.9);
}
</style>
