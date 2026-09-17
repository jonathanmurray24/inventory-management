<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="initialLoading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ t('restocking.loadError') }}</div>
    <div v-else>
      <div class="card controls-card">
        <div class="controls-grid">
          <div class="control-group warehouse-control">
            <label for="restock-warehouse">{{ t('restocking.warehouse') }}</label>
            <!--
              No "all" option here: a restock order needs exactly one destination
              warehouse, unlike the global filters which can span every warehouse.
            -->
            <select id="restock-warehouse" v-model="warehouse" class="filter-select">
              <option value="San Francisco">{{ t('warehouses.sanFrancisco') }}</option>
              <option value="London">{{ t('warehouses.london') }}</option>
              <option value="Tokyo">{{ t('warehouses.tokyo') }}</option>
            </select>
          </div>

          <div class="control-group budget-control">
            <label for="restock-budget">
              {{ t('restocking.budget') }}: <strong>{{ formatCurrency(budget, currentCurrency) }}</strong>
            </label>
            <input
              id="restock-budget"
              type="range"
              :min="0"
              :max="sliderMax"
              :step="250"
              v-model.number="budget"
            />
            <div class="slider-range-labels">
              <span>{{ formatCurrency(0, currentCurrency) }}</span>
              <span>{{ formatCurrency(sliderMax, currentCurrency) }}</span>
            </div>
          </div>
        </div>

        <div class="lead-time-note">
          {{ t('restocking.leadTime') }}: {{ t('common.daysCount', { days: recommendations.lead_time_days || 0 }) }}
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatCurrency(budget, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.allocated') }}</div>
          <div class="stat-value">{{ formatCurrency(recommendations.total_cost, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatCurrency(recommendations.remaining_budget, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsRecommended') }}</div>
          <div class="stat-value">{{ recommendations.lines.length }}</div>
          <div class="stat-sub">{{ t('restocking.itemsWithShortfall') }}: {{ recommendations.items_with_shortfall }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ recommendations.lines.length }})</h3>
        </div>

        <p v-if="recommendations.items_with_shortfall === 0" class="empty-state">
          {{ t('restocking.noShortfall') }}
        </p>
        <p v-else-if="!recommendations.lines.length" class="empty-state">
          {{ t('restocking.noRecommendations') }}
        </p>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.onHand') }}</th>
                <th>{{ t('restocking.table.forecast') }}</th>
                <th>{{ t('restocking.table.shortfall') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.recommendedQty') }}</th>
                <th>{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="line in recommendations.lines"
                :key="line.sku"
                :class="{ 'partial-row': line.partial }"
              >
                <td><strong>{{ line.sku }}</strong></td>
                <td>{{ translateProductName(line.name) }}</td>
                <td>{{ line.category }}</td>
                <td>{{ line.quantity_on_hand }}</td>
                <td>{{ line.forecasted_demand }}</td>
                <td>{{ line.shortfall }}</td>
                <td>{{ formatCurrencyWithDecimals(line.unit_cost, currentCurrency, 2) }}</td>
                <td>
                  {{ line.recommended_qty }}
                  <span v-if="line.partial" class="badge warning">{{ t('restocking.partialFill') }}</span>
                </td>
                <td>{{ formatCurrencyWithDecimals(line.line_cost, currentCurrency, 2) }}</td>
                <td>
                  <span :class="['badge', line.trend]">{{ t(`trends.${line.trend}`) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="action-row">
        <button
          class="btn-primary"
          :disabled="!recommendations.lines.length || submitting"
          @click="showConfirm = true"
        >
          {{ t('restocking.placeOrder') }}
        </button>
      </div>

      <div v-if="lastOrder" class="success-banner">
        {{ t('restocking.orderSubmitted', {
          orderNumber: lastOrder.order_number,
          date: formatDate(lastOrder.expected_delivery),
          days: lastOrder.lead_time_days
        }) }}
        <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <RestockConfirmModal
        :is-open="showConfirm"
        :lines="recommendations.lines"
        :warehouse="warehouse"
        :total-cost="recommendations.total_cost"
        :lead-time-days="recommendations.lead_time_days || 0"
        :submitting="submitting"
        @close="showConfirm = false"
        @confirm="submitOrder"
      />
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { api } from '../api'
import { useFilters } from '../composables/useFilters'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'
import RestockConfirmModal from '../components/RestockConfirmModal.vue'

export default {
  name: 'Restocking',
  components: {
    RestockConfirmModal
  },
  setup() {
    const { t, currentCurrency, currentLocale, translateProductName } = useI18n()
    const { selectedLocation } = useFilters()

    const warehouse = ref(selectedLocation.value !== 'all' ? selectedLocation.value : 'San Francisco')
    const budget = ref(0)
    const sliderMax = ref(1000)

    const recommendations = ref({
      lines: [],
      total_cost: 0,
      remaining_budget: 0,
      total_shortfall_cost: 0,
      items_with_shortfall: 0,
      lead_time_days: null
    })

    const initialLoading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const submitError = ref(null)
    const showConfirm = ref(false)
    const lastOrder = ref(null)

    // Sequence counter so out-of-order responses from rapid slider drags
    // or warehouse switches never clobber a newer result with a stale one.
    const requestSeq = ref(0)
    let debounceTimer = null

    const roundToStep = (value, step) => Math.round(value / step) * step

    const fetchRecommendations = async (budgetValue) => {
      requestSeq.value++
      const seq = requestSeq.value
      try {
        const data = await api.getRestockRecommendations({ budget: budgetValue, warehouse: warehouse.value })
        // The slider produces bursts of requests; ignore any response that
        // isn't the most recent one we asked for.
        if (seq !== requestSeq.value) return
        recommendations.value = data
        error.value = null
      } catch (err) {
        if (seq === requestSeq.value) {
          error.value = t('restocking.loadError')
        }
      } finally {
        if (seq === requestSeq.value) {
          initialLoading.value = false
        }
      }
    }

    // Runs on mount and whenever the warehouse changes. First probes with
    // budget=0 to learn the full shortfall cost so the slider's max always
    // has one step of headroom above "everything covered", then fetches the
    // real recommendations for the chosen (or re-centered) budget. This is
    // intentionally two requests.
    const bootstrapBudget = async () => {
      requestSeq.value++
      const seq = requestSeq.value
      try {
        const probe = await api.getRestockRecommendations({ budget: 0, warehouse: warehouse.value })
        if (seq !== requestSeq.value) return

        const shortfallCost = probe.total_shortfall_cost || 0
        sliderMax.value = Math.max(1000, Math.ceil(shortfallCost / 1000) * 1000 + 1000)

        if (budget.value === 0 || budget.value > sliderMax.value) {
          budget.value = roundToStep(sliderMax.value / 2, 250)
        }

        await fetchRecommendations(budget.value)
      } catch (err) {
        if (seq === requestSeq.value) {
          error.value = t('restocking.loadError')
          initialLoading.value = false
        }
      }
    }

    // The global location filter can drive this page's warehouse, but the
    // page is also allowed to pick a different one independently.
    watch(selectedLocation, (v) => {
      if (v !== 'all') warehouse.value = v
    })

    watch(warehouse, () => {
      bootstrapBudget()
    })

    watch(budget, () => {
      if (debounceTimer) clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => {
        fetchRecommendations(budget.value)
      }, 250)
    })

    const submitOrder = async () => {
      submitting.value = true
      submitError.value = null
      try {
        const payload = {
          warehouse: warehouse.value,
          items: recommendations.value.lines.map(line => ({
            sku: line.sku,
            quantity: line.recommended_qty
          }))
        }
        const order = await api.createRestockOrder(payload)
        lastOrder.value = order
        showConfirm.value = false

        // Placing an order does not reduce the shortfall because the stock
        // hasn't arrived yet, so the recommendation table is unchanged after
        // this refetch.
        await fetchRecommendations(budget.value)
      } catch (err) {
        submitError.value = t('restocking.submitError')
      } finally {
        submitting.value = false
      }
    }

    const formatDate = (iso) => {
      const date = new Date(iso)
      if (isNaN(date.getTime())) return ''
      return date.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    onMounted(() => {
      bootstrapBudget()
    })

    onUnmounted(() => {
      if (debounceTimer) clearTimeout(debounceTimer)
    })

    return {
      t,
      currentCurrency,
      translateProductName,
      warehouse,
      budget,
      sliderMax,
      recommendations,
      initialLoading,
      error,
      submitting,
      submitError,
      showConfirm,
      lastOrder,
      formatCurrency,
      formatCurrencyWithDecimals,
      formatDate,
      submitOrder
    }
  }
}
</script>

<style scoped>
.controls-card {
  margin-bottom: 1.5rem;
}

.controls-grid {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 2rem;
  align-items: start;
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.control-group label {
  font-size: 0.813rem;
  font-weight: 600;
  color: #64748b;
}

.filter-select {
  padding: 0.4rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.813rem;
  color: #0f172a;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 500;
}

.filter-select:hover {
  border-color: #94a3b8;
}

.filter-select:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.budget-control input[type='range'] {
  accent-color: #3b82f6;
  width: 100%;
}

.slider-range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #94a3b8;
}

.lead-time-note {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
  font-size: 0.875rem;
  color: #64748b;
}

.stat-sub {
  margin-top: 0.375rem;
  font-size: 0.75rem;
  color: #94a3b8;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.partial-row {
  background: rgba(245, 158, 11, 0.06);
}

.partial-row td:first-child {
  box-shadow: inset 3px 0 0 #f59e0b;
}

.action-row {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1.25rem;
}

.btn-primary {
  background: #0f172a;
  color: white;
  padding: 0.65rem 1.25rem;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.success-banner {
  background: #dcfce7;
  border: 1px solid #86efac;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.938rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.success-banner a {
  color: #166534;
  font-weight: 600;
  text-decoration: underline;
}
</style>
