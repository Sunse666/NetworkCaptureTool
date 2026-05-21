import { createApp } from "vue";
import App from "./App.vue";
import "./styles.css";

// 前端入口：只负责挂载根组件，具体业务拆到组件和 API 模块中。
createApp(App).mount("#app");
