<template>
  <GatewayGate>
    <ElContainer direction="vertical" class="gateway-node-page" data-testid="gateway-node-detail">
      <ElHeader class="gateway-node-header">
        <div class="gateway-node-title">
          <RouterLink class="gateway-node-back" to="/gateway/nodes">
            <ArrowLeft :size="14" />节点列表
          </RouterLink>
          <div class="gateway-node-title__row">
            <h2>{{ node?.name ?? '节点详情' }}</h2>
            <ElText size="small" type="info" class="gateway-node-mono">{{ node?.id ?? '—' }}</ElText>
          </div>
          <ElText size="small" type="info">
            {{ node?.base_url ?? '正在加载节点…' }} · 配置态、健康态与调度态相互独立
          </ElText>
        </div>
        <div v-if="node" class="gateway-node-tags" aria-label="节点状态">
          <ElTag size="small" :type="tagType(healthTone(node.health_state))">{{ healthStateLabel(node.health_state) }}</ElTag>
          <ElTag size="small" :type="tagType(schedulingTone(node.scheduling_state))">{{ schedulingStateLabel(node.scheduling_state) }}</ElTag>
          <ElTag size="small" :type="node.config_state === 'ENABLED' ? 'success' : 'info'">{{ configStateLabel(node.config_state) }}</ElTag>
          <ElTag size="small" effect="plain">{{ poolName(node.pool_id) }}</ElTag>
        </div>
        <div class="gateway-node-actions">
          <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-node-refresh" @click="load">刷新</ElButton>
          <ElButton v-if="node" :loading="working" :icon="Activity" data-testid="gateway-node-probe" @click="probe">探测</ElButton>
          <ElButton
            v-if="node && node.scheduling_state === 'ACTIVE'"
            type="warning"
            :loading="working"
            :icon="Pause"
            data-testid="gateway-node-drain"
            @click="drain"
          >安全下线</ElButton>
          <ElButton
            v-else-if="node"
            type="success"
            :loading="working"
            :icon="Play"
            data-testid="gateway-node-restore"
            @click="restore"
          >恢复调度</ElButton>
          <ElButton
            v-if="node && canManage"
            :loading="working"
            :icon="node.config_state === 'ENABLED' ? PowerOff : Power"
            data-testid="gateway-node-toggle"
            @click="toggleConfig"
          >{{ node.config_state === 'ENABLED' ? '禁用' : '启用' }}</ElButton>
          <ElButton v-if="node && canManage" type="primary" :icon="Pencil" data-testid="gateway-node-edit" @click="openEditor">编辑</ElButton>
        </div>
      </ElHeader>

      <ElMain class="gateway-node-body">
        <ElAlert
          v-if="error"
          type="error"
          show-icon
          :closable="false"
          :title="error"
          data-testid="gateway-node-error"
        >
          <ElButton size="small" type="primary" data-testid="gateway-node-retry" @click="load">重试</ElButton>
        </ElAlert>

        <ElCard
          v-if="!node"
          v-loading="loading"
          class="gateway-node-state"
          element-loading-text="正在加载节点"
          data-testid="gateway-node-state"
        >
          <ElEmpty v-if="!loading" :image-size="72" description="未找到该节点，或它已被删除。">
            <ElButton type="primary" :icon="ArrowLeft" data-testid="gateway-node-back-empty" @click="backToList">返回节点列表</ElButton>
          </ElEmpty>
        </ElCard>

        <ElContainer v-else class="gateway-node-layout">
          <ElAside class="gateway-node-nav">
            <ElMenu
              mode="vertical"
              :default-active="activeSection"
              aria-label="节点详情导航"
              data-testid="gateway-node-nav"
              @select="jumpTo"
            >
              <ElMenuItem
                v-for="item in sections"
                :key="item.id"
                :index="item.id"
                :data-testid="`gateway-node-nav-${item.id}`"
              >
                <component :is="item.icon" :size="15" />
                <span>{{ item.label }}</span>
              </ElMenuItem>
            </ElMenu>
          </ElAside>

          <ElMain ref="contentRef" class="gateway-node-content" data-testid="gateway-node-content" @scroll="syncActiveSection">
            <!-- 概览 -->
            <section id="overview" class="gateway-node-section" data-testid="gateway-node-section-overview">
              <header class="gateway-node-section__bar">
                <h3>概览</h3>
                <ElText size="small" type="info">Token 与性能区块共用同一统计窗口</ElText>
                <ElRadioGroup v-model="statsWindow" class="gateway-node-window" aria-label="统计窗口" data-testid="gateway-node-window">
                  <ElRadioButton v-for="item in windows" :key="item.id" :value="item.id">{{ item.label }}</ElRadioButton>
                </ElRadioGroup>
              </header>
              <div class="gateway-node-metrics" aria-label="节点指标">
                <ElCard v-for="metric in metricCards" :key="metric.id" shadow="never" :data-testid="`gateway-node-metric-${metric.id}`">
                  <ElStatistic :title="metric.label" :value="metric.value as number" />
                  <p class="gateway-node-metric-hint">{{ metric.hint }}</p>
                </ElCard>
              </div>
              <div class="gateway-node-grid">
                <ElCard shadow="never" data-testid="gateway-node-info">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div><h4>节点信息</h4><ElText size="small" type="info">凭据只写不回显</ElText></div>
                    </div>
                  </template>
                  <ElDescriptions :column="2" size="small">
                    <ElDescriptionsItem label="下游地址">{{ node.base_url }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="资源池">{{ poolName(node.pool_id) }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="认证方式">{{ authTypeLabel(node.auth_type) }} · {{ node.auth_header }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="凭据">{{ node.has_api_key ? '已配置（不回显）' : '未配置' }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="健康路径">{{ node.health_path || '继承默认' }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="支持模型">{{ node.models.length ? node.models.join('、') : '未配置' }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="最近探测">{{ formatDateTime(node.last_checked_at) }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="探测间隔">{{ node.probe_interval_seconds ?? '继承默认' }} 秒</ElDescriptionsItem>
                  </ElDescriptions>
                </ElCard>

                <ElCard shadow="never" data-testid="gateway-node-probe-latest">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div>
                        <h4>最近探测结果</h4>
                        <ElText size="small" type="info">认证由真实模型调用状态推断，未新增独立认证探测</ElText>
                      </div>
                      <ElTag size="small" :type="tagType(authenticationTone(probeAuthentication))">{{ authenticationLabel(probeAuthentication) }}</ElTag>
                    </div>
                  </template>
                  <ElTable :data="healthChecks.slice(0, 8)" size="small" row-key="id" data-testid="gateway-node-probe-table">
                    <ElTableColumn label="类型" min-width="110">
                      <template #default="{ row }">{{ probeTypeLabel(row.probe_type) }}</template>
                    </ElTableColumn>
                    <ElTableColumn label="结果" width="86">
                      <template #default="{ row }">
                        <ElTag size="small" :type="row.success ? 'success' : 'danger'">{{ row.success ? '通过' : '失败' }}</ElTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="延迟" width="92">
                      <template #default="{ row }"><span class="gateway-node-num">{{ row.latency_ms }} ms</span></template>
                    </ElTableColumn>
                    <ElTableColumn label="时间" width="118">
                      <template #default="{ row }"><span class="gateway-node-num">{{ formatRelativeTime(row.created_at) }}</span></template>
                    </ElTableColumn>
                    <template #empty>
                      <ElEmpty v-if="!loading" :image-size="56" description="暂无探测记录。" />
                    </template>
                  </ElTable>
                </ElCard>
              </div>
            </section>

            <!-- Token -->
            <section id="tokens" class="gateway-node-section" data-testid="gateway-node-section-tokens">
              <header class="gateway-node-section__bar">
                <h3>Token</h3>
                <ElText size="small" type="info">{{ windowLabel }}窗口的输入 / 输出 / 总量，未知用量不估算为零</ElText>
              </header>
              <div class="gateway-node-metrics gateway-node-metrics--three">
                <ElCard v-for="metric in tokenCards" :key="metric.id" shadow="never" :data-testid="`gateway-node-token-${metric.id}`">
                  <ElStatistic :title="metric.label" :value="metric.value as number" />
                  <p class="gateway-node-metric-hint">{{ metric.hint }}</p>
                </ElCard>
              </div>
              <ElCard shadow="never" data-testid="gateway-node-token-trend">
                <template #header>
                  <div class="gateway-node-card-head">
                    <div><h4>Token 趋势</h4><ElText size="small" type="info">{{ windowLabel }}</ElText></div>
                  </div>
                </template>
                <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="tokens" tall />
                <ElEmpty v-else :image-size="52" :description="loading ? '加载中…' : '暂无数据'" />
              </ElCard>
            </section>

            <!-- 性能 -->
            <section id="performance" class="gateway-node-section" data-testid="gateway-node-section-performance">
              <header class="gateway-node-section__bar">
                <h3>性能</h3>
                <ElText size="small" type="info">{{ windowLabel }}窗口的平均 / p50 / p95</ElText>
              </header>
              <div class="gateway-node-grid">
                <ElCard shadow="never" data-testid="gateway-node-latency">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div><h4>性能指标</h4><ElText size="small" type="info">平均 / p50 / p95</ElText></div>
                    </div>
                  </template>
                  <ElDescriptions :column="1" size="small">
                    <ElDescriptionsItem v-for="row in latencyRows" :key="row.label" :label="row.label">{{ row.value }}</ElDescriptionsItem>
                  </ElDescriptions>
                  <div class="gateway-node-peak">
                    <span>峰值并发 <b>{{ stats?.peak_concurrency ?? '—' }}</b></span>
                    <span>QPS <b>{{ stats ? stats.qps.toFixed(2) : '—' }}</b></span>
                    <span>失败 <b class="gateway-node-peak--bad">{{ stats?.errors ?? '—' }}</b></span>
                  </div>
                </ElCard>
                <ElCard shadow="never" data-testid="gateway-node-request-trend">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div><h4>请求量趋势</h4><ElText size="small" type="info">{{ windowLabel }}</ElText></div>
                    </div>
                  </template>
                  <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="requests" />
                  <ElEmpty v-else :image-size="52" :description="loading ? '加载中…' : '暂无数据'" />
                </ElCard>
              </div>
            </section>

            <!-- 限制 -->
            <section id="limits" class="gateway-node-section" data-testid="gateway-node-section-limits">
              <header class="gateway-node-section__bar">
                <h3>限制</h3>
                <ElText size="small" type="info">并发、权重与额度由节点配置决定，实际用量按自然窗口统计</ElText>
              </header>
              <div class="gateway-node-grid">
                <ElCard shadow="never" data-testid="gateway-node-scheduling-limits">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div><h4>并发与权重</h4><ElText size="small" type="info">0 或空表示不限</ElText></div>
                    </div>
                  </template>
                  <ElDescriptions :column="1" size="small">
                    <ElDescriptionsItem label="最大并发">{{ node.max_concurrency || '不限' }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="有效权重">{{ node.weight }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="调度状态">
                      <ElTag size="small" :type="tagType(schedulingTone(node.scheduling_state))">{{ schedulingStateLabel(node.scheduling_state) }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="配置状态">
                      <ElTag size="small" :type="node.config_state === 'ENABLED' ? 'success' : 'info'">{{ configStateLabel(node.config_state) }}</ElTag>
                    </ElDescriptionsItem>
                  </ElDescriptions>
                </ElCard>
                <ElCard shadow="never" data-testid="gateway-node-quota">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div><h4>Token 额度</h4><ElText size="small" type="info">已完成请求的实际 usage 计入</ElText></div>
                    </div>
                  </template>
                  <ElDescriptions :column="1" size="small">
                    <ElDescriptionsItem label="额度策略">{{ quotaPolicyLabel(node.quota_policy) }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="每小时限额">
                      {{ node.hourly_token_limit ?? '不限' }} · 本小时已用 {{ hourTokens ? formatTokens(hourTokens.total_tokens) : '—' }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="每日限额">
                      {{ node.daily_token_limit ?? '不限' }} · 今日已用 {{ dayTokens ? formatTokens(dayTokens.total_tokens) : '—' }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="未知用量（今日）">{{ dayTokens?.unknown_usage_requests ?? '—' }}</ElDescriptionsItem>
                  </ElDescriptions>
                  <p class="gateway-node-note"><Timer :size="13" />额度原子计入，因并发可能产生有限超额。</p>
                </ElCard>
              </div>
            </section>

            <!-- 健康 -->
            <section id="health" class="gateway-node-section" data-testid="gateway-node-section-health">
              <header class="gateway-node-section__bar">
                <h3>健康</h3>
                <ElText size="small" type="info">健康态由探测推导，调度态由管理员操作决定，两者互不覆盖</ElText>
              </header>
              <div class="gateway-node-grid">
                <ElCard shadow="never" data-testid="gateway-node-health-state">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div><h4>健康状态</h4><ElText size="small" type="info">服务端观测快照</ElText></div>
                    </div>
                  </template>
                  <ElDescriptions :column="1" size="small">
                    <ElDescriptionsItem label="健康态">
                      <ElTag size="small" :type="tagType(healthTone(node.health_state))">{{ healthStateLabel(node.health_state) }}</ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="连续成功">{{ node.success_streak }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="连续失败">{{ node.failure_streak }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="最近探测">{{ formatDateTime(node.last_checked_at) }}</ElDescriptionsItem>
                  </ElDescriptions>
                  <pre class="gateway-node-snapshot" data-testid="gateway-node-health-detail">{{ JSON.stringify(node.health_detail, null, 2) }}</pre>
                </ElCard>
                <ElCard shadow="never" data-testid="gateway-node-health-history">
                  <template #header>
                    <div class="gateway-node-card-head">
                      <div><h4>探测历史</h4><ElText size="small" type="info">最近 {{ healthChecks.length }} 条</ElText></div>
                    </div>
                  </template>
                  <ElTable :data="healthChecks" size="small" row-key="id" max-height="360" data-testid="gateway-node-health-table">
                    <ElTableColumn label="类型" min-width="100">
                      <template #default="{ row }">{{ probeTypeLabel(row.probe_type) }}</template>
                    </ElTableColumn>
                    <ElTableColumn label="结果" width="80">
                      <template #default="{ row }">
                        <ElTag size="small" :type="row.success ? 'success' : 'danger'">{{ row.success ? '通过' : '失败' }}</ElTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="延迟" width="88">
                      <template #default="{ row }"><span class="gateway-node-num">{{ row.latency_ms }} ms</span></template>
                    </ElTableColumn>
                    <ElTableColumn label="状态码" width="80">
                      <template #default="{ row }"><span class="gateway-node-num">{{ row.status_code ?? '—' }}</span></template>
                    </ElTableColumn>
                    <ElTableColumn label="错误" min-width="150" show-overflow-tooltip>
                      <template #default="{ row }">
                        <span v-if="row.error" class="gateway-node-err">{{ row.error }}</span>
                        <span v-else>—</span>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="时间" width="120">
                      <template #default="{ row }"><span class="gateway-node-num">{{ formatDateTime(row.created_at) }}</span></template>
                    </ElTableColumn>
                    <template #empty>
                      <ElEmpty v-if="!loading" :image-size="56" description="暂无探测记录。" />
                    </template>
                  </ElTable>
                </ElCard>
              </div>
            </section>

            <!-- 日志 -->
            <section id="logs" class="gateway-node-section" data-testid="gateway-node-section-logs">
              <header class="gateway-node-section__bar">
                <h3>日志</h3>
                <ElText size="small" type="info">只记录元数据与测量值，不保存 Prompt、Authorization 或响应体</ElText>
                <ElButton
                  size="small"
                  :loading="logsLoading"
                  :icon="RefreshCw"
                  data-testid="gateway-node-logs-refresh"
                  @click="loadRequests()"
                >刷新日志</ElButton>
              </header>
              <ElCard shadow="never" data-testid="gateway-node-logs">
                <template #header>
                  <div class="gateway-node-card-head">
                    <div><h4>调用日志</h4><ElText size="small" type="info">该节点的调用元数据与测量值</ElText></div>
                  </div>
                </template>
                <ElTable
                  v-loading="logsLoading"
                  :data="requests.items"
                  size="small"
                  row-key="id"
                  element-loading-text="正在加载调用日志"
                  data-testid="gateway-node-logs-table"
                >
                  <ElTableColumn label="时间" width="116">
                    <template #default="{ row }"><span class="gateway-node-num">{{ formatDateTime(row.started_at) }}</span></template>
                  </ElTableColumn>
                  <ElTableColumn label="Key / 模型" min-width="160">
                    <template #default="{ row }">
                      <div class="gateway-node-cell">
                        <strong>{{ row.key_id ? row.key_id.slice(0, 12) : '—' }}</strong>
                        <span>{{ row.model ?? '—' }}</span>
                      </div>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="状态" min-width="150">
                    <template #default="{ row }">
                      <ElTag v-if="row.error_code" size="small" type="danger" :title="row.error_code">{{ row.error_code }}</ElTag>
                      <ElTag v-else size="small" :type="row.status_code && row.status_code < 400 ? 'success' : 'warning'">{{ row.status_code ?? '—' }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="流式" width="88">
                    <template #default="{ row }">{{ row.streaming ? 'SSE' : '普通' }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="重试" width="68">
                    <template #default="{ row }"><span class="gateway-node-num">{{ row.retry_count }}</span></template>
                  </ElTableColumn>
                  <ElTableColumn label="Token（入 / 出 / 总）" width="150">
                    <template #default="{ row }"><span class="gateway-node-num">{{ tokenText(row as GatewayRequestLog) }}</span></template>
                  </ElTableColumn>
                  <ElTableColumn label="TTFT" width="96">
                    <template #default="{ row }"><span class="gateway-node-num">{{ latencyText(row.ttft_ms) }}</span></template>
                  </ElTableColumn>
                  <ElTableColumn label="总时长" width="96">
                    <template #default="{ row }"><span class="gateway-node-num">{{ latencyText(row.duration_ms) }}</span></template>
                  </ElTableColumn>
                  <template #empty>
                    <ElEmpty v-if="!logsLoading" :image-size="64" description="暂无调用记录。" />
                  </template>
                </ElTable>
                <footer class="gateway-node-footer">
                  <ElText size="small" type="info" data-testid="gateway-node-logs-total">共 {{ requests.total }} 条 · 第 {{ requests.page }} 页</ElText>
                  <ElPagination
                    :current-page="requests.page"
                    :page-size="requests.page_size"
                    :total="requests.total"
                    layout="prev, pager, next"
                    :disabled="logsLoading"
                    aria-label="节点调用日志分页"
                    data-testid="gateway-node-logs-pagination"
                    @current-change="loadRequests"
                  />
                </footer>
              </ElCard>
            </section>

            <!-- 配置 -->
            <section id="config" class="gateway-node-section" data-testid="gateway-node-section-config">
              <header class="gateway-node-section__bar">
                <h3>配置</h3>
                <ElText size="small" type="info">配置态由管理员维护，健康态与运行态不由配置覆盖</ElText>
              </header>
              <ElCard shadow="never" data-testid="gateway-node-config">
                <template #header>
                  <div class="gateway-node-card-head">
                    <div><h4>节点配置</h4><ElText size="small" type="info">凭据加密入库，任何视图都不回显明文</ElText></div>
                    <ElButton
                      v-if="canManage"
                      type="primary"
                      plain
                      size="small"
                      :icon="Pencil"
                      data-testid="gateway-node-config-edit"
                      @click="openEditor"
                    >编辑配置</ElButton>
                  </div>
                </template>
                <ElDescriptions :column="2" size="small">
                  <ElDescriptionsItem label="名称">{{ node.name }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="资源池">{{ poolName(node.pool_id) }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="Base URL">{{ node.base_url }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="认证">{{ authTypeLabel(node.auth_type) }} · {{ node.auth_header }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="连接 / 请求超时">
                    {{ node.connect_timeout_seconds ?? '默认' }} / {{ node.request_timeout_seconds ?? '默认' }} 秒
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="健康路径">{{ node.health_path || '继承默认' }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="探测间隔">{{ node.probe_interval_seconds ?? '继承默认' }} 秒</ElDescriptionsItem>
                  <ElDescriptionsItem label="支持模型">{{ node.models.length ? node.models.join('、') : '未配置' }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="权重 / 并发">{{ node.weight }} / {{ node.max_concurrency || '不限' }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="额度">
                    {{ node.hourly_token_limit ?? '不限' }} / {{ node.daily_token_limit ?? '不限' }}（{{ quotaPolicyLabel(node.quota_policy) }}）
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="排序">{{ node.sort_order }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="创建 / 更新">
                    {{ formatDateTime(node.created_at) }} / {{ formatDateTime(node.updated_at) }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
            </section>
          </ElMain>
        </ElContainer>
      </ElMain>
    </ElContainer>

    <GatewayNodeDrawer :open="editorOpen" :node="node" :pools="pools" @close="editorOpen = false" @saved="load" />
  </GatewayGate>
</template>

<script setup lang="ts">
import {
  Activity,
  ArrowLeft,
  Coins,
  Gauge,
  HeartPulse,
  Pause,
  Pencil,
  Play,
  Power,
  PowerOff,
  RefreshCw,
  ScrollText,
  SlidersHorizontal,
  Timer,
} from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElAside,
  ElButton,
  ElCard,
  ElContainer,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElHeader,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElStatistic,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
  vLoading,
} from 'element-plus'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayHealthCheck,
  type GatewayNode,
  type GatewayPool,
  type GatewayProbeType,
  type GatewayRequestLog,
  type GatewayRequestPage,
  type GatewayScopeStats,
  type GatewayStatsWindow,
} from '@/api/gateway'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { formatTokens } from '@/utils/format'
import {
  authTypeLabel,
  authenticationLabel,
  authenticationResult,
  authenticationTone,
  configStateLabel,
  errorMessage,
  formatDateTime,
  formatPercent,
  formatRelativeTime,
  healthStateLabel,
  healthTone,
  probeTypeLabel,
  quotaPolicyLabel,
  schedulingStateLabel,
  schedulingTone,
  type GatewayTone,
} from '@/utils/gateway'
import GatewayGate from '@/views/gateway/GatewayGate.vue'
import GatewayNodeDrawer from '@/views/gateway/GatewayNodeDrawer.vue'
import GatewayTrendChart from '@/views/gateway/GatewayTrendChart.vue'

const route = useRoute()
const router = useRouter()
const { hasRole, disconnect } = useGatewayAuth()
const canManage = computed(() => hasRole('node'))
const nodeId = computed(() => String(route.params.id ?? ''))

// 节点详情不套在网关一级菜单里（见 router 的 /gateway/nodes/:id），
// 因此二级导航用本页左侧竖向 ElMenu + 区块锚点：URL 保持不变，刷新后仍是同一页，
// 也不会在一级菜单旁再挤出一条窄栏。
const sections = [
  { id: 'overview', label: '概览', icon: Activity },
  { id: 'tokens', label: 'Token', icon: Coins },
  { id: 'performance', label: '性能', icon: Gauge },
  { id: 'limits', label: '限制', icon: Timer },
  { id: 'health', label: '健康', icon: HeartPulse },
  { id: 'logs', label: '日志', icon: ScrollText },
  { id: 'config', label: '配置', icon: SlidersHorizontal },
]
const activeSection = ref('overview')
// 内容列是页内唯一滚动容器（见 .gateway-node-content）：区块顶部进入上沿这条
// 引导线就算当前区块，留出余量以免锚点落位与亚像素布局让选中态停在上一块。
const sectionOffset = 40

const windows: Array<{ id: GatewayStatsWindow; label: string }> = [
  { id: 'hour', label: '本小时' },
  { id: 'today', label: '今日' },
  { id: '7d', label: '近 7 天' },
  { id: '30d', label: '近 30 天' },
]
const statsWindow = ref<GatewayStatsWindow>('today')
const contentRef = ref<ComponentPublicInstance>()
const node = ref<GatewayNode | null>(null)
const pools = ref<GatewayPool[]>([])
const healthChecks = ref<GatewayHealthCheck[]>([])
const stats = ref<GatewayScopeStats | null>(null)
const hourTokens = ref<GatewayScopeStats | null>(null)
const dayTokens = ref<GatewayScopeStats | null>(null)
const requests = ref<GatewayRequestPage>({ items: [], total: 0, page: 1, page_size: 50 })
const loading = ref(false)
const logsLoading = ref(false)
const working = ref(false)
const error = ref('')
const editorOpen = ref(false)
const allProbes: GatewayProbeType[] = ['NETWORK', 'SERVICE', 'MODEL', 'STREAM']

const windowLabel = computed(() => windows.find((item) => item.id === statsWindow.value)?.label ?? '')
const probeAuthentication = computed(() => authenticationResult(healthChecks.value))

const metricCards = computed<Array<{ id: string; label: string; value: number | string; hint: string }>>(() => {
  const current = stats.value
  return [
    { id: 'requests', label: '窗口请求', value: current?.requests ?? '—', hint: '窗口内完成的调用总量' },
    { id: 'success-rate', label: '成功率', value: formatPercent(current?.success_rate), hint: '2xx/3xx 且未被中断' },
    { id: 'active', label: '当前并发', value: current?.active ?? '—', hint: '运行态租约' },
    { id: 'qps', label: 'QPS', value: current ? current.qps.toFixed(2) : '—', hint: '窗口平均每秒请求数' },
    { id: 'tokens', label: '总 Token', value: current ? formatTokens(current.total_tokens) : '—', hint: '输入 + 输出，未知不估算' },
    { id: 'streak', label: '连续成功 / 失败', value: `${node.value?.success_streak ?? 0} / ${node.value?.failure_streak ?? 0}`, hint: '探测连击计数' },
  ]
})

const tokenCards = computed<Array<{ id: string; label: string; value: number | string; hint: string }>>(() => {
  const current = stats.value
  return [
    { id: 'input', label: '输入 Token', value: current ? formatTokens(current.input_tokens) : '—', hint: '下游 usage 累计' },
    { id: 'output', label: '输出 Token', value: current ? formatTokens(current.output_tokens) : '—', hint: '下游 usage 累计' },
    { id: 'total', label: '总 Token', value: current ? formatTokens(current.total_tokens) : '—', hint: '输入 + 输出' },
  ]
})

const latencyRows = computed(() => {
  const current = stats.value
  if (!current) return [] as Array<{ label: string; value: string }>
  const line = (label: string, value: { avg: number | null; p50: number | null; p95: number | null }, unit = 'ms') =>
    ({ label, value: value.avg === null ? '—' : `${value.avg.toFixed(0)} / ${value.p50?.toFixed(0) ?? '—'} / ${value.p95?.toFixed(0) ?? '—'} ${unit}` })
  return [
    line('连接', current.connect_ms),
    line('首字节 (TTFB)', current.ttfb_ms),
    line('首 Token (TTFT)', current.ttft_ms),
    line('总时长', current.duration_ms),
    line('输出 TPS', current.output_tps, 'tok/s'),
  ]
})

function tagType(tone: GatewayTone): 'success' | 'warning' | 'danger' | 'info' {
  if (tone === 'success') return 'success'
  if (tone === 'warning') return 'warning'
  if (tone === 'danger') return 'danger'
  return 'info'
}

function tokenText(row: GatewayRequestLog): string {
  if (!row.usage_known) return 'unknown'
  return `${row.input_tokens ?? 0} / ${row.output_tokens ?? 0} / ${row.total_tokens ?? 0}`
}

function latencyText(value: number | null): string {
  return value === null || value === undefined ? '—' : `${value} ms`
}

function poolName(poolId: string | null): string {
  if (!poolId) return '未分配'
  return pools.value.find((pool) => pool.id === poolId)?.name ?? poolId
}

// ElMain 是组件实例，滚动容器要用它渲染出来的 <main>。
function scroller(): HTMLElement | null {
  const element = contentRef.value?.$el
  return element instanceof HTMLElement ? element : null
}

// 视口变化会改变内容列高度，浏览器随后才把 scrollTop 夹到新区块，
// 所以等两帧布局稳定后再对齐选中态。
let syncFrame = 0
function scheduleSync(): void {
  cancelAnimationFrame(syncFrame)
  syncFrame = requestAnimationFrame(() => {
    syncFrame = requestAnimationFrame(syncActiveSection)
  })
}

function syncActiveSection(): void {
  const container = scroller()
  if (!container) return
  // 触底时最后一个区块可能永远到不了顶部，直接判定为当前区块。
  if (container.scrollTop > 0 && container.scrollTop + container.clientHeight >= container.scrollHeight - 4) {
    activeSection.value = sections[sections.length - 1].id
    return
  }
  const top = container.getBoundingClientRect().top
  let current = sections[0].id
  for (const item of sections) {
    const element = document.getElementById(item.id)
    if (element && element.getBoundingClientRect().top - top <= sectionOffset) current = item.id
  }
  activeSection.value = current
}

function jumpTo(index: string): void {
  const element = document.getElementById(index)
  if (!element) return
  element.scrollIntoView({ block: 'start' })
  activeSection.value = index
  // 锚点可能被容器边距或触底夹住，落定后按真实滚动位置复核一次。
  scheduleSync()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [nodeValue, poolList, checks, requestPage, hours, days] = await Promise.all([
      gatewayApi.node(nodeId.value),
      gatewayApi.pools(),
      gatewayApi.healthChecks(nodeId.value, 100),
      gatewayApi.requests({ node_id: nodeId.value, page: 1, page_size: 50 }),
      gatewayApi.stats('node', 'hour', nodeId.value),
      gatewayApi.stats('node', 'today', nodeId.value),
    ])
    node.value = nodeValue
    pools.value = poolList
    healthChecks.value = checks
    requests.value = requestPage
    hourTokens.value = hours
    dayTokens.value = days
    await loadStats()
  } catch (reason) {
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
    error.value = errorMessage(reason, '节点详情加载失败')
  } finally {
    loading.value = false
    await nextTick()
    syncActiveSection()
  }
}

async function loadStats(): Promise<void> {
  try {
    stats.value = await gatewayApi.stats('node', statsWindow.value, nodeId.value)
  } catch (reason) {
    error.value = errorMessage(reason, '统计加载失败')
  }
}

async function loadRequests(target: number = requests.value.page): Promise<void> {
  logsLoading.value = true
  try {
    requests.value = await gatewayApi.requests({ node_id: nodeId.value, page: target, page_size: requests.value.page_size })
  } catch (reason) {
    notify(errorMessage(reason, '日志加载失败'), 'error')
  } finally {
    logsLoading.value = false
  }
}

async function probe(): Promise<void> {
  working.value = true
  try {
    const result = await gatewayApi.probeNode(nodeId.value, allProbes)
    const passed = result.checks.filter((check) => check.success).length
    notify(`探测完成：${passed}/${result.checks.length} 项通过`, passed === result.checks.length ? 'success' : 'info')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '探测失败'), 'error')
  } finally {
    working.value = false
  }
}

async function drain(): Promise<void> {
  const confirmed = await confirmDialog({ title: '安全下线节点', message: '活跃请求会继续完成，新请求改走其它节点。', confirmLabel: '安全下线', danger: true })
  if (!confirmed) return
  working.value = true
  try {
    await gatewayApi.drainNode(nodeId.value)
    notify('节点已进入安全下线')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '下线失败'), 'error')
  } finally {
    working.value = false
  }
}

async function restore(): Promise<void> {
  working.value = true
  try {
    await gatewayApi.activateNode(nodeId.value)
    notify('节点已恢复调度')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '恢复失败'), 'error')
  } finally {
    working.value = false
  }
}

async function toggleConfig(): Promise<void> {
  if (!node.value) return
  const enable = node.value.config_state !== 'ENABLED'
  working.value = true
  try {
    await gatewayApi.updateNode(nodeId.value, { config_state: enable ? 'ENABLED' : 'DISABLED' })
    notify(enable ? '节点已启用' : '节点已禁用')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '状态更新失败'), 'error')
  } finally {
    working.value = false
  }
}

function openEditor(): void {
  editorOpen.value = true
}

function backToList(): void {
  void router.push('/gateway/nodes')
}

watch(nodeId, () => { void load() })
watch(statsWindow, () => { void loadStats() })

onMounted(() => {
  window.addEventListener('resize', scheduleSync)
  void load()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', scheduleSync)
  cancelAnimationFrame(syncFrame)
})
</script>

<style scoped>
.gateway-node-page { height: calc(100vh - 68px); overflow: hidden; background: var(--astra-bg-base); }
.gateway-node-header { --el-header-height: auto; --el-header-padding: 0; display: flex; align-items: center; gap: 16px; padding: 14px 24px; border-bottom: 1px solid var(--astra-border); background: var(--astra-bg-panel); }
.gateway-node-title { display: grid; min-width: 0; gap: 3px; margin-right: auto; }
.gateway-node-back { display: inline-flex; align-items: center; gap: 4px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-node-back:hover { color: var(--astra-primary-bright); }
.gateway-node-title__row { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.gateway-node-title h2 { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-section); line-height: normal; }
.gateway-node-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.gateway-node-actions { display: flex; flex: none; flex-wrap: wrap; align-items: center; gap: 8px; }
.gateway-node-body { --el-main-padding: 16px 24px; display: flex; flex-direction: column; gap: 12px; overflow: hidden; }
.gateway-node-state { flex: none; min-height: 200px; }
.gateway-node-layout { flex: 1 1 auto; min-height: 0; }
.gateway-node-nav { --el-aside-width: 168px; overflow: visible; }
.gateway-node-nav :deep(.el-menu) { --el-menu-base-level-padding: 12px; --el-menu-item-height: 38px; border-right: 0; background: transparent; }
.gateway-node-nav :deep(.el-menu-item) { gap: 8px; }
.gateway-node-content { --el-main-padding: 0 4px 0 0; display: grid; align-content: start; gap: 26px; min-width: 0; min-height: 0; }
.gateway-node-section { display: grid; gap: 12px; }
.gateway-node-section__bar { display: flex; align-items: center; gap: 12px; }
.gateway-node-section__bar h3 { margin: 0; margin-right: auto; color: var(--astra-text-primary); }
.gateway-node-window { flex: none; }
.gateway-node-metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.gateway-node-metrics--three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.gateway-node-metrics :deep(.el-statistic__head) { color: var(--astra-text-muted); font-size: var(--astra-font-control); }
.gateway-node-metrics :deep(.el-statistic__content) { color: var(--astra-text-primary); font-size: var(--astra-font-subtitle); font-weight: var(--astra-weight-bold); }
.gateway-node-metric-hint { margin: 4px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-node-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 12px; align-items: start; }
.gateway-node-card-head { display: flex; align-items: flex-start; gap: 12px; }
.gateway-node-card-head > div { margin-right: auto; }
.gateway-node-card-head h4 { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-control); }
.gateway-node-note { display: flex; align-items: center; gap: 6px; margin: 10px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-node-peak { display: flex; gap: 16px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--astra-border); color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-node-peak b { color: var(--astra-text-primary); font-variant-numeric: tabular-nums; }
.gateway-node-peak--bad { color: var(--astra-danger); }
.gateway-node-snapshot { max-height: 220px; margin: 10px 0 0; padding: 10px; overflow: auto; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 8px; background: var(--astra-bg-base); font: var(--astra-font-helper)/1.5 var(--astra-font-family); white-space: pre-wrap; }
.gateway-node-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-node-num { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-node-err { color: var(--astra-danger); font-size: var(--astra-font-helper); }
.gateway-node-cell { display: grid; min-width: 0; }
.gateway-node-cell strong { color: var(--astra-text-primary); font-size: var(--astra-font-helper); }
.gateway-node-cell span { color: var(--astra-text-muted); font-size: var(--astra-font-micro); }
.gateway-node-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 12px; }
@media (max-width: 1280px) { .gateway-node-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } .gateway-node-grid { grid-template-columns: 1fr; } }
@media (max-width: 1000px) { .gateway-node-header { align-items: flex-start; flex-wrap: wrap; } .gateway-node-nav { --el-aside-width: auto; } }
@media (max-width: 760px) { .gateway-node-actions { width: 100%; } .gateway-node-metrics, .gateway-node-metrics--three { grid-template-columns: repeat(2, minmax(0, 1fr)); } .gateway-node-section__bar { flex-wrap: wrap; } .gateway-node-footer { flex-direction: column; align-items: flex-start; } }
</style>
