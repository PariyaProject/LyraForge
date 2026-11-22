<script setup lang="ts">
export type StudioIconName =
  | "home"
  | "library"
  | "sparkles"
  | "sliders"
  | "play"
  | "settings"
  | "upload"
  | "search"
  | "star"
  | "download"
  | "stop"
  | "alert"
  | "check"
  | "copy"
  | "music";

withDefaults(
  defineProps<{
    name: StudioIconName;
    size?: number;
  }>(),
  { size: 16 },
);
</script>

<template>
  <svg
    aria-hidden="true"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    style="flex-shrink: 0"
  >
    <template v-if="name === 'home'">
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V20h14V9.5" />
    </template>
    <template v-else-if="name === 'library'">
      <path d="M4 19V5a2 2 0 0 1 2-2h4v18H6a2 2 0 0 1-2-2Z" />
      <path d="M10 3h4v18h-4" />
      <path d="m15 5 5 1v14l-5-1" />
    </template>
    <template v-else-if="name === 'sparkles'">
      <path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9Z" />
      <path d="M5 19v-2m-1 1h2M19 5v-2m-1 1h2" />
    </template>
    <template v-else-if="name === 'sliders'">
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4" />
    </template>
    <template v-else-if="name === 'play'">
      <polygon points="6 4 20 12 6 20 6 4" />
    </template>
    <template v-else-if="name === 'settings'">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3m0 14v3M4.9 4.9l2.1 2.1m10 10 2.1 2.1M2 12h3m14 0h3M4.9 19.1 7 17m10-10 2.1-2.1" />
    </template>
    <template v-else-if="name === 'upload'">
      <path d="M12 16V4m0 0-4 4m4-4 4 4" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </template>
    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </template>
    <template v-else-if="name === 'star'">
      <polygon points="12 3 14.9 8.8 21 9.7 16.5 14.1 17.6 20.2 12 17.2 6.4 20.2 7.5 14.1 3 9.7 9.1 8.8 12 3" />
    </template>
    <template v-else-if="name === 'download'">
      <path d="M12 4v12m0 0-4-4m4 4 4-4" />
      <path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2" />
    </template>
    <template v-else-if="name === 'stop'">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </template>
    <template v-else-if="name === 'alert'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5m0 3h.01" />
    </template>
    <template v-else-if="name === 'check'">
      <polyline points="20 6 9 17 4 12" />
    </template>
    <template v-else-if="name === 'copy'">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </template>
    <template v-else>
      <path d="M9 18V5l11-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="17" cy="16" r="3" />
    </template>
  </svg>
</template>
