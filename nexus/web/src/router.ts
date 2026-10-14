import { createRouter, createWebHistory } from "vue-router";
import EmployeesView from "./views/EmployeesView.vue";
import ChatView from "./views/ChatView.vue";
import TeamView from "./views/TeamView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/employees" },
    { path: "/employees", name: "employees", component: EmployeesView },
    { path: "/chat", name: "chat", component: ChatView },
    { path: "/team", name: "team", component: TeamView },
  ],
});
