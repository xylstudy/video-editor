import React, { useMemo } from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import type { RenderInput, StoryboardFrame } from "./types/schema";
import { FrameLayer } from "./components/FrameLayer";
import { DualTransitionLayer, getRequiredOverlap } from "./components/DualTransitions";
import { AudioLayer } from "./components/AudioLayer";
import { ReferenceEffectTracks } from "./components/ReferenceEffects";

/** 预加载时长（秒）—— 确保素材提前加载，避免掉帧 */
const PREMOUNT_SECONDS = 1;

/**
 * 主合成组件：按方案 storyboard 编排所有分镜。
 *
 * 架构：双层过渡架构
 * - 首个分镜：无出画内容，仅做入场动效
 * - 后续分镜：开头 overlap 帧做双层过渡（出画 + 入画 + 覆盖层）
 * - 稳定期：仅入画内容
 *
 * 支持 30+ 种过渡效果，overlap 帧数根据过渡类型动态计算。
 */
export const VideoSchemeComposition: React.FC<RenderInput> = ({
  scheme,
  material_map,
}) => {
  const { fps } = useVideoConfig();
  const currentFrame = useCurrentFrame();
  const storyboard = scheme.storyboard ?? [];

  const premountFrames = Math.round(PREMOUNT_SECONDS * fps);

  // 预计算每个分镜的帧范围 —— 精确顺序排列
  const frameSchedule = useMemo(() => {
    const schedule: Array<{
      frame: StoryboardFrame;
      prevFrame: StoryboardFrame | null;
      startFrame: number;
      durationInFrames: number;
      transitionType: string;
      overlapFrames: number;
    }> = [];
    let cursor = 0;
    for (let i = 0; i < storyboard.length; i++) {
      const f = storyboard[i];
      const dur = Math.max(1, Math.round(f.duration * fps));
      const transitionIn = f.transition_in ?? f.transition ?? "cut";
      // 首个分镜无出画，用 0 帧重叠
      const overlap = i === 0 ? 0 : getRequiredOverlap(transitionIn as any);
      schedule.push({
        frame: f,
        prevFrame: i > 0 ? storyboard[i - 1] : null,
        startFrame: cursor,
        durationInFrames: dur,
        transitionType: transitionIn,
        overlapFrames: Math.min(overlap, dur - 1),
      });
      cursor += dur;
    }
    return schedule;
  }, [storyboard, fps]);

  // 总时长 = 所有分镜原始时长之和
  const totalDuration = useMemo(
    () => {
      if (frameSchedule.length === 0) return 30 * fps;
      const last = frameSchedule[frameSchedule.length - 1];
      return last.startFrame + last.durationInFrames;
    },
    [frameSchedule]
  );

  /** 全局 fade-out progress（最后 0.5 秒） */
  const fadeOutStart = totalDuration - Math.round(0.5 * fps);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* BGM / 音轨 — 传入 totalDuration 以支持淡出对齐音频长度 */}
      <AudioLayer bgm={{
        src: scheme.bgm?.audio_path ? (material_map?.[scheme.bgm.audio_path] ?? scheme.bgm.audio_path) : "",
        volume: scheme.audio_config?.volume ?? scheme.bgm?.volume ?? 0.3,
        loop: scheme.audio_config?.loop ?? scheme.bgm?.loop ?? true,
        trimBefore: scheme.audio_config?.trim_before ?? scheme.bgm?.trim_before ?? 0,
        trimAfter: scheme.audio_config?.trim_after ?? scheme.bgm?.trim_after ?? undefined,
        fadeFrames: scheme.audio_config?.fade_frames ?? 15,
        totalDuration,
      }} />

      {/* 逐分镜 Sequence 编排 */}
      {frameSchedule.map((item, idx) => {
        const transition = item.transitionType as any;

        return (
          <Sequence
            key={idx}
            name={`shot-${item.frame.index}`}
            from={item.startFrame}
            durationInFrames={item.durationInFrames}
            premountFor={premountFrames}
          >
            <DualTransitionLayer
              transitionType={transition}
              overlapFrames={item.overlapFrames}
              totalDurationInFrames={item.durationInFrames}
              currentContent={
                <FrameLayer
                  frame={item.frame}
                  materialMap={material_map}
                  durationInFrames={item.durationInFrames}
                />
              }
              outgoingContent={
                item.prevFrame ? (
                  <FrameLayer
                    frame={item.prevFrame}
                    materialMap={material_map}
                    durationInFrames={item.overlapFrames}
                  />
                ) : null
              }
            />
          </Sequence>
        );
      })}

      <ReferenceEffectTracks tracks={scheme.effect_tracks} />

      {/* 全局 fade out（最后 0.5 秒 -> 黑场） */}
      <AbsoluteFill
        style={{
          opacity: interpolate(
            currentFrame,
            [fadeOutStart, totalDuration],
            [0, 1],
            {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: Easing.in(Easing.cubic),
            }
          ),
          backgroundColor: "#000",
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};
