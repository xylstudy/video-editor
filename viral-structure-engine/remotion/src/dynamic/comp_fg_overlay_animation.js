// src/dynamic/comp_fg_overlay_animation.tsx
import { AbsoluteFill, Img, useCurrentFrame, useVideoConfig, interpolate, Easing, spring } from "remotion";
import { jsx, jsxs } from "react/jsx-runtime";
var comp_fg_overlay_animation = ({
  backgroundSourceId = "",
  foregroundSourceId = "",
  subtitleText = "",
  subtitleColor = "#ffd700",
  foregroundEffect = "glow_fade_in",
  foregroundDuration = 4
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const bgScale = interpolate(frame, [0, durationInFrames], [1, 1.05], {
    extrapolateRight: "clamp"
  });
  const enterProgress = spring({
    frame,
    fps,
    config: { damping: 12, stiffness: 80 }
  });
  const opacity = interpolate(enterProgress, [0, 1], [0, 1]);
  const glowOpacity = interpolate(enterProgress, [0, 0.3, 1], [0, 0.8, 0.2]);
  const glowSize = interpolate(enterProgress, [0, 0.5, 1], [0, 40, 20]);
  const rotateY = interpolate(
    frame % 120,
    [0, 60, 120],
    [-5, 5, -5],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.sin)
    }
  );
  const subtitleY = interpolate(frame, [20, 40], [200, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back())
  });
  const subtitleOpacity = interpolate(frame, [20, 40], [0, 1]);
  const bgSrc = backgroundSourceId;
  const fgSrc = foregroundSourceId || backgroundSourceId;
  return /* @__PURE__ */ jsxs(AbsoluteFill, { style: {
    backgroundColor: "#000",
    width: 1080,
    height: 1920
  }, children: [
    /* @__PURE__ */ jsx(AbsoluteFill, { style: {
      transform: `scale(${bgScale})`
    }, children: bgSrc && /* @__PURE__ */ jsx(
      Img,
      {
        src: bgSrc,
        style: {
          width: "100%",
          height: "100%",
          objectFit: "cover"
        }
      }
    ) }),
    /* @__PURE__ */ jsx(AbsoluteFill, { style: {
      opacity,
      transform: `
          perspective(1000px)
          rotateY(${rotateY}deg)
          scale(${1 + (1 - enterProgress) * 0.1})
        `,
      filter: `
          brightness(${0.5 + enterProgress * 0.5})
          drop-shadow(0 0 ${glowSize}px rgba(255, 215, 0, ${glowOpacity}))
        `,
      transition: "transform 0.1s ease-out"
    }, children: fgSrc && /* @__PURE__ */ jsx(
      Img,
      {
        src: fgSrc,
        style: {
          width: "100%",
          height: "100%",
          objectFit: "cover"
          // 假设前景图片已经是抠好的PNG，用mix-blend-mode可以增强效果
          // 如果是在绿幕上，可以加chroma key，这里假设已经抠好
        }
      }
    ) }),
    /* @__PURE__ */ jsx(AbsoluteFill, { style: {
      justifyContent: "flex-end",
      alignItems: "center",
      paddingBottom: 100
    }, children: /* @__PURE__ */ jsx(
      "div",
      {
        style: {
          transform: `translateY(${subtitleY}px)`,
          opacity: subtitleOpacity,
          color: subtitleColor,
          fontSize: 56,
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          fontWeight: "bold",
          textShadow: `
              0 2px 4px rgba(0,0,0,0.5),
              0 0 20px rgba(255,215,0,0.3),
              0 0 40px rgba(255,215,0,0.1)
            `,
          textAlign: "center",
          letterSpacing: 4,
          lineHeight: 1.5,
          padding: "0 40px"
        },
        children: subtitleText
      }
    ) })
  ] });
};
var comp_fg_overlay_animation_default = comp_fg_overlay_animation;
export {
  comp_fg_overlay_animation_default as default
};
