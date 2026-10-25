// 与 Python 模型对齐的 TypeScript 类型定义

export type ShotType =
  | "hook"
  | "cta"
  | "transition"
  | "scene_establish"
  | "daily_moment"
  | "emotion_peak"
  | "persona"
  | "info_card"
  | "closing"
  | "pain_point"
  | "product"
  | "usage"
  | "comparison";

export type TransitionType =
  | "cut"
  | "fade"
  | "dissolve"
  | "zoom_in"
  | "zoom_out"
  | "flash_white"
  | "flash_black"
  | "slide"
  | "slide_left"
  | "slide_right"
  | "slide_up"
  | "slide_down"
  | "wipe_left"
  | "wipe_right"
  | "wipe_up"
  | "wipe_down"
  | "slice_wipe"
  | "blur_in"
  | "rotate_in"
  | "whip"
  | "mask"
  | "circle_reveal"
  | "zoom_flash"
  | "glitch"
  | "spin"
  | "zoom_heavy"
  | "light_leak"
  | "freeze_frame"
  | "flip_3d"
  | "radial_wipe"
  | "zoom_through"
  | "liquid_warp"
  | "chromatic_aberration"
  | "none";

/** 单个分镜的渲染层 */
export interface FrameLayerConfig {
  type: "video" | "image" | "text" | "shape" | "gradient" | "custom";
  material_id?: string;
  content?: string;
  style?: Record<string, unknown>;
  animation?: Record<string, unknown>;
  // 裁切/缩放
  crop?: { x: number; y: number; width: number; height: number };
  scale?: number;
  opacity?: number;
  position?: { x: number; y: number };
}

export interface FFmpegSegment {
  trim_start?: number;
  trim_end?: number;
  speed?: number;
  reverse?: boolean;
  crop?: string;       // FFmpeg crop filter 表达式
  filter?: string;     // 自定义 filter
}

export interface StoryboardFrame {
  index: number;
  shot_type: ShotType;
  duration: number;
  start_time?: number;
  end_time?: number;
  purpose?: string;
  source_material_id?: string;
  material_id?: string;
  is_generated?: boolean;
  fill_strategy?: string;
  visual_description?: string;
  visual_content?: string;
  subtitle_text?: string;
  voiceover_text?: string;
  text_card_content?: string;
  text_card_style?: Record<string, unknown>;
  text_card_config?: Record<string, unknown>;
  transition_in?: TransitionType;
  transition?: TransitionType;
  emotion?: string;
  camera_movement?: string;
  shot_size?: string;
  composition?: string;
  has_face?: boolean;
  bgm_sync?: boolean;
  motion_effect?: string;
  ken_burns_config?: KenBurnsConfig;
  speed_change?: number;

  // ===== 前景/背景合成 =====
  fg_source_id?: string;
  bg_source_id?: string;
  composite_mode?: "none" | "fg_overlay" | "fg_reveal" | "pip";

  // ===== 每分镜字幕配置 =====
  subtitle_config?: {
    fontSize?: number;
    verticalAlign?: "bottom" | "top" | "center";
    color?: string;
    textAlign?: "left" | "center" | "right";
    marginFromEdge?: number;
    offsetX?: number;
    animation?: "fade_in" | "typewriter" | "scale_up" | "none";
    [key: string]: unknown;
  };

  // ===== 扩展：渲染控制 =====
  render_component?: string;
  custom_render_config?: Record<string, unknown>;
  layers?: FrameLayerConfig[];
  canvas_width?: number;
  canvas_height?: number;

  // ===== FFmpeg 粗剪 =====
  ffmpeg_segment?: FFmpegSegment;
  effect_event_ids?: string[];
  effect_mapping?: Record<
    string,
    { status?: "mapped" | "degraded" | "unresolved"; component?: string; reason?: string }
  >;
}

export interface KenBurnsConfig {
  motion_type?: "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "focus_scan";
  speed?: "slow" | "medium" | "fast";
  focus_on_face?: boolean;
}

export interface SubtitleStyle {
  font_family?: string;
  font_size?: number;
  color?: string;
  stroke_color?: string;
  position?: "bottom" | "center" | "top";
  animation?: "none" | "fade_in" | "typewriter" | "bounce" | "slide_in";
  typing_speed?: number;
  max_chars_per_line?: number;
  background_style?: string;
}

export interface PackagingStyle {
  subtitle_style?: SubtitleStyle;
  title_card_style?: string;
  text_card_background?: string;
  text_card_font?: string;
  preferred_transitions?: string[];
  transition_frequency?: "sparse" | "moderate" | "frequent";
  color_grade?: string;
  filter_style?: string;
  visual_mood?: string;
  default_ken_burns?: string;
}

export interface BGMInfo {
  style?: string;
  bpm?: number;
  mood?: string;
  beat_points?: number[];
  key_transitions?: Array<{ time: number; intensity: number }>;
  role?: "background" | "emphasis" | "transition";
  audio_path?: string;
  volume?: number;
  // 音频裁切（帧单位）
  trim_before?: number;
  trim_after?: number;
  loop?: boolean;
}

export interface AudioConfig {
  source?: "reference" | "custom" | "none";
  volume?: number;
  loop?: boolean;
  trim_before?: number;
  trim_after?: number | null;
  fade_frames?: number;
  original_audio_mode?: "mute" | "selected" | "all";
  normalize?: boolean;
  target_lufs?: number;
  true_peak?: number;
}

export interface VideoScheme {
  id: string;
  title: string;
  target_topic: string;
  target_duration: number;
  structure_type: string;
  narrative_type?: string;
  hook_strategy?: string;
  overall_emotion?: string;
  storyboard: StoryboardFrame[];
  effect_tracks?: Array<{
    start: number;
    end: number;
    type: string;
    component?: string;
    priority?: string;
    parameters?: Record<string, unknown>;
  }>;
  packaging?: PackagingStyle;
  bgm?: BGMInfo;
  audio_source_id?: string;
  audio_config?: AudioConfig;
  script_blocks?: Array<{
    index: number;
    purpose: string;
    shot_range: string;
    content_summary: string;
    duration_hint: number;
    emotion: string;
    rhythm: "快" | "中" | "慢";
  }>;
  total_duration: number;

  // ===== 扩展 =====
  canvas_width?: number;
  canvas_height?: number;
  render_pipeline?: "remotion" | "ffmpeg" | "hybrid";
  render_hints?: Record<string, unknown>;
  ffmpeg_timeline?: Record<string, unknown>[];
}

// 素材路径映射
export interface MaterialMap {
  [materialId: string]: string;
}

// Remotion inputProps
export interface RenderInput {
  scheme: VideoScheme;
  material_map: MaterialMap;
  output_path?: string;
}
