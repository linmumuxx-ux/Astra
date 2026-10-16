import { createRouter, createWebHistory, type LocationQueryRaw, type RouteLocationGeneric } from "vue-router";
import EmployeesView from "./views/EmployeesView.vue";
import ChatView from "./views/ChatView.vue";
import TeamView from "./views/TeamView.vue";
import TaskListView from "./views/TaskListView.vue";
import TaskDetailView from "./views/TaskDetailView.vue";
import EmployeeListView from "./views/EmployeeListView.vue";
import EmployeeDetailView from "./views/EmployeeDetailView.vue";
import DigitalLibraryView from "./views/DigitalLibraryView.vue";
import InterventionView from "./views/InterventionView.vue";
import SettingsView from "./views/SettingsView.vue";
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

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/employees" },
    { path: "/employees", name: "employees", component: EmployeesView },
    { path: "/chat", name: "chat", component: ChatView },
    { path: "/team", name: "team", component: TeamView },
    { path: "/tasks", name: "tasks", component: TaskListView },
    { path: "/tasks/:id", name: "task-detail", component: TaskDetailView },
    { path: "/workers", name: "workers", component: EmployeeListView },
    { path: "/workers/:id", name: "worker-detail", component: EmployeeDetailView },
    { path: "/library", name: "library", component: DigitalLibraryView },
    { path: "/settings", name: "settings", component: SettingsView },
    { path: "/interventions", name: "interventions", component: InterventionView },
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
