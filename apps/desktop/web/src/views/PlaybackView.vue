<script setup lang="ts">
import LyreKeyboard from "../components/LyreKeyboard.vue";
import StudioIcon from "../components/StudioIcon.vue";
import type { LyraStore } from "../composables/useLyraStore";

defineProps<{
  store: LyraStore;
}>();
</script>

<template>
  <section class="view-stack" aria-label="试听导出与安全演奏">
    <header class="view-header">
      <div>
        <h1 class="view-title">试听、导出与游戏演奏控制台</h1>
        <p class="view-subtitle">
          先离线 WAV 试听，再通过两段授权确认启动 Dry-Run 模拟或 Windows 受控按键发送。
        </p>
      </div>
      <button
        v-if="store.playbackStatus.value?.state === 'running'"
        class="danger"
        type="button"
        @click="store.handleEmergencyStop"
      >
        <StudioIcon name="stop" />
        紧急停止演奏
      </button>
    </header>

    <div class="split-2">
      <div class="view-stack" style="gap: var(--space-4)">
        <div class="card">
          <div class="card-title-row">
            <h2>离线音频试听与导出</h2>
            <span v-if="store.arrDetail.value" class="pill">
              {{ store.arrDetail.value.arrangement.label || store.arrDetail.value.arrangement.style }}
            </span>
          </div>

          <div class="button-row">
            <button
              class="primary"
              type="button"
              :disabled="!store.selectedArrId.value || store.busy.value"
              @click="store.handlePreview"
            >
              <StudioIcon name="play" />
              合成试听音频
            </button>
            <button
              class="secondary"
              type="button"
              :disabled="!store.selectedArrId.value"
              @click="store.handleExport('midi')"
            >
              <StudioIcon name="download" />
              导出 MIDI
            </button>
            <button
              class="secondary"
              type="button"
              :disabled="!store.selectedArrId.value"
              @click="store.handleExport('json')"
            >
              导出 JSON
            </button>
          </div>

          <audio
            v-if="store.previewUrl.value"
            controls
            :src="store.previewUrl.value"
            style="inline-size: 100%"
          />

          <div
            style="
              padding: 12px;
              border-radius: var(--radius-md);
              border: 1px solid var(--border-subtle);
              background: var(--bg-canvas);
              display: flex;
              flex-direction: column;
              gap: 10px;
            "
          >
            <h3>导出曲谱分享包 (.lyrapack)</h3>
            <p class="muted" style="margin: 0">
              分享包默认仅包含编曲键位事件与许可摘要，绝不包含任何原始音频、视频或密钥。
            </p>
            <label class="checkbox-row">
              <input v-model="store.packRightsConfirmed.value" type="checkbox" />
              我确认拥有本曲谱的合法分享授权并遵守原始版权许可
            </label>
            <div class="button-row">
              <button
                class="secondary"
                type="button"
                :disabled="!store.selectedArrId.value"
                @click="store.handleExportLyrapack"
              >
                <StudioIcon name="download" />
                导出分享包 (.lyrapack)
              </button>
            </div>
          </div>
        </div>

        <div class="card">
          <h2>21 键映射实时热力概览</h2>
          <LyreKeyboard
            v-if="store.profile.value"
            :keys="store.profile.value.keys"
            :event-counts="store.eventCounts.value"
          />
        </div>
      </div>

      <div class="card">
        <div class="card-title-row">
          <h2>安全演奏控制（两段确认门控）</h2>
          <span
            class="pill"
            :class="store.playbackStatus.value?.state === 'running' ? 'pill-warn' : 'pill-ok'"
          >
            {{ store.playbackStatus.value?.state ?? "idle" }}
          </span>
        </div>

        <div class="banner-info">
          <StudioIcon name="alert" :size="16" />
          <div>
            严格遵守安全边界：不读取/修改游戏内存，不注入进程，仅在用户显式点击两段确认后执行按键时序。切窗失焦或按 Esc 立即停止。
          </div>
        </div>

        <div class="field">
          <label for="playback-mode">演奏模式</label>
          <select id="playback-mode" v-model="store.playbackMode.value">
            <option value="dry-run">Dry-Run 安全模拟（推荐调试与 macOS）</option>
            <option
              value="windows"
              :disabled="!store.health.value?.windows_playback_available"
            >
              Windows 原神窗口 SendInput（仅 Windows）
            </option>
          </select>
        </div>

        <details class="advanced-box">
          <summary>高级时序控制（实时节拍发送）</summary>
          <div style="margin-block-start: var(--space-2)">
            <label class="checkbox-row">
              <input v-model="store.realtime.value" type="checkbox" />
              按真实演奏时间间隔发送事件（测试可取消勾选加快 Dry-Run）
            </label>
          </div>
        </details>

        <div class="button-row">
          <button
            class="secondary"
            type="button"
            :disabled="!store.selectedArrId.value || store.busy.value"
            @click="store.handlePrepare"
          >
            1. 准备演奏
          </button>
          <button
            class="primary"
            type="button"
            :disabled="!store.prepared.value || store.busy.value"
            @click="store.handleStart"
          >
            <StudioIcon name="play" />
            2. 确认授权开始（随后切到游戏）
          </button>
          <button
            v-if="store.playbackStatus.value?.state === 'running'"
            class="secondary"
            type="button"
            @click="store.handlePause"
          >
            暂停
          </button>
          <button
            v-if="store.playbackStatus.value?.state === 'paused'"
            class="primary"
            type="button"
            @click="store.handleResume"
          >
            继续
          </button>
          <button
            class="danger"
            type="button"
            @click="store.handleEmergencyStop"
          >
            <StudioIcon name="stop" />
            紧急停止
          </button>
        </div>

        <div v-if="store.prepared.value" class="banner-warn">
          <StudioIcon name="alert" />
          <div class="view-stack" style="gap: 4px">
            <strong>请核对演奏风险提示：</strong>
            <span>{{ store.prepared.value.risk_notice }}</span>
            <span class="muted tabular">
              模式：{{ store.prepared.value.mode }} · 预计 {{ store.prepared.value.event_count }} 个事件
            </span>
            <span class="muted">
              开始后会先进入「等待游戏窗口」，请在 10 秒内切到《原神》；检测到游戏前置且权限一致后才会发送按键，超时不会发送任何按键。
            </span>
          </div>
        </div>

        <div
          v-if="store.playbackStatus.value?.state === 'waiting_focus'"
          class="banner-info"
        >
          <StudioIcon name="alert" />
          <span>
            正在等待《原神》窗口获得前台…请切换到游戏；若超时，会提示当前前台窗口并停止。
          </span>
        </div>

        <div
          v-if="store.playbackStatus.value?.state === 'permission_required'"
          class="banner-error"
        >
          <StudioIcon name="alert" />
          <div class="view-stack" style="gap: 8px">
            <span>
              {{ store.playbackStatus.value.last_result?.error ?? '权限不足：请以管理员身份重启 LyraForge。' }}
            </span>
            <div>
              <button class="secondary" type="button" @click="store.handleRelaunchElevated">
                以管理员身份重启 LyraForge
              </button>
            </div>
          </div>
        </div>

        <div v-if="store.playbackStatus.value" class="stats-grid">
          <div class="stat-card">
            <div class="label">当前状态</div>
            <div class="value">{{ store.playbackStatus.value.state }}</div>
          </div>
          <div class="stat-card">
            <div class="label">激活模式</div>
            <div class="value">{{ store.playbackStatus.value.mode ?? store.playbackMode.value }}</div>
          </div>
          <div class="stat-card">
            <div class="label">已发送 / 总计</div>
            <div class="value">
              {{ store.playbackStatus.value.last_result?.actions_sent ?? 0 }} /
              {{ store.playbackStatus.value.last_result?.actions_total ?? 0 }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
