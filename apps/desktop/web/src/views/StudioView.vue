<script setup lang="ts">
import { computed } from "vue";
import LyreKeyboard from "../components/LyreKeyboard.vue";
import PianoRollEditor from "../components/PianoRollEditor.vue";
import StudioIcon from "../components/StudioIcon.vue";
import { arrangementTitle, type LyraStore } from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

const STYLES: Array<{ id: "melody" | "balanced" | "rich"; label: string }> = [
  { id: "melody", label: "主旋律" },
  { id: "balanced", label: "均衡" },
  { id: "rich", label: "丰满" },
];

const currentArr = computed(() => props.store.arrDetail.value?.arrangement ?? null);

const profilePresets = computed(() =>
  props.store.presets.value.filter(
    (preset) => preset.profile_id === props.store.selectedProfileId.value,
  ),
);

async function onArrangementChange(event: Event): Promise<void> {
  const arrId = (event.target as HTMLSelectElement).value;
  await props.store.selectArrangement(arrId);
}
</script>

<template>
  <section class="view-stack" aria-label="编曲工作室与 Piano Roll">
    <header class="view-header">
      <div>
        <h1 class="view-title">编曲工作室 & Piano Roll</h1>
        <p class="view-subtitle">
          针对原神自由演奏乐器调音域、生成 A/B 对比并在 Piano Roll 直接拖拽精修音符。
        </p>
      </div>
      <div class="button-row">
        <button
          class="secondary"
          type="button"
          :disabled="!store.selectedArrId.value || store.busy.value"
          @click="store.handlePreview"
        >
          <StudioIcon name="play" />
          试听当前版本
        </button>
        <button
          class="secondary"
          type="button"
          :disabled="!store.arrDetail.value"
          @click="store.setView('playback')"
        >
          <StudioIcon name="sliders" />
          前往试听与演奏
        </button>
      </div>
    </header>

    <div class="card">
      <div class="field" style="margin-block-end: var(--space-3)">
        <label>一键预设（内置离线，按当前乐器）</label>
        <div class="button-row" style="flex-wrap: wrap; gap: 8px">
          <button
            v-for="preset in profilePresets"
            :key="preset.id"
            class="secondary"
            type="button"
            :title="preset.description"
            @click="store.applyPreset(preset.id)"
          >
            {{ preset.name }}
          </button>
        </div>
        <span class="muted">
          点击后自动套用风格 / 移调 / 琶音 / 速度，再点「生成编曲」即可。
        </span>
      </div>

      <div class="row">
        <div class="field" style="flex: 1 1 210px">
          <label for="profile-select">目标原神乐器</label>
          <select
            id="profile-select"
            v-model="store.selectedProfileId.value"
            @change="store.handleProfileChange"
          >
            <option v-for="p in store.profiles.value" :key="p.id" :value="p.id">
              {{ p.display_name }}（{{ p.key_count }} 键）
            </option>
          </select>
        </div>

        <div class="field">
          <label id="studio-style-label">编曲风格</label>
          <div class="segmented" role="group" aria-labelledby="studio-style-label">
            <button
              v-for="item in STYLES"
              :key="item.id"
              type="button"
              :class="{ active: store.style.value === item.id }"
              @click="store.style.value = item.id"
            >
              {{ item.label }}
            </button>
          </div>
        </div>

        <div class="button-row" style="margin-inline-start: auto">
          <button
            class="secondary"
            type="button"
            :disabled="!store.selectedArrId.value || store.busy.value"
            @click="store.handleAddToQueue"
          >
            <StudioIcon name="music" />
            加入播放队列
          </button>
          <button
            class="primary"
            type="button"
            :disabled="!store.canArrange.value || store.busy.value"
            @click="store.handleArrange"
          >
            <StudioIcon name="sliders" />
            生成改编版本
          </button>
          <button
            class="secondary"
            type="button"
            :disabled="!store.canArrange.value || store.busy.value"
            @click="store.handleArrangeAB"
          >
            生成 A/B 对比版本
          </button>
        </div>
      </div>

      <details class="advanced-box">
        <summary>高级编曲参数（移调 · 播放倍速 · 和弦琶音错峰）</summary>
        <div class="row" style="margin-block-start: var(--space-3)">
          <div class="field" style="flex: 1 1 130px">
            <label for="studio-transpose">移调半音（auto 或整数）</label>
            <input id="studio-transpose" v-model="store.transposeInput.value" type="text" />
          </div>
          <div class="field" style="flex: 1 1 130px">
            <label for="studio-speed">速度倍率</label>
            <input
              id="studio-speed"
              v-model.number="store.speed.value"
              type="number"
              min="0.5"
              max="2.0"
              step="0.05"
            />
          </div>
          <div class="field" style="flex: 1 1 150px">
            <label for="studio-arp">和弦错峰（0–60 ms）</label>
            <input
              id="studio-arp"
              v-model.number="store.arpeggiateMs.value"
              type="number"
              min="0"
              max="60"
              step="5"
            />
          </div>
        </div>
      </details>

      <div v-if="store.arrangements.value.length > 0" class="row">
        <div class="field" style="flex: 1 1 250px">
          <label for="studio-arr-select">已保存版本</label>
          <select
            id="studio-arr-select"
            :value="store.selectedArrId.value"
            @change="onArrangementChange"
          >
            <option v-for="a in store.arrangements.value" :key="a.id" :value="a.id">
              {{ arrangementTitle(a) }}（{{ a.event_count }} 音 · {{ a.profile_id }}）
            </option>
          </select>
        </div>

        <div v-if="currentArr" class="button-row">
          <button
            type="button"
            :class="currentArr.is_favorite ? 'active-pill' : 'secondary'"
            @click="store.handleToggleFavorite"
          >
            <StudioIcon name="star" :size="14" />
            {{ currentArr.is_favorite ? "已收藏" : "收藏" }}
          </button>
          <button
            type="button"
            :class="currentArr.user_vote === 1 ? 'active-pill' : 'ghost'"
            @click="store.handleVote(1)"
          >
            推荐 (+1)
          </button>
          <button
            type="button"
            :class="currentArr.user_vote === -1 ? 'active-pill' : 'ghost'"
            @click="store.handleVote(-1)"
          >
            降权 (-1)
          </button>
        </div>
      </div>

      <div v-if="currentArr && store.arrDetail.value" class="quality-strip">
        <span>
          <strong>编曲适配分 (相对输入 MIDI)：</strong>
          {{
            (
              store.arrDetail.value.report?.quality?.overall_score ??
              currentArr.playable_ratio * 100
            ).toFixed(1)
          }} / 100
        </span>
        <span v-if="store.arrDetail.value.report?.quality">
          主旋律保留：{{ Math.round(store.arrDetail.value.report.quality.melody_preservation * 100) }}%
        </span>
        <span v-if="store.arrDetail.value.report?.quality">
          节奏保真：{{ Math.round(store.arrDetail.value.report.quality.rhythmic_fidelity * 100) }}%
        </span>
        <span v-if="store.arrDetail.value.report?.stats">
          折半八度：{{ store.arrDetail.value.report.stats.octave_folded }}
        </span>
        <span v-if="store.arrDetail.value.report?.stats">
          邻音代偿：{{ store.arrDetail.value.report.stats.semitone_substituted }}
        </span>
        <span>事件：{{ currentArr.event_count }} 音</span>
        <span class="muted">
          说明：此分数衡量相对输入 MIDI 的原神 21 键可演奏性，不等同于音频转谱识别准确率。
        </span>
      </div>
    </div>

    <div v-if="store.comparisonResult.value" class="card">
      <div class="card-title-row">
        <h2>A/B 编曲对比结果</h2>
        <span class="pill pill-ok">推荐胜出：{{ store.comparisonResult.value.winner }}</span>
      </div>
      <p class="muted" style="margin: 0">{{ store.comparisonResult.value.summary }}</p>
    </div>

    <div class="card">
      <div class="card-title-row">
        <h2>MIDI Piano Roll 可视化编辑器</h2>
        <span v-if="store.arrDetail.value" class="pill tabular">
          {{ store.arrDetail.value.performance.events.length }} 演奏事件
        </span>
      </div>

      <PianoRollEditor
        v-if="store.arrDetail.value && store.profile.value"
        :keys="store.profile.value.keys"
        :events="store.arrDetail.value.performance.events"
        :saving="store.busy.value"
        @save="store.handleSaveEdited"
      />
      <div v-else class="empty-state">
        <p style="margin: 0">
          当前曲目尚无改编版本。请先点击上方“生成改编版本”或“生成 A/B 对比版本”。
        </p>
      </div>
    </div>

    <details class="advanced-box" open>
      <summary>原神 21 键键位热力图预览（{{ store.profile.value?.display_name ?? "未加载" }}）</summary>
      <div style="margin-block-start: var(--space-3)">
        <LyreKeyboard
          v-if="store.profile.value"
          :keys="store.profile.value.keys"
          :event-counts="store.eventCounts.value"
        />
      </div>
    </details>
  </section>
</template>
