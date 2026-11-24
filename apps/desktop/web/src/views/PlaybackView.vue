<script setup lang="ts">
import LyreKeyboard from "../components/LyreKeyboard.vue";
import StudioIcon from "../components/StudioIcon.vue";
import { arrangementTitle, type LyraStore } from "../composables/useLyraStore";

defineProps<{
  store: LyraStore;
}>();
</script>

<template>
  <section class="view-stack" aria-label="试听导出与安全演奏">
    <header class="view-header">
      <div>
        <h1 class="view-title">试听与演奏控制台</h1>
        <p class="view-subtitle">
          先离线试听合成音频并检查 21 键热力分布，再通过两段确认门控安全启动演奏。
        </p>
      </div>
      <button
        v-if="store.playbackStatus.value?.state === 'running'"
        class="danger"
        type="button"
        @click="store.handleEmergencyStop"
      >
        <StudioIcon name="stop" :size="15" />
        紧急停止演奏
      </button>
    </header>

    <div class="split-asymmetric">
      <div class="playback-left-col">
        <div class="pane">
          <div class="pane-header">
            <h2>21 键实时映射舞台</h2>
            <span v-if="store.arrDetail.value" class="pill">
              {{ arrangementTitle(store.arrDetail.value.arrangement) }}
            </span>
          </div>

          <LyreKeyboard
            v-if="store.profile.value"
            :keys="store.profile.value.keys"
            :event-counts="store.eventCounts.value"
            :active-key-ids="store.soundingKeyIds.value"
          />
          <div v-else class="empty-state">
            <p style="margin: 0">尚未加载乐器键位映射。</p>
          </div>
        </div>

        <div class="pane">
          <div class="pane-header">
            <h2>离线试听与文件导出</h2>
          </div>

          <div class="button-row">
            <button
              class="secondary"
              type="button"
              :disabled="!store.selectedArrId.value || store.busy.value"
              @click="store.handlePreview"
            >
              <StudioIcon name="play" :size="14" />
              合成试听音频
            </button>
            <button
              class="secondary"
              type="button"
              :disabled="!store.selectedArrId.value"
              @click="store.handleExport('midi')"
            >
              <StudioIcon name="download" :size="14" />
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

          <div class="section-block">
            <h3 class="subsection-heading">导出曲谱分享包 (.lyrapack)</h3>
            <p class="muted" style="margin: 0; font-size: 12px">
              分享包仅包含编曲键位事件与许可摘要，绝不包含原始音频、视频或密钥凭据。
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
                <StudioIcon name="download" :size="14" />
                导出分享包 (.lyrapack)
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="pane">
        <div class="pane-header">
          <h2>安全演奏控制（两段确认门控）</h2>
          <span
            class="pill"
            :class="store.playbackStatus.value?.state === 'running' ? 'pill-warn' : 'pill-ok'"
          >
            {{ store.playbackStatus.value?.state ?? "idle" }}
          </span>
        </div>

        <dl class="metric-strip">
          <div class="metric-cell">
            <dt>当前状态</dt>
            <dd>{{ store.playbackStatus.value?.state ?? "idle" }}</dd>
          </div>
          <div class="metric-cell">
            <dt>激活模式</dt>
            <dd>{{ store.playbackStatus.value?.mode ?? store.playbackMode.value }}</dd>
          </div>
          <div class="metric-cell">
            <dt>已发送 / 总计</dt>
            <dd>
              {{ store.playbackStatus.value?.last_result?.actions_sent ?? 0 }} /
              {{ store.playbackStatus.value?.last_result?.actions_total ?? 0 }}
            </dd>
          </div>
        </dl>

        <div
          v-if="store.playbackStatus.value?.last_result?.p50_lateness_ms !== undefined"
          class="timing-diag-strip tabular"
        >
          <span>
            调度误差 P50/P95/Max:
            {{ store.playbackStatus.value.last_result.p50_lateness_ms?.toFixed(2) }} /
            {{ store.playbackStatus.value.last_result.p95_lateness_ms?.toFixed(2) }} /
            {{ store.playbackStatus.value.last_result.max_lateness_ms?.toFixed(2) }} ms
          </span>
          <span>
            迟到/时钟平移: {{ store.playbackStatus.value.last_result.late_events_count ?? 0 }} /
            {{ store.playbackStatus.value.last_result.clock_shifts_count ?? 0 }}
          </span>
          <span>
            同键冲突修复:
            {{ store.playbackStatus.value.last_result.retrigger_conflicts_count ?? 0 }}
          </span>
        </div>

        <div class="banner-info">
          <StudioIcon name="shield" :size="15" />
          <span>
            安全边界：不读取或修改游戏内存，不注入进程，仅在用户显式点击两段确认后发送受控按键；切窗失焦或按 Esc 立即停止。
          </span>
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
          <div class="timing-controls-body">
            <label class="checkbox-row">
              <input v-model="store.realtime.value" type="checkbox" />
              按真实演奏时间间隔发送事件（测试可取消勾选加快 Dry-Run）
            </label>
            <div class="field">
              <label for="playback-late-policy">延迟事件策略</label>
              <select id="playback-late-policy" v-model="store.lateEventPolicy.value">
                <option value="shift_clock">平移时间轴（避免迟到音符堆成一团和弦）</option>
                <option value="drop_late">丢弃严重滞后音符（保持节拍准点）</option>
                <option value="catch_up">追赶补发（严格按绝对时钟）</option>
              </select>
            </div>
            <div class="row">
              <div class="field">
                <label for="playback-release-gap">同键释放间隙 (ms)</label>
                <input
                  id="playback-release-gap"
                  v-model="store.minKeyReleaseGapInput.value"
                  type="text"
                  inputmode="numeric"
                  placeholder="默认 20 ms（暂定待实测）"
                />
              </div>
              <div class="field">
                <label for="playback-key-hold">最小按住覆盖 (ms)</label>
                <input
                  id="playback-key-hold"
                  v-model="store.keyHoldMsInput.value"
                  type="text"
                  inputmode="numeric"
                  placeholder="沿用编曲默认值"
                />
              </div>
            </div>
          </div>
        </details>

        <details class="advanced-box">
          <summary>乐器基准与实机校准（Benchmark A–G）</summary>
          <div class="timing-controls-body">
            <p class="hint">
              Dry-Run / 调度测试仅验证事件时序与无重叠输出；是否真正发声请切到游戏后录制 WAV 并上传分析。
            </p>
            <div class="field">
              <label for="calibration-pattern-select">测试序列</label>
              <select
                id="calibration-pattern-select"
                v-model="store.selectedCalibrationPatternId.value"
              >
                <option
                  v-for="pat in store.calibrationPatterns.value"
                  :key="pat.id"
                  :value="pat.id"
                >
                  {{ pat.display_name }}
                </option>
                <option
                  v-if="store.calibrationPatterns.value.length === 0"
                  value="same_key_retrigger"
                >
                  B · 同键重复触发（30–150 ms 阶梯）
                </option>
              </select>
            </div>
            <div class="row">
              <button
                class="secondary btn-sm"
                :disabled="store.busy.value"
                @click="store.handleRunDryCalibration"
              >
                运行调度基准
              </button>
              <button
                class="secondary btn-sm"
                :disabled="store.busy.value"
                @click="store.handlePrepareCalibration"
              >
                准备实机校准序列
              </button>
            </div>
            <div class="field">
              <label for="calibration-wav-file">上传游戏实录 WAV（起音 / 余音检验）</label>
              <input
                id="calibration-wav-file"
                type="file"
                accept=".wav,audio/wav"
                :disabled="store.busy.value"
                @change="store.handleCalibrationWavChange"
              />
            </div>
            <div v-if="store.calibrationDryResult.value" class="calibration-result tabular">
              <div>
                层级：{{ store.calibrationDryResult.value.tier }}（游戏发声已验证：{{
                  store.calibrationDryResult.value.verifies_game_audio ? "是" : "否"
                }}）
              </div>
              <div>
                漂移 {{ store.calibrationDryResult.value.drift_ms }} ms / CPU
                {{ store.calibrationDryResult.value.cpu_pct }}% / 重叠按键
                {{ store.calibrationDryResult.value.log_verification.overlapping_key_downs }} / 最小间隙
                {{
                  store.calibrationDryResult.value.log_verification.min_observed_release_gap_ms ??
                  "N/A"
                }}
                ms
              </div>
            </div>
            <div v-if="store.calibrationAnalyzeResult.value" class="calibration-result tabular">
              <div>
                检出起音：{{ store.calibrationAnalyzeResult.value.matched_onsets }} /
                {{ store.calibrationAnalyzeResult.value.expected_onset_clusters }}（{{
                  Math.round(store.calibrationAnalyzeResult.value.detection_rate * 100)
                }}%）
              </div>
              <div>
                估计偏移 {{ store.calibrationAnalyzeResult.value.estimated_offset_ms }} ms / 平均误差
                {{ store.calibrationAnalyzeResult.value.mean_abs_error_ms ?? "N/A" }} ms
              </div>
              <div class="hint">
                建议参数：{{ JSON.stringify(store.calibrationAnalyzeResult.value.suggested_timing) }}
              </div>
            </div>
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
            <StudioIcon name="play" :size="14" />
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
            <StudioIcon name="stop" :size="14" />
            紧急停止
          </button>
        </div>

        <div v-if="store.prepared.value" class="banner-warn">
          <StudioIcon name="alert" :size="15" />
          <div style="display: flex; flex-direction: column; gap: var(--space-2xs)">
            <strong>请核对演奏风险提示</strong>
            <span>{{ store.prepared.value.risk_notice }}</span>
            <div class="meta-row">
              <span>模式：{{ store.prepared.value.mode }}</span>
              <span>预计 {{ store.prepared.value.event_count }} 个事件</span>
            </div>
            <span class="muted" style="font-size: 12px">
              开始后会先进入「等待游戏窗口」，请在 10 秒内切到《原神》；检测到游戏前置且权限一致后才会发送按键。
            </span>
          </div>
        </div>

        <div
          v-if="store.playbackStatus.value?.state === 'waiting_focus'"
          class="banner-info"
        >
          <StudioIcon name="alert" :size="15" />
          <span>
            正在等待《原神》窗口获得前台，请切换到游戏；若超时会提示当前前台窗口并自动停止。
          </span>
        </div>

        <div
          v-if="store.playbackStatus.value?.state === 'permission_required'"
          class="banner-error"
        >
          <StudioIcon name="alert" :size="15" />
          <div style="display: flex; flex-direction: column; gap: var(--space-xs)">
            <span>
              {{ store.playbackStatus.value.last_result?.error ?? "权限不足：请以管理员身份重启 LyraForge。" }}
            </span>
            <div>
              <button class="secondary btn-sm" type="button" @click="store.handleRelaunchElevated">
                以管理员身份重启 LyraForge
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.playback-left-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  min-inline-size: 0;
}
</style>
