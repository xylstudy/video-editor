import React, { useMemo } from "react";
import { AbsoluteFill, OffthreadVideo } from "remotion";
import type { StoryboardFrame, MaterialMap } from "../types/schema";
import { getComponent, hasComponent, registerComponent } from "./registry";
import { TextCard } from "./TextCard";
import { KenBurns } from "./KenBurns";
import { Subtitles } from "./Subtitles";
import { ForegroundLayer } from "./ForegroundLayer";
import { TextOverlay } from "./TextOverlay";
import { FilmGrain } from "./Effects";

// 内置组件注册到注册表
registerComponent("text_card", TextCard as unknown as React.FC<Record<string, unknown>>);
registerComponent("ken_burns", KenBurns as unknown as React.FC<Record<string, unknown>>);
registerComponent("subtitles", Subtitles as unknown as React.FC<Record<string, unknown>>);

/**
 * 解析 renderer 生成的动画名（如 "slow_zoom_in"）为 KenBurns 组件所需的参数。
 * 格式: {speed}_{motionType}
 *   speed: slow / medium / fast
 *   motionType: zoom_in / zoom_out / pan_left / pan_right / focus_scan
 * 不支持的 motionType（如 pan_up）回退到 zoom_in。
 */
function parseKenBurnsAnimation(raw: string): { motionType: "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "focus_scan"; speed: "slow" | "medium" | "fast" } {
  const speedPrefixes = ["slow_", "medium_", "fast_"];
  let speed: "slow" | "medium" | "fast" = "slow";
  let motion = raw || "zoom_in";

  for (const prefix of speedPrefixes) {
    if (motion.startsWith(prefix)) {
      speed = prefix.replace("_", "") as "slow" | "medium" | "fast";
      motion = motion.slice(prefix.length);
      break;
    }
  }

  const supported = new Set(["zoom_in", "zoom_out", "pan_left", "pan_right", "focus_scan"]);
  if (!supported.has(motion)) {
    motion = "zoom_in";
  }

  return { motionType: motion as "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "focus_scan", speed };
}

interface DynamicFrameProps {
  frame: StoryboardFrame;
  materialMap: MaterialMap;
  durationInFrames: number;
}

/**
 * 动态分镜渲染器。
 *
 * 根据 frame.render_component 的值选择渲染策略：
 *   "auto"              → 智能推断（TextCard / 视频 / 图片 / KenBurns）
 *   "text_card"         → 内置 TextCard
 *   "ken_burns"         → 内置 KenBurns
 *   "custom:{name}"     → 从注册表加载自定义组件
 *   其他                → 当作注册表组件名
 */
export const DynamicFrame: React.FC<DynamicFrameProps> = ({
  frame,
  materialMap,
  durationInFrames,
}) => {
  const renderComponentName = frame.render_component ?? "auto";

  // ===== 自定义组件分支 =====
  const customComponent = useMemo(() => {
    if (renderComponentName.startsWith("custom:")) {
      const name = renderComponentName.replace("custom:", "");
      return getComponent(name) ?? null;
    }
    if (hasComponent(renderComponentName)) {
      return getComponent(renderComponentName)!;
    }
    return null;
  }, [renderComponentName]);

  if (customComponent) {
    const imagePath = getMaterialPath(frame, materialMap) ?? "";
    const foregroundPath = getFgMaterialPath(frame, materialMap) ?? "";
    const backgroundPath = getBgMaterialPath(frame, materialMap) ?? imagePath;
    const config = frame.custom_render_config ?? {};
    const configuredMaterialIds = [
      ...(Array.isArray(config.source_material_ids) ? config.source_material_ids : []),
      ...(Array.isArray(config.material_ids) ? config.material_ids : []),
      ...(frame.layers ?? []).map((layer) => layer.material_id),
    ].filter((item): item is string => typeof item === "string");
    const configuredPaths = configuredMaterialIds
      .map((id) => materialMap[id])
      .filter((item): item is string => typeof item === "string" && item.length > 0);
    const imageUrls = Array.from(
      new Set([imagePath, foregroundPath, backgroundPath, ...configuredPaths].filter(Boolean)),
    );

    // 构建传给组件的 props
    const baseProps: Record<string, unknown> = {
      frame,
      materialMap,
      durationInFrames,
      imagePath,
      imageUrls,
      images: imageUrls,
      src: imagePath,
      sourceMaterialId: imagePath,
      backgroundSourceId: backgroundPath,
      foregroundSourceId: foregroundPath || imagePath,
      subtitleText: frame.subtitle_text ?? "",
      subtitle: frame.subtitle_text ?? "",
      // visual_description is planner metadata for editors and reviewers. It
      // must not leak into the finished video as an on-screen technical note.
      text: frame.text_card_content || "",
    };

    // 对内置 ken_burns 组件，解析 LLM 生成的动画名（如 "slow_zoom_in"）
    if (renderComponentName === "ken_burns") {
      const rawAnimation = (config.animation || config.motion_type || "zoom_in") as string;
      const { motionType, speed: parsedSpeed } = parseKenBurnsAnimation(rawAnimation);
      baseProps.motionType = motionType;
      baseProps.speed = (config.speed as string) || parsedSpeed || "slow";
      baseProps.focusOnFace = config.focus_on_face ?? config.focusOnFace ?? false;
    }

    return React.createElement(customComponent, { ...config, ...baseProps });
  }

  // ===== auto 模式：按内容推断 =====
  return <AutoFrame frame={frame} materialMap={materialMap} durationInFrames={durationInFrames} />;
};

/** 提取逐分镜字幕配置，合并到 Subtitles props */
function buildSubtitleProps(
  frame: StoryboardFrame, durationInFrames: number,
): React.ComponentProps<typeof Subtitles> {
  const subCfg = frame.subtitle_config ?? {};

  return {
    text: frame.subtitle_text ?? "",
    voiceover: frame.voiceover_text ?? "",
    emotion: frame.emotion,
    durationInFrames,
    animation: (subCfg.animation as "fade_in" | "scale_up" | "none" | undefined)
      ?? (frame.custom_render_config?.subtitle_animation as "fade_in" | "scale_up" | "none")
      ?? undefined,
    fontSize: subCfg.fontSize ?? 42,
    verticalAlign: subCfg.verticalAlign as "bottom" | "top" | "center" ?? "bottom",
    color: subCfg.color ?? "#ffffff",
    textAlign: subCfg.textAlign as "left" | "center" | "right" ?? "center",
    marginFromEdge: subCfg.marginFromEdge ?? 80,
    offsetX: subCfg.offsetX ?? 0,
  };
}

/** 按 shot_type 和 emotion 智能选择 Ken Burns 参数，避免千篇一律的 slow_zoom_in */
function getSmartKenBurnsConfig(
  frame: StoryboardFrame,
  config: Record<string, unknown>,
  kbConfig: Record<string, unknown> | undefined,
): { motionType: "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "focus_scan"; speed: "slow" | "medium" | "fast" } {
  // 如果方案已指定，优先使用
  const raw = (
    config.animation
    || config.motion_type
    || kbConfig?.motion_type
    || ""
  ) as string;
  if (raw) return parseKenBurnsAnimation(raw);

  const shotType = frame.shot_type;
  const emotion = frame.emotion || "";
  const idx = frame.index;
  const dur = frame.duration || 3;

  // 短镜（<=3s）= 快节奏，制造"快切"感
  if (dur <= 3) {
    return { motionType: "zoom_in", speed: "fast" };
  }

  // 按镜头类型分配
  switch (shotType) {
    case "hook":
      return { motionType: "zoom_in", speed: "medium" };
    case "transition":
      // 轮换左右平移，制造方向感
      return { motionType: idx % 2 === 0 ? "pan_right" : "pan_left", speed: "medium" };
    case "emotion_peak":
      return { motionType: "zoom_in", speed: "slow" };
    case "info_card":
      return { motionType: "zoom_in", speed: "medium" };
    case "scene_establish":
      return { motionType: "zoom_out", speed: "slow" };
    case "daily_moment":
    default: {
      // 按 index 轮换多种运镜，让相邻镜头不同
      const motions: Array<{ motionType: "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "focus_scan"; speed: "slow" | "medium" }> = [
        { motionType: "zoom_in", speed: "slow" },
        { motionType: "pan_right", speed: "slow" },
        { motionType: "focus_scan", speed: "slow" },
        { motionType: "zoom_out", speed: "slow" },
        { motionType: "pan_left", speed: "slow" },
      ];
      return motions[idx % motions.length];
    }
  }
}

/** 按情绪决定是否叠加胶片颗粒 */
function getFilmGrain(frame: StoryboardFrame): { active: boolean; opacity: number; type: "film" | "dust" } | null {
  const emotion = frame.emotion || "";
  if (emotion.includes("温馨") || emotion.includes("治愈") || emotion.includes("怀旧")) {
    return { active: true, opacity: 0.12, type: "film" };
  }
  if (emotion.includes("震撼") || emotion.includes("感动") || emotion.includes("热血")) {
    return { active: true, opacity: 0.18, type: "film" };
  }
  if (emotion.includes("回忆") || emotion.includes("时光")) {
    return { active: true, opacity: 0.15, type: "dust" };
  }
  return null;
}
const AutoFrame: React.FC<DynamicFrameProps> = ({ frame, materialMap, durationInFrames }) => {
  const config = frame.custom_render_config ?? {};
  const subtitleProps = buildSubtitleProps(frame, durationInFrames);

  // 文字卡
  if (frame.text_card_content) {
    return (
      <AbsoluteFill style={{ width: frame.canvas_width ?? 1080, height: frame.canvas_height ?? 1920 }}>
        <TextCard
          text={frame.text_card_content}
          bgColor={(frame.text_card_style?.background_color as string) ?? "#1a1a2e"}
          textColor={(frame.text_card_style?.text_color as string) ?? "#ffffff"}
          animation={(frame.text_card_style?.animation as string) ?? "fade_in"}
          durationInFrames={durationInFrames}
        />
      </AbsoluteFill>
    );
  }

  const matPath = getMaterialPath(frame, materialMap);
  if (!matPath) {
    return (
      <AbsoluteFill style={{ width: frame.canvas_width ?? 1080, height: frame.canvas_height ?? 1920 }}>
        <TextCard
          text={frame.visual_description ?? frame.purpose ?? ""}
          bgColor="#1a1a2e"
          textColor="#ffffff"
          animation="fade_in"
          durationInFrames={durationInFrames}
        />
      </AbsoluteFill>
    );
  }

  const ext = matPath.toLowerCase().split(".").pop();
  const isVideo = ["mp4", "mov", "webm", "avi", "mkv"].includes(ext ?? "");

  // ===== 前景/背景合成分支 =====
  const compMode = frame.composite_mode ?? "none";
  const hasFg = frame.fg_source_id && compMode !== "none";
  const fgPath = hasFg ? getFgMaterialPath(frame, materialMap) : null;

  if (hasFg && fgPath) {
    const filmGrain = getFilmGrain(frame);
    return (
      <AbsoluteFill>
        <ForegroundLayer
          bgImage={matPath}
          fgImage={fgPath}
          compositeMode={compMode as "fg_overlay" | "fg_reveal" | "pip"}
          durationInFrames={durationInFrames}
        />
        {filmGrain && <FilmGrain opacity={filmGrain.opacity} type={filmGrain.type} />}
        <Subtitles {...subtitleProps} />
        <TextOverlay layers={frame.layers ?? []} durationInFrames={durationInFrames} />
      </AbsoluteFill>
    );
  }

  // ===== 普通视频/图片 =====
  if (isVideo) {
    const filmGrain = getFilmGrain(frame);
    return (
      <AbsoluteFill>
        <NativeVideoLayer path={matPath} />
        {filmGrain && <FilmGrain opacity={filmGrain.opacity} type={filmGrain.type} />}
        <Subtitles {...subtitleProps} />
        <TextOverlay layers={frame.layers ?? []} durationInFrames={durationInFrames} />
      </AbsoluteFill>
    );
  }

  // ===== 智能 Ken Burns =====
  const kbConfig = getSmartKenBurnsConfig(frame, config, frame.ken_burns_config as Record<string, unknown> | undefined);
  const filmGrain = getFilmGrain(frame);

  return (
    <AbsoluteFill>
      <KenBurns
        imagePath={matPath}
        motionType={kbConfig.motionType}
        speed={kbConfig.speed}
        focusOnFace={!!(config.focus_on_face ?? frame.ken_burns_config?.focus_on_face ?? false)}
        durationInFrames={durationInFrames}
      />
      {filmGrain && <FilmGrain opacity={filmGrain.opacity} type={filmGrain.type} />}
      <Subtitles {...subtitleProps} />
      <TextOverlay layers={frame.layers ?? []} durationInFrames={durationInFrames} />
    </AbsoluteFill>
  );
};

// ===== 内部小部件 =====

const NativeVideoLayer: React.FC<{ path: string }> = ({ path }) => (
  <OffthreadVideo muted src={path} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
);

function getMaterialPath(frame: StoryboardFrame, materialMap: MaterialMap): string | undefined {
  const mid = frame.material_id ?? frame.source_material_id;
  return mid ? materialMap[mid] : undefined;
}

/** 获取前景素材路径（优先 fg_source_id） */
function getFgMaterialPath(frame: StoryboardFrame, materialMap: MaterialMap): string | undefined {
  const mid = frame.fg_source_id;
  return mid ? materialMap[mid] : undefined;
}

/** 获取显式背景素材；没有指定时由调用方回退到主素材。 */
function getBgMaterialPath(frame: StoryboardFrame, materialMap: MaterialMap): string | undefined {
  const mid = frame.bg_source_id;
  return mid ? materialMap[mid] : undefined;
}
