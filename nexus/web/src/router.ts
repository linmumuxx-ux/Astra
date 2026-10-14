import { createRouter, createWebHistory } from "vue-router";
import EmployeesView from "./views/EmployeesView.vue";
import ChatView from "./views/ChatView.vue";
import TeamView from "./views/TeamView.vue";
import TasksView from "./views/TasksView.vue";
import WorkersView from "./views/WorkersView.vue";
import GatewayView from "./views/GatewayView.vue";
import LibraryView from "./views/LibraryView.vue";
import InterventionsView from "./views/InterventionsView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/employees" },
    { path: "/employees", name: "employees", component: EmployeesView },
    { path: "/chat", name: "chat", component: ChatView },
    { path: "/team", name: "team", component: TeamView },
    { path: "/tasks", name: "tasks", component: TasksView },
    { path: "/workers", name: "workers", component: WorkersView },
    { path: "/gateway", name: "gateway", component: GatewayView },
    { path: "/library", name: "library", component: LibraryView },
    { path: "/interventions", name: "interventions", component: InterventionsView },
  ],
});
