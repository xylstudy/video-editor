import React, { useMemo } from "react";
import {
  AbsoluteFill, Img, OffthreadVideo, interpolate, spring, useCurrentFrame,
  useVideoConfig, Easing,
} from "remotion";

interface ForegroundLayerProps {
  bgImage: string;
  fgImage: string;
  compositeMode: "fg_overlay" | "fg_reveal" | "pip";
  durationInFrames: number;
}

const isVideoSource = (src: string) => /\.(mp4|mov|webm|mkv|avi)(?:[?#].*)?$/i.test(src);

const MediaLayer: React.FC<{
  src: string;
  style: React.CSSProperties;
}> = ({ src, style }) => isVideoSource(src)
  ? <OffthreadVideo src={src} muted style={style} />
  : <Img src={src} style={style} />;

/**
 * 前景/背景合成组件。
 *
 * 三种合成模式：
 * - fg_overlay: 前景直接叠加在背景上（半透明居中）
 * - fg_reveal: 前景以揭示动画出现（淡入 + 轻微上浮）
 * - pip: 画中画（前景缩小到右下角）
 */
export const ForegroundLayer: React.FC<ForegroundLayerProps> = ({
  bgImage,
  fgImage,
  compositeMode,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = useMemo(
    () => interpolate(frame, [0, durationInFrames], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.25, 0.1, 0.25, 1),
    }),
    [frame, durationInFrames],
  );

  // fg_reveal: 淡入 + 上浮
  const revealOpacity = compositeMode === "fg_reveal"
    ? interpolate(progress, [0, 0.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;

  const revealTranslateY = compositeMode === "fg_reveal"
    ? interpolate(progress, [0, 0.2], [60, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 0;

  // pip: 缩小到右下 1/3
  const pipScale = compositeMode === "pip" ? 0.33 : 1;
  const pipX = compositeMode === "pip" ? "W-w-20" : "(W-w)/2";
  const pipY = compositeMode === "pip" ? "H-h-20" : "(H-h)/2";

  // fg_overlay: 居中半透明
  const overlayOpacity = compositeMode === "fg_overlay" ? 0.85 : 1;

  return (
    <AbsoluteFill>
      {/* 背景 */}
      <AbsoluteFill>
        <MediaLayer
          src={bgImage}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
        />
      </AbsoluteFill>

      {/* 前景 — 居中/画中画 */}
      <AbsoluteFill
        style={{
          justifyContent: compositeMode === "pip" ? "flex-end" : "center",
          alignItems: compositeMode === "pip" ? "flex-end" : "center",
          opacity: overlayOpacity,
        }}
      >
        <div
          style={{
            width: compositeMode === "pip" ? "33%" : "80%",
            maxWidth: compositeMode === "pip" ? 360 : "100%",
            overflow: "hidden",
            borderRadius: compositeMode === "pip" ? 12 : 0,
            boxShadow: compositeMode === "pip"
              ? "0 4px 24px rgba(0,0,0,0.5)"
              : undefined,
            opacity: revealOpacity,
            transform: `translateY(${revealTranslateY}px)`,
          }}
        >
          <MediaLayer
            src={fgImage}
            style={{
              width: "100%",
              height: compositeMode === "pip" ? "auto" : "100%",
              objectFit: "cover",
              display: "block",
            }}
          />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
