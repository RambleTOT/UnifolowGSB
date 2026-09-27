import { defineConfig } from "vitest/config";

// Тесты форматирования, словаря и правил фильтров не трогают DOM-плагины,
// поэтому настройка держится отдельно от сборки: так типы vite и vitest не
// конфликтуют между собой.
export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
