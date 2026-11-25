<script setup lang="ts">
import LyreKeyboard from "../components/LyreKeyboard.vue";
import StudioIcon from "../components/StudioIcon.vue";
import {
  PLAYBACK_TIMING_PRESETS,
  arrangementTitle,
  type LyraStore,
  type PlaybackTimingPreset,
} from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

function profileDisplayName(profileId: string): string {
  return (
    props.store.profiles.value.find((p) => p.id === profileId)?.display_name ?? profileId
  );
}

async function onSongSelectChange(event: Event): Promise<void> {
  const songId = (event.target as HTMLSelectElement).value;
  if (songId) {
    await props.store.selectSong(songId);
  }
}

async function onArrangementSelectChange(event: Event): Promise<void> {
  const arrId = (event.target as HTMLSelectElement).value;
  await props.store.selectArrangement(arrId);
}

function isTimingPresetActive(preset: PlaybackTimingPreset): boolean {
  return (
    props.store.minKeyReleaseGapInput.value.trim() === preset.releaseGapMs &&
    props.store.keyHoldMsInput.value.trim() === preset.keyHoldMs &&
    props.store.lateEventPolicy.value === preset.latePolicy
  );
}
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
            <h2>当前演奏曲谱与 21 键舞台</h2>
            <span v-if="store.arrDetail.value" class="pill">
              {{ arrangementTitle(store.arrDetail.value.arrangement) }}
            </span>
          </div>

          <div v-if="store.allSongs.value.length > 0" class="playback-selector-grid">
            <div class="field">
              <label for="playback-song-select">选择曲目</label>
              <select
                id="playback-song-select"
                :value="store.selectedSongId.value ?? ''"
                @change="onSongSelectChange"
              >
                <option v-for="s in store.allSongs.value" :key="s.id" :value="s.id">
                  {{ s.title }}（{{ s.arrangement_count }} 版）
                </option>
              </select>
            </div>
            <div v-if="store.arrangements.value.length > 0" class="field">
              <label for="playback-arr-select">选择编曲版本</label>
              <select
                id="playback-arr-select"
                :value="store.selectedArrId.value"
                @change="onArrangementSelectChange"
              >
                <option v-for="a in store.arrangements.value" :key="a.id" :value="a.id">
                  {{ arrangementTitle(a) }}（{{ a.event_count }} 音 · {{ profileDisplayName(a.profile_id) }}）
                </option>
              </select>
            </div>
          </div>

          <div class="button-row">
            <button
              v-if="store.selectedArrId.value"
              class="secondary btn-sm"
              type="button"
              :disabled="store.busy.value"
              @click="store.handleAddToQueue"
            >
              <StudioIcon name="list-music" :size="13" />
              加入播放队列
            </button>
            <button
              class="ghost btn-sm"
              type="button"
              @click="store.setView('studio')"
            >
              <StudioIcon name="sliders" :size="13" />
              前往编曲工作室调整谱面
            </button>
          </div>

          <div v-if="store.arrangements.value.length === 0" class="empty-state">
            <p style="margin: 0">
              当前曲目还没有可演奏的编曲版本，请先在「编曲工作室」生成版本。
            </p>
            <button class="primary btn-sm" type="button" @click="store.setView('studio')">
              前往编曲工作室生成
            </button>
          </div>

          <LyreKeyboard
            v-else-if="store.profile.value"
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

        <div class="section-block">
          <div class="pane-header">
            <h3 class="subsection-heading">演奏节奏与防吞音设置</h3>
            <button
              id="playback-quick-check-btn"
              class="secondary btn-sm"
              type="button"
              :disabled="store.busy.value"
              @click="store.handleQuickTimingCheck"
            >
              一键本机调度检测（无需录音）
            </button>
          </div>

          <p class="muted" style="margin: 0; font-size: 12px">
            直接选择符合你电脑和曲风的按键参数；若游戏内发现漏音或慢半拍，点击检测或切换预设即可。
          </p>

          <div class="timing-preset-grid" role="group" aria-label="演奏防吞音场景预设">
            <button
              v-for="preset in PLAYBACK_TIMING_PRESETS"
              :key="preset.id"
              type="button"
              class="timing-preset-btn"
              :class="{ 'is-active': isTimingPresetActive(preset) }"
              @click="store.applyPlaybackTimingPreset(preset.id)"
            >
              <strong>{{ preset.name }}</strong>
              <span class="timing-preset-desc">{{ preset.summary }}</span>
            </button>
          </div>

          <div v-if="store.playbackTimingAdvice.value" class="timing-check-card">
            <div class="pane-header">
              <strong>{{ store.playbackTimingAdvice.value.headline }}</strong>
              <span
                class="pill"
                :class="
                  store.playbackTimingAdvice.value.tier === 'excellent'
                    ? 'pill-ok'
                    : store.playbackTimingAdvice.value.tier === 'jittery'
                      ? 'pill-warn'
                      : ''
                "
              >
                P95 {{ store.playbackTimingAdvice.value.p95Ms }} ms · Max
                {{ store.playbackTimingAdvice.value.maxMs }} ms
              </span>
            </div>
            <p class="muted" style="margin: 0; font-size: 12px">
              {{ store.playbackTimingAdvice.value.detail }}
            </p>
            <div class="button-row">
              <button
                id="playback-apply-recommended-btn"
                type="button"
                class="primary btn-sm"
                @click="store.applyRecommendedTimingAdvice"
              >
                一键应用推荐参数（{{ store.playbackTimingAdvice.value.recommendedPresetName }}）
              </button>
            </div>
          </div>

          <details class="advanced-box" open>
            <summary>微调节拍与防吞音参数</summary>
            <div class="timing-controls-body">
              <label class="checkbox-row">
                <input v-model="store.realtime.value" type="checkbox" />
                按真实演奏时间间隔发送事件（快速调试时可取消勾选）
              </label>
              <div class="field">
                <label for="playback-late-policy">遇到卡顿迟到音符时</label>
                <select id="playback-late-policy" v-model="store.lateEventPolicy.value">
                  <option value="shift_clock">平移时间轴（避免迟到音符堆成一团和弦）</option>
                  <option value="drop_late">丢弃严重滞后音符（保持节拍准点）</option>
                  <option value="catch_up">追赶补发（严格按绝对时钟）</option>
                </select>
              </div>
              <div class="row">
                <div class="field">
                  <label for="playback-release-gap">同键连击释放间隙 (ms)</label>
                  <input
                    id="playback-release-gap"
                    v-model="store.minKeyReleaseGapInput.value"
                    type="text"
                    inputmode="numeric"
                    placeholder="默认 20 ms"
                  />
                </div>
                <div class="field">
                  <label for="playback-key-hold">按键按住时长覆盖 (ms)</label>
                  <input
                    id="playback-key-hold"
                    v-model="store.keyHoldMsInput.value"
                    type="text"
                    inputmode="numeric"
                    placeholder="留空沿用编曲默认"
                  />
                </div>
              </div>
            </div>
          </details>

          <ul class="timing-guide-list">
            <li>同一按键连续快敲漏音 → 调大「同键连击释放间隙」（推荐 25–35 ms）</li>
            <li>偶发单个音符完全不响 → 适当调大「按键按住时长」（推荐 25–35 ms）</li>
            <li>窗口掉帧后突然挤出一团乱音 → 保持「平移时间轴」或选「严格卡拍」</li>
          </ul>
        </div>

        <details class="advanced-box">
          <summary>开发者实录波形分析（高级可选，日常演奏无需录音）</summary>
          <div class="timing-controls-body">
            <p class="hint">
              仅当你想做精度测量或提交反馈时使用：可用基准序列生成实录测试曲并分析游戏实录 WAV。
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
