<template>
  <div v-if="open" class="drawer-mask" @click.self="$emit('close')">
    <aside class="drawer">
      <header>
        <h2>设置</h2>
        <button class="btn icon" @click="$emit('close')">×</button>
      </header>

      <section class="setting-block">
        <h3>背景图片</h3>
        <p>直接选择本机图片，保存后会应用到当前界面。</p>
        <label class="file-picker" :class="{ 'has-image': previewImage }">
          <input type="file" accept="image/*" @change="selectBackgroundFile" />
          <span v-if="previewImage" class="file-preview" :style="{ backgroundImage: `url(${previewImage})` }"></span>
          <span class="file-copy">
            <strong>{{ selectedFileName || "选择背景图片" }}</strong>
            <small>支持 jpg、png、webp，建议小于 2MB。</small>
          </span>
        </label>
        <p v-if="localError" class="setting-error">{{ localError }}</p>
        <button v-if="draft.image_path" class="text-action" @click="clearImage">移除自定义图片</button>
        <div class="setting-row">
          <label>模糊度 <input v-model.number="draft.blur" type="range" min="0" max="40" /></label>
          <label>遮罩透明度 <input v-model.number="draft.opacity" type="range" min="0.2" max="0.95" step="0.05" /></label>
        </div>
      </section>

      <section class="setting-block">
        <h3>预设背景</h3>
        <div class="theme-row">
          <button class="swatch one" @click="selectPreset('aurora')"></button>
          <button class="swatch two" @click="selectPreset('night')"></button>
          <button class="swatch three" @click="selectPreset('mint')"></button>
          <button class="swatch four" @click="selectPreset('sunset')"></button>
        </div>
      </section>

      <footer>
        <button class="btn" @click="$emit('close')">取消</button>
        <button class="btn primary" @click="save">保存设置</button>
      </footer>
    </aside>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { captureStore as store } from "../stores/captureStore";

const props = defineProps({ open: Boolean });
const emit = defineEmits(["close", "save"]);
const draft = reactive({ ...store.background });
const selectedFileName = ref("");
const localError = ref("");
const maxImageSize = 2 * 1024 * 1024;

const previewImage = computed(() => (draft.mode === "image" ? draft.image_path : ""));

watch(
  () => props.open,
  () => {
    Object.assign(draft, store.background);
    selectedFileName.value = "";
    localError.value = "";
  },
);

function selectBackgroundFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    localError.value = "请选择图片文件。";
    return;
  }
  if (file.size > maxImageSize) {
    localError.value = "图片超过 2MB，请选择更轻量的背景图。";
    event.target.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    draft.image_path = String(reader.result || "");
    draft.mode = "image";
    selectedFileName.value = file.name;
    localError.value = "";
  };
  reader.onerror = () => {
    localError.value = "图片读取失败，请重新选择。";
  };
  reader.readAsDataURL(file);
}

function clearImage() {
  draft.image_path = "";
  draft.mode = "preset";
  selectedFileName.value = "";
}

function selectPreset(preset) {
  draft.preset = preset;
  draft.mode = "preset";
  draft.image_path = "";
  selectedFileName.value = "";
}

function save() {
  if (localError.value) return;
  emit("save", { ...draft, mode: draft.image_path ? "image" : draft.mode });
}
</script>
