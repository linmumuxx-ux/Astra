<template>
  <el-drawer v-model="visible" append-to-body :title="employee ? '编辑数字员工' : '创建数字员工'" size="610px" :close-on-click-modal="false" @close="onClose">
    <el-form label-position="top" @submit.prevent="submit">
      <div class="form-cap">身份与职责</div>
      <div class="pair">
        <el-form-item label="员工名称" required>
          <el-input v-model="form.name" maxlength="24" placeholder="例如：星河" />
        </el-form-item>
        <el-form-item label="责任领域" required>
          <el-input v-model="form.domain" maxlength="42" placeholder="例如：测试自动化工程师" />
        </el-form-item>
      </div>
      <el-form-item label="员工形象">
        <el-select v-model="form.avatar" style="width: 100%">
          <el-option v-for="item in avatars" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item label="职责说明" required>
        <el-input v-model="form.description" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="工作指令" required>
        <el-input v-model="form.instructions" type="textarea" :rows="5" />
      </el-form-item>
      <div class="form-cap">知识与工具</div>
      <el-form-item label="知识">
        <el-select
          v-model="form.knowledge"
          multiple
          filterable
          :placeholder="catalogs.knowledge.available ? '选择知识库' : '当前无法读取知识库'"
          style="width: 100%"
          :disabled="!catalogs.knowledge.available"
        >
          <el-option v-for="item in knowledgeOptions" :key="item.id" :label="`${item.name} · ${item.id}`" :value="item.id" />
        </el-select>
        <div class="muted" style="margin-top: 6px">知识库来自 AgentScope。读不到目录时不能新增。</div>
      </el-form-item>
      <el-form-item label="技能">
        <el-select
          v-model="form.skills"
          multiple
          filterable
          :placeholder="skillOptions.length ? '选择技能' : '当前没有可选技能'"
          style="width: 100%"
          :disabled="!skillOptions.length"
        >
          <el-option v-for="item in skillOptions" :key="item.id" :label="`${item.name} · ${item.id}`" :value="item.id" />
        </el-select>
        <div class="muted" style="margin-top: 6px">任务管理是内置技能。其余技能仍来自 AgentScope，这里不能编写技能正文。</div>
      </el-form-item>
      <el-form-item label="工具">
        <el-select
          v-model="form.tools"
          multiple
          filterable
          :placeholder="catalogs.tools.available ? '选择工具' : '当前无法确认工具'"
          style="width: 100%"
          :disabled="!catalogs.tools.available"
        >
          <el-option v-for="item in toolOptions" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <div class="muted" style="margin-top: 6px">
          可选范围是工作区自带工具和 contact_employee。不能填写目录外的名称。
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <div class="footer">
        <el-switch v-model="form.enabled" active-text="启用此员工" />
        <div>
          <el-button @click="emit('close')">取消</el-button>
          <el-button type="primary" @click="submit">保存员工</el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from "vue";
import type { Employee, ResourceCatalog } from "../types";

const props = defineProps<{
  open: boolean;
  employee: Employee | null;
  catalogs: {
    skills: ResourceCatalog;
    knowledge: ResourceCatalog;
    tools: ResourceCatalog;
  };
}>();
const emit = defineEmits<{
  close: [];
  save: [body: Omit<Employee, "id" | "agentscope_agent_id" | "mailbox_session_id">];
}>();

const avatars = ["👩🏻‍💻", "🧑🏻‍🔬", "👩🏽‍🚀", "🤖", "🧑🏽‍💻"];
const defaultInstructions = "收到消息后先判断能否直接回答；信息不足时追问；需要其他员工帮助时联系相应员工。";
const form = reactive({
  name: "",
  domain: "",
  description: "",
  instructions: defaultInstructions,
  avatar: "👩🏻‍💻",
  enabled: true,
  knowledge: [] as string[],
  skills: [] as string[],
  tools: [] as string[],
});

const visible = ref(false);
let openedAt = 0;
watch(
  () => props.open,
  async (open) => {
    if (!open) {
      visible.value = false;
      return;
    }
    await nextTick();
    openedAt = Date.now();
    visible.value = true;
  },
  { immediate: true },
);
function onClose() {
  if (props.open && Date.now() - openedAt < 400) {
    visible.value = true;
    return;
  }
  if (props.open) emit("close");
}

const skillOptions = computed(() => optionsFor(props.catalogs.skills, form.skills));
const knowledgeOptions = computed(() => optionsFor(props.catalogs.knowledge, form.knowledge));
const toolOptions = computed(() => optionsFor(props.catalogs.tools, form.tools));

watch(
  () => [props.open, props.employee] as const,
  () => {
    const employee = props.employee;
    form.name = employee?.name ?? "";
    form.domain = employee?.domain ?? "";
    form.description = employee?.description ?? "";
    form.instructions = employee?.instructions ?? defaultInstructions;
    form.avatar = employee?.avatar ?? "👩🏻‍💻";
    form.enabled = employee?.enabled ?? true;
    form.knowledge = [...(employee?.knowledge ?? [])];
    form.skills = [...(employee?.skills ?? [])];
    form.tools = [...(employee?.tools ?? defaultTools())];
  },
  { immediate: true },
);

function optionsFor(catalog: ResourceCatalog, selected: string[]) {
  const options = new Map(catalog.items.map((item) => [item.id, item]));
  for (const id of selected) {
    if (!options.has(id)) options.set(id, { id, name: id });
  }
  return [...options.values()];
}

function defaultTools(): string[] {
  if (!props.catalogs.tools.available) return [];
  const known = props.catalogs.tools.items.some((item) => item.id === "contact_employee");
  return known ? ["contact_employee"] : [];
}

function submit() {
  emit("save", {
    name: form.name.trim(),
    domain: form.domain.trim(),
    description: form.description.trim(),
    instructions: form.instructions.trim(),
    avatar: form.avatar,
    enabled: form.enabled,
    knowledge: [...form.knowledge],
    skills: [...form.skills],
    tools: [...form.tools],
  });
}
</script>

<style scoped>
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.footer { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
</style>
