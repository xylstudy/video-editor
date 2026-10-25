import React, { useMemo } from "react";
import { AbsoluteFill, Img, OffthreadVideo, interpolate, spring, useCurrentFrame, useVideoConfig, Easing } from "remotion";

interface KenBurnsProps {
  imagePath: string;
  motionType: "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "focus_scan";
  speed: "slow" | "medium" | "fast";
  focusOnFace: boolean;
  durationInFrames: number;
}

// ============================================================
//  Ken Burns 效果：在静态图上做慢速缩放/平移，让图片"活"起来。
//
//  遵循 skill 最佳实践：
//  - 使用 spring() 实现缩放（更自然的起停）
//  - 平移使用 ease-out bezier 曲线
//  - 分离 timing（progress 0→1）和 mapping（具体数值）
// ============================================================

export const KenBurns: React.FC<KenBurnsProps> = ({
  imagePath,
  motionType,
  speed,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // ---- timing ----

  /** 归一化 progress 0→1（全时长） */
  const progress = useMemo(
    () => interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.25, 0.1, 0.25, 1), // 匀速偏缓出，Ken Burns 需要平滑
    }),
    [frame, durationInFrames],
  );

  /** spring-based 缩放 progress（比线性更自然） */
  const springProgress = useMemo(
    () => spring({
      fps,
      frame: Math.min(frame, durationInFrames),
      config: { damping: 300, stiffness: 200 },
    }),
    [fps, frame, durationInFrames],
  );

  // ---- 从 progress 映射到具体属性 ----

  const maxZoom = speed === "slow" ? 1.15 : speed === "fast" ? 1.45 : 1.3;

  const zoom = motionType === "zoom_in"
    ? interpolate(springProgress, [0, 1], [1, maxZoom])
    : motionType === "zoom_out"
    ? interpolate(progress, [0, 1], [maxZoom, 1])
    : interpolate(springProgress, [0, 1], [1, maxZoom * 0.5 ? 1.1 : 1.15]);

  const maxPan = speed === "slow" ? 50 : speed === "fast" ? 150 : 100;

  let translateX = 0;
  let translateY = 0;

  switch (motionType) {
    case "pan_left":
      translateX = interpolate(progress, [0, 1], [0, -maxPan]);
      break;
    case "pan_right":
      translateX = interpolate(progress, [0, 1], [0, maxPan]);
      break;
    case "focus_scan":
      // 先拉近再缓慢扫视
      translateX = interpolate(progress, [0, 1], [0, maxPan * 0.6]);
      break;
    default:
      break;
  }

  return (
    <AbsoluteFill>
      {/\.(mp4|mov|webm|mkv|avi|m4v)(?:[?#].*)?$/i.test(imagePath) ? (
        <OffthreadVideo
          src={imagePath}
          muted
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${zoom}) translate(${translateX}px, ${translateY}px)`,
          }}
        />
      ) : (
        <Img
          src={imagePath}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${zoom}) translate(${translateX}px, ${translateY}px)`,
          }}
        />
      )}
    </AbsoluteFill>
  );
};
