<template>
  <aside class="panel left-rail conv-list">
    <div class="conv-list-header">
      <el-input
        v-model="searchQuery"
        placeholder="搜索员工或群组"
        data-testid="conv-search"
        clearable
      />
      <div class="conv-filter-row">
        <el-radio-group v-model="filter" size="small" data-testid="conv-filter">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="contact">联系人</el-radio-button>
          <el-radio-button value="group">群组</el-radio-button>
        </el-radio-group>
        <el-button
          size="small"
          data-testid="conv-create-group"
          @click="$emit('create-group')"
          title="创建群组"
        >
          ＋
        </el-button>
      </div>
    </div>

    <div v-if="!filteredItems.length" class="empty">
      {{ emptyText }}
    </div>

    <div v-else class="conv-items-scroll">
      <button
        v-for="item in filteredItems"
        :key="`${item.kind}_${item.id}`"
        type="button"
        class="rail-item"
        :class="{ active: currentKind === item.kind && currentId === item.id }"
        :data-testid="item.kind === 'contact' ? `conv-item-contact-${item.id}` : `conv-item-group-${item.id}`"
        @click="$emit('select', { kind: item.kind, id: item.id })"
      >
        <span class="avatar" :class="{ off: item.kind === 'contact' && !item.enabled }">{{ item.avatar }}</span>
        <span class="conv-item-text">
          <b class="conv-item-name">{{ item.name }}</b>
          <small class="muted conv-item-sub">
            <span>{{ item.secondary }}</span>
            <span v-if="item.kind === 'contact' && !item.enabled" class="tag ash" style="margin-left: 4px">已禁用</span>
          </small>
        </span>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Channel, Employee } from "@/types";
import type { ConversationKind, UnifiedListItem } from "./types";

const props = defineProps<{
  employees: Employee[];
  channels: Channel[];
  currentKind: ConversationKind | null;
  currentId: string | null;
  defaultFilter?: "all" | "contact" | "group";
}>();

defineEmits<{
  (e: "select", payload: { kind: ConversationKind; id: string }): void;
  (e: "create-group"): void;
}>();

const filter = ref<"all" | "contact" | "group">(props.defaultFilter || "all");
watch(
  () => props.defaultFilter,
  (val) => {
    if (val) filter.value = val;
  },
);

const searchQuery = ref("");

const employeeNameMap = computed(() => {
  const map = new Map<string, string>();
  for (const emp of props.employees) {
    map.set(emp.id, emp.name);
  }
  return map;
});

const allItems = computed<UnifiedListItem[]>(() => {
  const items: UnifiedListItem[] = [];

  props.employees.forEach((emp, index) => {
    items.push({
      kind: "contact",
      id: emp.id,
      name: emp.name,
      avatar: emp.avatar || "👤",
      secondary: emp.domain || "",
      enabled: emp.enabled,
      // List APIs expose no reliable last-activity time, so keep API order.
      timestamp: null,
      orderIndex: index,
      raw: emp,
    });
  });

  props.channels.forEach((chan, index) => {
    items.push({
      kind: "group",
      id: chan.id,
      name: chan.name,
      avatar: "☷",
      secondary: `${chan.members?.length ?? 0} 位成员`,
      enabled: true,
      // List APIs expose no reliable last-activity time, so keep API order.
      timestamp: null,
      orderIndex: 100000 + index,
      raw: chan,
    });
  });

  items.sort((a, b) => {
    const aHasTime = a.timestamp !== null && !isNaN(a.timestamp);
    const bHasTime = b.timestamp !== null && !isNaN(b.timestamp);
    if (aHasTime && bHasTime) {
      return (b.timestamp as number) - (a.timestamp as number);
    }
    if (aHasTime && !bHasTime) return -1;
    if (!aHasTime && bHasTime) return 1;
    return a.orderIndex - b.orderIndex;
  });

  return items;
});

const filteredItems = computed<UnifiedListItem[]>(() => {
  const q = searchQuery.value.trim().toLowerCase();

  return allItems.value.filter((item) => {
    if (filter.value === "contact" && item.kind !== "contact") return false;
    if (filter.value === "group" && item.kind !== "group") return false;

    if (!q) return true;

    if (item.kind === "contact") {
      const emp = item.raw as Employee;
      const nameMatch = emp.name.toLowerCase().includes(q);
      const domainMatch = (emp.domain || "").toLowerCase().includes(q);
      const descMatch = (emp.description || "").toLowerCase().includes(q);
      return nameMatch || domainMatch || descMatch;
    }

    if (item.kind === "group") {
      const chan = item.raw as Channel;
      const nameMatch = chan.name.toLowerCase().includes(q);
      const memberNames = (chan.members || [])
        .map((m) => employeeNameMap.value.get(m.employee_id) || "")
        .join(" ")
        .toLowerCase();
      const memberMatch = memberNames.includes(q);
      return nameMatch || memberMatch;
    }

    return true;
  });
});

const emptyText = computed(() => {
  if (searchQuery.value.trim()) {
    return "无匹配结果";
  }
  if (filter.value === "contact") {
    return "暂无联系人";
  }
  if (filter.value === "group") {
    return "暂无群组";
  }
  if (props.employees.length === 0 && props.channels.length === 0) {
    return "暂无联系人";
  }
  return "无匹配结果";
});
</script>

<style scoped>
.conv-list {
  display: flex;
  flex-direction: column;
  padding: 14px 12px;
}
.conv-list-header {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
}
.conv-filter-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.conv-items-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.rail-item {
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 9px 8px;
  border-radius: 12px;
  cursor: pointer;
  margin-bottom: 4px;
}
.conv-item-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.conv-item-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conv-item-sub {
  display: flex;
  align-items: center;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
