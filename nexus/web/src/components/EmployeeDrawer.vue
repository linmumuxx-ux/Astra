<template>
  <el-drawer :model-value="open" :title="employee ? '编辑数字员工' : '创建数字员工'" size="610px" @close="emit('close')">
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
      <el-form-item label="知识（每行一个知识库标识）">
        <el-input v-model="knowledgeText" type="textarea" :rows="3" placeholder="自动化框架 Wiki" />
      </el-form-item>
      <el-form-item label="技能">
        <el-select
          v-model="form.skills"
          multiple
          filterable
          :placeholder="catalog.available ? '选择技能' : '当前无法读取技能'"
          style="width: 100%"
          :disabled="!catalog.available"
        >
          <el-option v-for="item in skillOptions" :key="item.id" :label="`${item.name} · ${item.id}`" :value="item.id" />
        </el-select>
        <div class="muted" style="margin-top: 6px">技能来自 AgentScope 技能库，这里不能编写技能正文。</div>
      </el-form-item>
      <el-form-item label="工具（每行一个名称）">
        <el-input v-model="toolsText" type="textarea" :rows="2" placeholder="contact_employee" />
        <div class="muted" style="margin-top: 6px">contact_employee 由 Agent Service 注册。这些名称不会在 Nexus 里执行。</div>
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
import { computed, reactive, ref, watch } from "vue";
import type { Employee, SkillItem } from "../types";

const props = defineProps<{
  open: boolean;
  employee: Employee | null;
  catalog: { available: boolean; items: SkillItem[] };
}>();
const emit = defineEmits<{
  close: [];
  save: [body: Omit<Employee, "id" | "agentscope_agent_id" | "mailbox_session_id">];
}>();

const avatars = ["👩🏻‍💻", "🧑🏻‍🔬", "👩🏽‍🚀", "🤖", "🧑🏽‍💻"];
const form = reactive({
  name: "",
  domain: "",
  description: "",
  instructions: "收到消息后先判断能否直接回答；信息不足时追问；需要其他员工帮助时联系相应员工。",
  avatar: "👩🏻‍💻",
  enabled: true,
  knowledge: [] as string[],
  skills: [] as string[],
  tools: ["contact_employee"],
});
const knowledgeText = ref("");
const toolsText = ref("contact_employee");
const skillOptions = computed(() => {
  const options = new Map(props.catalog.items.map((item) => [item.id, item]));
  for (const id of form.skills) {
    if (!options.has(id)) options.set(id, { id, name: id });
  }
  return [...options.values()];
});

watch(
  () => [props.open, props.employee] as const,
  () => {
    const employee = props.employee;
    form.name = employee?.name ?? "";
    form.domain = employee?.domain ?? "";
    form.description = employee?.description ?? "";
    form.instructions = employee?.instructions ?? "收到消息后先判断能否直接回答；信息不足时追问；需要其他员工帮助时联系相应员工。";
    form.avatar = employee?.avatar ?? "👩🏻‍💻";
    form.enabled = employee?.enabled ?? true;
    form.skills = [...(employee?.skills ?? [])];
    knowledgeText.value = (employee?.knowledge ?? []).join("\n");
    toolsText.value = (employee?.tools ?? ["contact_employee"]).join("\n");
  },
  { immediate: true },
);

function split(value: string): string[] {
  return value.split(/\n|,|，/).map((item) => item.trim()).filter(Boolean);
}

function submit() {
  emit("save", {
    name: form.name.trim(),
    domain: form.domain.trim(),
    description: form.description.trim(),
    instructions: form.instructions.trim(),
    avatar: form.avatar,
    enabled: form.enabled,
    knowledge: split(knowledgeText.value),
    skills: [...form.skills],
    tools: split(toolsText.value),
  });
}
</script>

<style scoped>
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.footer { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
</style>
