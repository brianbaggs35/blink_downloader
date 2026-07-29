import { createRouter, createWebHistory } from "vue-router";

import { authGuard } from "./guards";
import AppShell from "@/layouts/AppShell.vue";
import AiUsageView from "@/views/AiUsageView.vue";
import AiView from "@/views/AiView.vue";
import BiometricsView from "@/views/BiometricsView.vue";
import IntegrationsView from "@/views/IntegrationsView.vue";
import LibraryView from "@/views/LibraryView.vue";
import LiveView from "@/views/LiveView.vue";
import LoginView from "@/views/LoginView.vue";
import SecurityFeedView from "@/views/SecurityFeedView.vue";
import SettingsView from "@/views/SettingsView.vue";
import SetupView from "@/views/SetupView.vue";
import StatusView from "@/views/StatusView.vue";
import StorageView from "@/views/StorageView.vue";
import SyncModuleView from "@/views/SyncModuleView.vue";
import VehiclesView from "@/views/VehiclesView.vue";

export const routes = [
  { path: "/login", name: "login", component: LoginView, meta: { title: "Sign in" } },
  { path: "/setup", name: "setup", component: SetupView, meta: { title: "Setup" } },
  {
    path: "/",
    component: AppShell,
    children: [
      {
        path: "security-feed",
        name: "security-feed",
        component: SecurityFeedView,
        meta: { title: "Security Feed" },
      },
      { path: "", name: "library", component: LibraryView, meta: { title: "Library" } },
      { path: "status", name: "status", component: StatusView, meta: { title: "Status" } },
      { path: "live", name: "live-view", component: LiveView, meta: { title: "Live View" } },
      { path: "storage", name: "storage", component: StorageView, meta: { title: "Storage" } },
      {
        path: "sync-module",
        name: "sync-module",
        component: SyncModuleView,
        meta: { title: "Sync Module" },
      },
      {
        path: "integrations",
        name: "integrations",
        component: IntegrationsView,
        meta: { title: "Integrations" },
      },
      { path: "ai", name: "ai", component: AiView, meta: { title: "AI" } },
      { path: "ai-usage", name: "ai-usage", component: AiUsageView, meta: { title: "AI Usage" } },
      { path: "vehicles", name: "vehicles", component: VehiclesView, meta: { title: "Vehicles" } },
      {
        path: "biometrics",
        name: "biometrics",
        component: BiometricsView,
        meta: { title: "Biometrics" },
      },
      { path: "settings", name: "settings", component: SettingsView, meta: { title: "Settings" } },
    ],
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(authGuard);
