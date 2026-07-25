import "@fontsource-variable/inter";
import "primeicons/primeicons.css";
import "./assets/base.css";

import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import { createApp } from "vue";

import App from "./App.vue";
import { initTheme } from "./composables/useTheme";
import { router } from "./router";
import { primeVueOptions } from "./theme";

initTheme();

createApp(App)
  .use(createPinia())
  .use(router)
  .use(PrimeVue, primeVueOptions)
  .use(ToastService)
  .mount("#app");
