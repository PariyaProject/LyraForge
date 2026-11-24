<script setup lang="ts">
export type StudioIconName =
  | "home"
  | "library"
  | "sparkles"
  | "sliders"
  | "play"
  | "pause"
  | "settings"
  | "upload"
  | "search"
  | "star"
  | "download"
  | "stop"
  | "alert"
  | "check"
  | "copy"
  | "music"
  | "x"
  | "skip-back"
  | "skip-forward"
  | "chevron-right"
  | "chevron-down"
  | "panel-right"
  | "keyboard"
  | "cpu"
  | "shield"
  | "trash"
  | "edit"
  | "refresh"
  | "plus"
  | "minus"
  | "undo"
  | "redo"
  | "info"
  | "list-music";

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
    stroke-width="1.75"
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
      <path d="M12 3v3m0 12v3M4.5 12H3m18 0h-1.5" />
      <path d="M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0Z" />
      <path d="m6.5 6.5 2 2m7 7 2 2m0-11-2 2m-7 7-2 2" />
    </template>
    <template v-else-if="name === 'sliders'">
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4" />
    </template>
    <template v-else-if="name === 'play'">
      <polygon points="7 4 19 12 7 20 7 4" />
    </template>
    <template v-else-if="name === 'pause'">
      <rect x="6" y="4" width="4" height="16" rx="1" />
      <rect x="14" y="4" width="4" height="16" rx="1" />
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
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
    </template>
    <template v-else-if="name === 'alert'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5m0 3h.01" />
    </template>
    <template v-else-if="name === 'check'">
      <polyline points="20 6 9 17 4 12" />
    </template>
    <template v-else-if="name === 'copy'">
      <rect x="9" y="9" width="11" height="11" rx="1.5" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </template>
    <template v-else-if="name === 'x'">
      <path d="M18 6 6 18M6 6l12 12" />
    </template>
    <template v-else-if="name === 'skip-back'">
      <polygon points="19 20 9 12 19 4 19 20" />
      <line x1="5" y1="19" x2="5" y2="5" />
    </template>
    <template v-else-if="name === 'skip-forward'">
      <polygon points="5 4 15 12 5 20 5 4" />
      <line x1="19" y1="5" x2="19" y2="19" />
    </template>
    <template v-else-if="name === 'chevron-right'">
      <polyline points="9 18 15 12 9 6" />
    </template>
    <template v-else-if="name === 'chevron-down'">
      <polyline points="6 9 12 15 18 9" />
    </template>
    <template v-else-if="name === 'panel-right'">
      <rect x="3" y="4" width="18" height="16" rx="1.5" />
      <line x1="15" y1="4" x2="15" y2="20" />
    </template>
    <template v-else-if="name === 'keyboard'">
      <rect x="2" y="5" width="20" height="14" rx="1.5" />
      <path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M7 13h10" />
    </template>
    <template v-else-if="name === 'cpu'">
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
      <path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4" />
    </template>
    <template v-else-if="name === 'shield'">
      <path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z" />
    </template>
    <template v-else-if="name === 'trash'">
      <path d="M3 6h18M8 6V4h8v2M6 6v14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V6" />
    </template>
    <template v-else-if="name === 'edit'">
      <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" />
    </template>
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>
    <template v-else-if="name === 'minus'">
      <path d="M5 12h14" />
    </template>
    <template v-else-if="name === 'undo'">
      <path d="M9 14 4 9l5-5" />
      <path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
    </template>
    <template v-else-if="name === 'redo'">
      <path d="m15 14 5-5-5-5" />
      <path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13" />
    </template>
    <template v-else-if="name === 'info'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-4M12 8h.01" />
    </template>
    <template v-else-if="name === 'list-music'">
      <path d="M16 4v10M16 4l4 1v3l-4-1M4 7h8M4 12h8M4 17h6" />
      <circle cx="14" cy="16" r="2.5" />
    </template>
    <template v-else>
      <path d="M9 18V5l11-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="17" cy="16" r="3" />
    </template>
  </svg>
</template>
