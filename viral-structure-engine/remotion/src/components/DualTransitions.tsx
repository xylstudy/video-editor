import React, { ReactNode, useMemo } from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Easing,
} from "remotion";
import type { TransitionType } from "../types/schema";

// ============================================================
// 转场重叠帧数配置
// ============================================================

/** 根据转场类型返回所需的重叠帧数 */
export function getRequiredOverlap(type: TransitionType): number {
  switch (type) {
    case "cut":
    case "none":
      return 0;
    case "fade":
    case "dissolve":
      return 4;
    case "flash_white":
    case "flash_black":
      return 8;
    case "slide":
    case "slide_left":
    case "slide_right":
    case "slide_up":
    case "slide_down":
      return 10;
    case "wipe_left":
    case "wipe_right":
    case "wipe_up":
    case "wipe_down":
    case "slice_wipe":
      return 10;
    case "zoom_in":
    case "zoom_out":
      return 8;
    case "blur_in":
      return 10;
    case "rotate_in":
      return 12;
    case "whip":
      return 12;
    case "mask":
    case "circle_reveal":
      return 10;
    case "zoom_flash":
      return 10;
    case "glitch":
      return 10;
    case "spin":
      return 14;
    case "zoom_heavy":
      return 12;
    case "light_leak":
      return 14;
    case "freeze_frame":
      return 10;
    case "flip_3d":
      return 14;
    case "radial_wipe":
      return 12;
    case "zoom_through":
    case "liquid_warp":
    case "chromatic_aberration":
      return 14;
    default:
      return 6;
  }
}

// ============================================================
// 动画工具函数
// ============================================================

/** 标准 ease-out progress (0→1) */
const enterProgress = (frame: number, dur: number) =>
  interpolate(frame, [0, dur], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

/** 线性 progress */
const linearProgress = (frame: number, dur: number) =>
  interpolate(frame, [0, dur], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

// ============================================================
// 出画样式计算
// ============================================================

function getOutgoingStyle(
  type: TransitionType,
  frame: number,
  overlap: number,
): React.CSSProperties {
  const p = enterProgress(frame, overlap);
  const lp = linearProgress(frame, overlap);

  switch (type) {
    case "fade":
    case "dissolve":
      return { opacity: 1 - lp };

    case "slide":
    case "slide_left":
      return {
        transform: `translateX(${interpolate(p, [0, 1], [0, -120])}px)`,
        opacity: 1 - p,
      };
    case "slide_right":
      return {
        transform: `translateX(${interpolate(p, [0, 1], [0, 120])}px)`,
        opacity: 1 - p,
      };
    case "slide_up":
      return {
        transform: `translateY(${interpolate(p, [0, 1], [0, -120])}px)`,
        opacity: 1 - p,
      };
    case "slide_down":
      return {
        transform: `translateY(${interpolate(p, [0, 1], [0, 120])}px)`,
        opacity: 1 - p,
      };

    case "wipe_left":
      return {
        clipPath: `inset(0 ${interpolate(p, [0, 1], [0, 100])}% 0 0)`,
      };
    case "wipe_right":
      return {
        clipPath: `inset(0 0 0 ${interpolate(p, [0, 1], [0, 100])}%)`,
      };
    case "wipe_up":
      return {
        clipPath: `inset(${interpolate(p, [0, 1], [0, 100])}% 0 0 0)`,
      };
    case "wipe_down":
      return {
        clipPath: `inset(0 0 ${interpolate(p, [0, 1], [0, 100])}% 0)`,
      };

    case "zoom_in":
      return {
        transform: `scale(${interpolate(p, [0, 1], [1, 0.9])})`,
        opacity: 1 - p,
      };
    case "zoom_out":
      return {
        transform: `scale(${interpolate(p, [0, 1], [1, 1.1])})`,
        opacity: 1 - p,
      };

    case "blur_in":
      return {
        filter: `blur(${interpolate(p, [0, 1], [0, 10])}px)`,
        opacity: 1 - p,
      };
    case "rotate_in":
      return {
        transform: `rotate(${interpolate(p, [0, 1], [0, -8])}deg) scale(${interpolate(p, [0, 1], [1, 0.92])})`,
        opacity: 1 - p,
      };

    case "whip": {
      const whipP = enterProgress(frame, overlap);
      return {
        transform: `translateX(${interpolate(whipP, [0, 1], [0, -350])}px) rotate(${interpolate(whipP, [0, 1], [0, -12])}deg)`,
        filter: `blur(${interpolate(whipP, [0, 1], [0, 25])}px)`,
        opacity: 1 - whipP,
      };
    }

    case "mask":
    case "circle_reveal":
      // 遮罩展开时出画保持可见，被入画覆盖
      return { opacity: 1 };
    case "radial_wipe":
      return { opacity: 1 };

    case "zoom_flash":
      return {
        transform: `scale(${interpolate(p, [0, 1], [1, 1.1])})`,
        opacity: 1 - p * 0.6,
      };
    case "glitch": {
      const intensity = interpolate(frame, [0, overlap], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return {
        transform: `translateX(${Math.sin(frame * Math.PI * 3.7) * intensity * 12}px) skewX(${Math.sin(frame * Math.PI * 5.1) * intensity * 5}deg)`,
        filter: intensity > 0.3 ? "contrast(1.4) brightness(1.15)" : "none",
        opacity: 1 - p,
      };
    }
    case "spin":
      return {
        transform: `rotate(${interpolate(p, [0, 1], [0, -360])}deg) scale(${interpolate(p, [0, 1], [1, 1.15])})`,
        filter: `blur(${interpolate(p, [0, 1], [0, 8])}px)`,
        opacity: 1 - p,
      };
    case "zoom_heavy":
      return {
        transform: `scale(${interpolate(p, [0, 1], [1, 1.4])})`,
        filter: `blur(${interpolate(p, [0, 1], [0, 10])}px)`,
        opacity: 1 - p,
      };
    case "zoom_through":
      return {
        transform: `scale(${interpolate(p, [0, 1], [1, 2.35])})`,
        filter: `blur(${interpolate(p, [0, 1], [0, 22])}px) brightness(${interpolate(p, [0, 1], [1, 1.45])})`,
        opacity: interpolate(p, [0, .72, 1], [1, .75, 0]),
      };
    case "liquid_warp":
      return {
        transform: `scale(${interpolate(p, [0, 1], [1, 1.13])}) skewX(${interpolate(p, [0, 1], [0, -9])}deg)`,
        filter: `blur(${interpolate(p, [0, 1], [0, 16])}px) saturate(${interpolate(p, [0, 1], [1, 1.5])})`,
        clipPath: `ellipse(${interpolate(p, [0, 1], [90, 10])}% ${interpolate(p, [0, 1], [90, 35])}% at ${interpolate(p, [0, 1], [50, 10])}% 50%)`,
        opacity: 1 - p * .45,
      };
    case "chromatic_aberration":
      return {
        transform: `translateX(${interpolate(p, [0, 1], [0, -85])}px) scale(${interpolate(p, [0, 1], [1, 1.08])})`,
        filter: `contrast(${interpolate(p, [0, 1], [1, 1.35])}) saturate(${interpolate(p, [0, 1], [1, 1.6])}) blur(${interpolate(p, [0, 1], [0, 7])}px)`,
        opacity: 1 - p,
      };
    case "light_leak":
      return { opacity: 1 - lp };
    case "freeze_frame":
      return { opacity: 1 };
    case "flip_3d":
      return {
        transform: `perspective(1000px) rotateY(${interpolate(p, [0, 1], [0, -90])}deg)`,
        opacity: 1 - p * 0.5,
        backfaceVisibility: "hidden",
      };
    case "flash_white":
    case "flash_black":
      return { opacity: 1 };
    case "cut":
    case "none":
    default:
      return { opacity: 1 };
  }
}

// ============================================================
// 入画样式计算
// ============================================================

function getIncomingStyle(
  type: TransitionType,
  frame: number,
  overlap: number,
): React.CSSProperties {
  const p = enterProgress(frame, overlap);
  const lp = linearProgress(frame, overlap);
  const { fps } = { fps: 30 };

  switch (type) {
    case "fade":
    case "dissolve":
      return { opacity: lp };

    case "slide":
    case "slide_left":
      return {
        transform: `translateX(${interpolate(p, [0, 1], [120, 0])}px)`,
        opacity: p,
      };
    case "slide_right":
      return {
        transform: `translateX(${interpolate(p, [0, 1], [-120, 0])}px)`,
        opacity: p,
      };
    case "slide_up":
      return {
        transform: `translateY(${interpolate(p, [0, 1], [120, 0])}px)`,
        opacity: p,
      };
    case "slide_down":
      return {
        transform: `translateY(${interpolate(p, [0, 1], [-120, 0])}px)`,
        opacity: p,
      };

    case "wipe_left":
      return {
        clipPath: `inset(0 0 0 ${interpolate(p, [0, 1], [100, 0])}%)`,
      };
    case "wipe_right":
      return {
        clipPath: `inset(0 ${interpolate(p, [0, 1], [100, 0])}% 0 0)`,
      };
    case "wipe_up":
      return {
        clipPath: `inset(0 0 ${interpolate(p, [0, 1], [100, 0])}% 0)`,
      };
    case "wipe_down":
      return {
        clipPath: `inset(${interpolate(p, [0, 1], [100, 0])}% 0 0 0)`,
      };

    case "zoom_in": {
      const springScale = spring({
        fps,
        frame: Math.min(frame, overlap),
        config: { damping: 200, stiffness: 400 },
      });
      return {
        transform: `scale(${interpolate(springScale, [0, 1], [0.92, 1])})`,
        opacity: p,
      };
    }
    case "zoom_out": {
      const springScale = spring({
        fps,
        frame: Math.min(frame, overlap),
        config: { damping: 200, stiffness: 400 },
      });
      return {
        transform: `scale(${interpolate(springScale, [0, 1], [1.1, 1])})`,
        opacity: p,
      };
    }

    case "blur_in":
      return {
        filter: `blur(${interpolate(p, [0, 1], [10, 0])}px)`,
        opacity: p,
      };
    case "rotate_in":
      return {
        transform: `rotate(${interpolate(p, [0, 1], [-8, 0])}deg) scale(${interpolate(p, [0, 1], [0.92, 1])})`,
        opacity: p,
      };

    case "whip": {
      const whipP = enterProgress(frame, overlap);
      return {
        transform: `translateX(${interpolate(whipP, [0, 1], [350, 0])}px) rotate(${interpolate(whipP, [0, 1], [12, 0])}deg)`,
        filter: `blur(${interpolate(whipP, [0, 1], [20, 0])}px)`,
        opacity: interpolate(whipP, [0, 0.15, 1], [0, 0.2, 1]),
      };
    }

    case "mask":
    case "circle_reveal": {
      const circlePct = interpolate(p, [0, 1], [0, 100]);
      return {
        clipPath: `circle(${circlePct}% at 50% 50%)`,
      };
    }
    case "radial_wipe": {
      const angle = interpolate(p, [0, 1], [0, 360]);
      return {
        clipPath: `polygon(${getRadialWipePoints(angle).join(",")})`,
      };
    }

    case "zoom_flash": {
      const zfScale = interpolate(frame, [0, overlap], [1.15, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.ease),
      });
      return { transform: `scale(${zfScale})`, opacity: p };
    }
    case "glitch": {
      const intensity = interpolate(frame, [0, overlap], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return {
        transform: `translateX(${Math.sin(frame * Math.PI * 4.3) * intensity * 8}px)`,
        filter: intensity > 0.4 ? "contrast(1.3) brightness(1.1)" : "none",
        opacity: interpolate(frame, [0, Math.min(3, overlap)], [0, 1], {
          extrapolateLeft: "clamp",
        }),
      };
    }
    case "spin":
      return {
        transform: `rotate(${interpolate(p, [0, 1], [360, 0])}deg) scale(${interpolate(p, [0, 1], [1.2, 1])})`,
        filter: `blur(${interpolate(p, [0, 1], [8, 0])}px)`,
        opacity: p,
      };
    case "zoom_heavy":
      return {
        transform: `scale(${interpolate(frame, [0, 3, overlap], [2.2, 1.8, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.ease),
        })})`,
        filter: `blur(${interpolate(frame, [0, Math.min(4, overlap), overlap], [20, 8, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })}px)`,
        opacity: interpolate(frame, [0, Math.min(4, overlap)], [0, 1], {
          extrapolateLeft: "clamp",
        }),
      };
    case "zoom_through":
      return {
        transform: `scale(${interpolate(p, [0, 1], [.42, 1])})`,
        filter: `blur(${interpolate(p, [0, 1], [25, 0])}px) brightness(${interpolate(p, [0, 1], [1.4, 1])})`,
        opacity: interpolate(p, [0, .2, 1], [0, .5, 1]),
      };
    case "liquid_warp":
      return {
        transform: `scale(${interpolate(p, [0, 1], [1.16, 1])}) skewX(${interpolate(p, [0, 1], [10, 0])}deg)`,
        filter: `blur(${interpolate(p, [0, 1], [18, 0])}px) saturate(${interpolate(p, [0, 1], [1.55, 1])})`,
        clipPath: `ellipse(${interpolate(p, [0, 1], [4, 95])}% ${interpolate(p, [0, 1], [30, 95])}% at ${interpolate(p, [0, 1], [92, 50])}% 50%)`,
        opacity: p,
      };
    case "chromatic_aberration":
      return {
        transform: `translateX(${interpolate(p, [0, 1], [85, 0])}px) scale(${interpolate(p, [0, 1], [1.08, 1])})`,
        filter: `contrast(${interpolate(p, [0, 1], [1.35, 1])}) saturate(${interpolate(p, [0, 1], [1.6, 1])}) blur(${interpolate(p, [0, 1], [7, 0])}px)`,
        opacity: p,
      };
    case "light_leak":
      return { opacity: lp };
    case "freeze_frame":
      return { opacity: p };
    case "flip_3d":
      return {
        transform: `perspective(1000px) rotateY(${interpolate(p, [0, 1], [90, 0])}deg)`,
        opacity: interpolate(p, [0, 0.3, 1], [0, 0.6, 1]),
        backfaceVisibility: "hidden",
      };
    case "flash_white":
    case "flash_black":
      return { opacity: p };
    case "cut":
    case "none":
    default:
      return { opacity: 1 };
  }
}

// ============================================================
// 径向擦除辅助
// ============================================================

function getRadialWipePoints(angleDeg: number): string[] {
  const cx = 50, cy = 50;
  const radius = 100;
  const pts: string[] = [`${cx}% ${cy}%`];
  const steps = 20;
  for (let i = 0; i <= steps; i++) {
    const a = ((angleDeg / 360) * (i / steps) + 0.01) * Math.PI * 2;
    const x = cx + radius * Math.cos(a);
    const y = cy + radius * Math.sin(a);
    pts.push(`${x}% ${y}%`);
  }
  return pts;
}

// ============================================================
// 覆盖层（闪光/漏光/故障叠加）
// ============================================================

function getOverlay(
  type: TransitionType,
  frame: number,
  overlap: number,
): ReactNode | null {
  switch (type) {
    case "flash_white": {
      const flashOp = interpolate(frame, [0, 4, 8], [1, 0.6, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return (
        <AbsoluteFill
          style={{
            backgroundColor: "#fff",
            opacity: flashOp,
            pointerEvents: "none",
          }}
        />
      );
    }
    case "flash_black": {
      const flashOp = interpolate(frame, [0, 4, 8], [1, 0.6, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return (
        <AbsoluteFill
          style={{
            backgroundColor: "#000",
            opacity: flashOp,
            pointerEvents: "none",
          }}
        />
      );
    }
    case "zoom_flash": {
      const zfFlash = interpolate(frame, [0, 2, 6], [1, 0.7, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return (
        <AbsoluteFill
          style={{
            backgroundColor: "#fff",
            opacity: zfFlash,
            pointerEvents: "none",
          }}
        />
      );
    }
    case "zoom_heavy": {
      const zhFlash = interpolate(frame, [0, 2, 8], [1, 0.8, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return (
        <AbsoluteFill
          style={{
            background: "radial-gradient(circle at center, #fff, transparent 60%)",
            opacity: zhFlash,
            pointerEvents: "none",
          }}
        />
      );
    }
    case "light_leak": {
      const p = enterProgress(frame, overlap);
      const llOp = interpolate(frame, [0, 4, overlap * 0.7, overlap], [1, 0.8, 0.4, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      const llC = interpolate(frame, [0, overlap * 0.5, overlap], [0.6, 0.3, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return (
        <AbsoluteFill
          style={{
            background: `linear-gradient(${70 + frame * 2}deg, rgba(255,${Math.floor(180 - llC * 100)},${Math.floor(80 - llC * 80)},${llOp}) 0%, rgba(255,${Math.floor(200 - llC * 80)},${Math.floor(120 - llC * 60)},${llOp * 0.5}) ${interpolate(p, [0, 1], [100, -20])}%, transparent ${Math.min(100, interpolate(p, [0, 1], [100, -20]) + 30)}%)`,
            pointerEvents: "none",
          }}
        />
      );
    }
    case "glitch": {
      const gIntensity = interpolate(frame, [0, overlap], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      if (gIntensity > 0.5) {
        const offset = Math.sin(frame * 6.7) * gIntensity * 15;
        return (
          <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen" as React.CSSProperties["mixBlendMode"] }}>
            <div style={{ position: "absolute", inset: 0, transform: `translateX(${offset}px)`, opacity: 0.35, background: "#0ff" }} />
            <div style={{ position: "absolute", inset: 0, transform: `translateX(${-offset}px)`, opacity: 0.25, background: "#f0f" }} />
          </AbsoluteFill>
        );
      }
      return null;
    }
    case "freeze_frame": {
      const ffIntensity = interpolate(frame, [0, Math.min(3, overlap), Math.min(8, overlap)], [0, 6, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      if (ffIntensity > 0.5) {
        return (
          <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen" as React.CSSProperties["mixBlendMode"] }}>
            <div style={{ position: "absolute", inset: 0, transform: `translateX(${ffIntensity}px)`, opacity: 0.4, background: "#f00" }} />
            <div style={{ position: "absolute", inset: 0, transform: `translateX(${-ffIntensity}px)`, opacity: 0.3, background: "#00f" }} />
          </AbsoluteFill>
        );
      }
      return null;
    }
    case "zoom_through": {
      const flash = interpolate(frame, [0, overlap * .45, overlap], [0, .42, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      return <AbsoluteFill style={{ pointerEvents: "none", opacity: flash, background: "radial-gradient(circle, #fff 0%, rgba(150,210,255,.7) 22%, transparent 68%)", mixBlendMode: "screen" }} />;
    }
    case "liquid_warp": {
      const x = interpolate(frame, [0, overlap], [-35, 135], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      return <div style={{ position: "absolute", pointerEvents: "none", left: `${x}%`, top: "-20%", width: "30%", height: "140%", borderRadius: "50%", background: "linear-gradient(90deg, transparent, rgba(255,255,255,.35), rgba(80,220,255,.24), transparent)", filter: "blur(35px)", transform: "rotate(12deg)", mixBlendMode: "screen" }} />;
    }
    case "chromatic_aberration": {
      const strength = interpolate(frame, [0, overlap * .45, overlap], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      return (
        <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen", opacity: strength * .32 }}>
          <AbsoluteFill style={{ background: "#00e5ff", transform: `translateX(${strength * 15}px)` }} />
          <AbsoluteFill style={{ background: "#ff1744", transform: `translateX(${-strength * 15}px)`, opacity: .8 }} />
        </AbsoluteFill>
      );
    }
    default:
      return null;
  }
}

// ============================================================
// 遮罩 clip-path 辅助（多形状）
// ============================================================

export function getMaskClipPath(
  type: "circle" | "diamond" | "heart" | "star",
  progress: number,
): string {
  const pct = interpolate(progress, [0, 1], [0, 100]);
  switch (type) {
    case "circle":
      return `circle(${pct}% at 50% 50%)`;
    case "diamond":
      return `polygon(${50 - pct / 2}% ${50}%, ${50}% ${50 - pct / 2}%, ${50 + pct / 2}% ${50}%, ${50}% ${50 + pct / 2}%)`;
    case "heart":
      return `path('M${50},${35 + (100 - pct) * 0.15} C${35 - pct * 0.2},${20 - pct * 0.1} ${15 - pct * 0.1},${35 - pct * 0.1} ${50},${65} C${85 - pct * 0.1},${35 - pct * 0.1} ${65 - pct * 0.2},${20 - pct * 0.1} ${50},${35 + (100 - pct) * 0.15}')`;
    case "star":
      return `polygon(${50}% ${2 + pct * 0.05}%,${61 + pct * 0.05}% ${31 + pct * 0.05}%,${95 + pct * 0.05}% ${31 + pct * 0.05}%,${68 + pct * 0.05}% ${51 + pct * 0.05}%,${79 + pct * 0.05}% ${82 + pct * 0.05}%,${50}% ${65 + pct * 0.05}%,${21 + pct * 0.05}% ${82 + pct * 0.05}%,${32 + pct * 0.05}% ${51 + pct * 0.05}%,${5 + pct * 0.05}% ${31 + pct * 0.05}%,${39 + pct * 0.05}% ${31 + pct * 0.05}%)`;
    default:
      return `circle(${pct}% at 50% 50%)`;
  }
}

// ============================================================
// Whip Pan Dual Hook — 出画 + 入画
// ============================================================

interface WhipPanDualStyles {
  outgoing: React.CSSProperties;
  incoming: React.CSSProperties;
}

export function useWhipPanDual(
  frame: number,
  overlap: number,
  direction: "left" | "right" = "right",
): WhipPanDualStyles {
  const dir = direction === "right" ? 1 : -1;
  const p = enterProgress(frame, overlap);

  return {
    outgoing: {
      transform: `translateX(${dir * interpolate(p, [0, 1], [0, -350])}px) rotate(${dir * interpolate(p, [0, 1], [0, -12])}deg)`,
      filter: `blur(${interpolate(p, [0, 1], [0, 25])}px)`,
      opacity: 1 - p,
    },
    incoming: {
      transform: `translateX(${dir * interpolate(p, [0, 1], [350, 0])}px) rotate(${dir * interpolate(p, [0, 1], [12, 0])}deg)`,
      filter: `blur(${interpolate(p, [0, 1], [20, 0])}px)`,
      opacity: interpolate(p, [0, 0.15, 1], [0, 0.2, 1]),
    },
  };
}

// ============================================================
// 3D Flip Hook
// ============================================================

interface Flip3DStyles {
  outgoing: React.CSSProperties;
  incoming: React.CSSProperties;
}

export function use3DFlip(
  frame: number,
  overlap: number,
): Flip3DStyles {
  const p = enterProgress(frame, overlap);

  return {
    outgoing: {
      transform: `perspective(1200px) rotateY(${interpolate(p, [0, 1], [0, -90])}deg)`,
      opacity: 1 - p * 0.5,
      backfaceVisibility: "hidden" as const,
    },
    incoming: {
      transform: `perspective(1200px) rotateY(${interpolate(p, [0, 1], [90, 0])}deg)`,
      opacity: interpolate(p, [0, 0.3, 1], [0, 0.6, 1]),
      backfaceVisibility: "hidden" as const,
    },
  };
}

// ============================================================
// DualTransitionLayer 组件
// ============================================================

interface DualTransitionLayerProps {
  transitionType: TransitionType;
  overlapFrames: number;
  totalDurationInFrames: number;
  /** 当前分镜内容（入画） */
  currentContent: ReactNode;
  /** 上一个分镜内容（出画），null 表示首个分镜 */
  outgoingContent: ReactNode | null;
}

/**
 * 双层过渡层 —— 同时渲染出画和入画，实现真正的 A→B 过渡。
 *
 * 设计：
 * - 过渡期 [0, overlapFrames): 出画 + 入画 + 覆盖层
 * - 稳定期 [overlapFrames, totalDuration): 仅入画内容（无动画）
 *
 * 支持 30+ 种过渡效果，包括基本（fade/slide/dissolve）、
 * 特效（whip/glitch/spin/flip_3d）、遮罩（mask/circle_reveal/radial_wipe）。
 */
export const DualTransitionLayer: React.FC<DualTransitionLayerProps> = ({
  transitionType,
  overlapFrames,
  totalDurationInFrames,
  currentContent,
  outgoingContent,
}) => {
  const frame = useCurrentFrame();
  const inTransition = frame < overlapFrames;

  // 无过渡（cut/none 或首个分镜）
  if (transitionType === "slice_wipe" && outgoingContent && overlapFrames > 0) {
    const slices = 6;
    return (
      <AbsoluteFill>
        {inTransition && <AbsoluteFill>{outgoingContent}</AbsoluteFill>}
        {Array.from({ length: slices }).map((_, index) => {
          const stagger = index * 0.55;
          const progress = interpolate(
            frame,
            [stagger, Math.max(stagger + 1, overlapFrames - (slices - 1 - index) * 0.25)],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) },
          );
          const left = (index * 100) / slices;
          const right = 100 - ((index + 1) * 100) / slices;
          const direction = index % 2 === 0 ? -1 : 1;
          return (
            <AbsoluteFill
              key={index}
              style={{
                clipPath: `inset(0 ${right}% 0 ${left}%)`,
                transform: inTransition ? `translateY(${direction * (1 - progress) * 100}%)` : undefined,
              }}
            >
              {currentContent}
            </AbsoluteFill>
          );
        })}
      </AbsoluteFill>
    );
  }

  if (overlapFrames === 0 || !outgoingContent) {
    return <AbsoluteFill>{currentContent}</AbsoluteFill>;
  }

  const outgoingStyle = getOutgoingStyle(transitionType, frame, overlapFrames);
  const incomingStyle = getIncomingStyle(transitionType, frame, overlapFrames);
  const overlay = getOverlay(transitionType, frame, overlapFrames);

  return (
    <AbsoluteFill>
      {/* 出画层 */}
      {inTransition && (
        <AbsoluteFill style={outgoingStyle}>
          {outgoingContent}
        </AbsoluteFill>
      )}

      {/* 入画层 */}
      <AbsoluteFill style={inTransition ? incomingStyle : undefined}>
        {currentContent}
      </AbsoluteFill>

      {/* 覆盖层（闪光/漏光/故障） */}
      {inTransition && overlay}
    </AbsoluteFill>
  );
};
