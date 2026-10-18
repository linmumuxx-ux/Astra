import { createRouter, createWebHistory, type LocationQueryRaw, type RouteLocationGeneric } from "vue-router";
import EmployeesView from "./views/EmployeesView.vue";
import DigitalEmployeeChatView from "./views/DigitalEmployeeChatView.vue";
import TaskHallView from "./views/TaskHallView.vue";
import TaskDetailView from "./views/TaskDetailView.vue";
import EmployeeListView from "./views/EmployeeListView.vue";
import EmployeeDetailView from "./views/EmployeeDetailView.vue";
import DigitalLibraryView from "./views/DigitalLibraryView.vue";
import SettingsView from "./views/SettingsView.vue";
import CategoryConfig from "./views/settings/CategoryConfig.vue";
import AgentScopeView from "./views/settings/AgentScopeView.vue";
import GatewayView from "./views/gateway/GatewayView.vue";
import GatewayNodeDetailView from "./views/gateway/GatewayNodeDetailView.vue";
import GatewayOverview from "./views/gateway/GatewayOverview.vue";
import GatewayNodes from "./views/gateway/GatewayNodes.vue";
import GatewayPoolsRoutes from "./views/gateway/GatewayPoolsRoutes.vue";
import GatewayKeys from "./views/gateway/GatewayKeys.vue";
import GatewayRequests from "./views/gateway/GatewayRequests.vue";
import GatewayAudits from "./views/gateway/GatewayAudits.vue";

const gatewayTabSegments: Record<string, string> = {
  overview: "overview",
  nodes: "nodes",
  routes: "routes",
  keys: "keys",
  logs: "logs",
};

function gatewayIndexRedirect(to: RouteLocationGeneric) {
  const tab = typeof to.query.tab === "string" ? to.query.tab : "";
  const segment = gatewayTabSegments[tab] ?? "overview";
  const { tab: _tab, ...rest } = to.query;
  return { path: `/gateway/${segment}`, query: rest as LocationQueryRaw };
}

function teamRedirect(to: RouteLocationGeneric) {
  const channelId = to.query.channel ?? to.query.id;
  const { channel: _channel, id: _id, ...rest } = to.query;
  const query: Record<string, any> = { ...rest, kind: "group" };
  if (channelId !== undefined && channelId !== null && channelId !== "") {
    query.channel = channelId;
  }
  return { path: "/chat", query: query as LocationQueryRaw };
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      redirect: (to: RouteLocationGeneric) => ({ path: "/chat", query: to.query }),
    },
    { path: "/chat", name: "chat", component: DigitalEmployeeChatView },
    { path: "/tasks", name: "tasks", component: TaskHallView },
    { path: "/tasks/:id", name: "task-detail", component: TaskDetailView },
    { path: "/library", name: "library", component: DigitalLibraryView },
    {
      path: "/settings",
      component: SettingsView,
      children: [
        {
          path: "",
          redirect: (to: RouteLocationGeneric) => ({
            path: "/settings/employees",
            query: to.query,
          }),
        },
        { path: "employees", name: "settings-employees", component: EmployeesView },
        { path: "workers", name: "settings-workers", component: EmployeeListView },
        { path: "workers/:id", name: "settings-worker-detail", component: EmployeeDetailView },
        { path: "categories", name: "settings-categories", component: CategoryConfig },
        { path: "agentscope", name: "settings-agentscope", component: AgentScopeView },
      ],
    },
    {
      path: "/employees",
      redirect: (to: RouteLocationGeneric) => ({
        path: "/settings/employees",
        query: to.query,
      }),
    },
    {
      path: "/workers",
      redirect: (to: RouteLocationGeneric) => ({
        path: "/settings/workers",
        query: to.query,
      }),
    },
    {
      path: "/workers/:id",
      redirect: (to: RouteLocationGeneric) => ({
        path: `/settings/workers/${to.params.id}`,
        query: to.query,
      }),
    },
    { path: "/team", redirect: teamRedirect },
    {
      path: "/interventions",
      redirect: (to: RouteLocationGeneric) => ({
        path: "/tasks",
        query: { ...to.query, view: "pending" },
      }),
    },
    {
      path: "/gateway",
      component: GatewayView,
      children: [
        { path: "", name: "gateway", redirect: gatewayIndexRedirect },
        { path: "overview", name: "gateway-overview", component: GatewayOverview },
        { path: "nodes", name: "gateway-nodes", component: GatewayNodes },
        { path: "routes", name: "gateway-routes", component: GatewayPoolsRoutes },
        { path: "keys", name: "gateway-keys", component: GatewayKeys },
        { path: "logs", name: "gateway-logs", component: GatewayRequests },
        { path: "audits", name: "gateway-audits", component: GatewayAudits },
        { path: "nodes/:id", name: "gateway-node-detail", component: GatewayNodeDetailView },
        { path: ":removed(versions|self)", redirect: "/gateway/overview" },
      ],
    },
  ],
});
