// src/dynamic/comp_slow_life_montage.tsx
import { useCurrentFrame, useVideoConfig, interpolate, Easing, AbsoluteFill, Img } from "remotion";
import { jsx, jsxs } from "react/jsx-runtime";
var SlowLifeMontage = ({
  source_material_ids = [],
  imagePath = "",
  imageUrls = [],
  animation = "zoom_in_slow",
  color_grade = "warm",
  ambient_sound = true,
  subtitle = "",
  subtitle_animation = "fade_in"
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const imageSrc = imageUrls[0] || imagePath;
  const zoomScale = interpolate(frame, [0, durationInFrames], [1, 1.08], {
    easing: Easing.inOut(Easing.ease),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp"
  });
  const warmOpacity = interpolate(frame, [0, durationInFrames * 0.3], [0, 0.15], {
    easing: Easing.inOut(Easing.ease),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp"
  });
  const subtitleOpacity = interpolate(
    frame,
    [durationInFrames * 0.1, durationInFrames * 0.3],
    [0, 1],
    {
      easing: Easing.inOut(Easing.ease),
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp"
    }
  );
  const ambientOpacity = interpolate(frame, [0, 15], [0, 0.6], {
    easing: Easing.inOut(Easing.ease),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp"
  });
  const translateX = interpolate(frame, [0, durationInFrames], [0, -15], {
    easing: Easing.inOut(Easing.ease),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp"
  });
  const subtitleY = interpolate(
    frame,
    [durationInFrames * 0.1, durationInFrames * 0.3],
    [30, 0],
    {
      easing: Easing.out(Easing.quad),
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp"
    }
  );
  const containerStyle = {
    width: 1080,
    height: 1920,
    overflow: "hidden",
    position: "relative",
    background: "#1a1a2e"
  };
  const imageStyle = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform: `scale(${zoomScale}) translateX(${translateX}px)`,
    transition: "transform 0.1s ease-out"
  };
  const warmOverlayStyle = {
    position: "absolute",
    top: 0,
    left: 0,
    width: "100%",
    height: "100%",
    background: "linear-gradient(135deg, #ff8c42 0%, #ffd700 50%, #ff6347 100%)",
    opacity: warmOpacity,
    mixBlendMode: "overlay",
    pointerEvents: "none"
  };
  const vignetteStyle = {
    position: "absolute",
    top: 0,
    left: 0,
    width: "100%",
    height: "100%",
    background: "radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.4) 100%)",
    pointerEvents: "none"
  };
  const ambientIndicatorStyle = {
    position: "absolute",
    bottom: 100,
    left: 40,
    color: "rgba(255, 255, 255, 0.7)",
    fontSize: 14,
    fontFamily: '"PingFang SC", "Microsoft YaHei", sans-serif',
    opacity: ambientOpacity,
    display: "flex",
    alignItems: "center",
    gap: 8,
    letterSpacing: 2,
    textShadow: "0 0 10px rgba(0,0,0,0.5)"
  };
  const subtitleStyle = {
    position: "absolute",
    bottom: 180,
    left: "50%",
    transform: `translateX(-50%) translateY(${subtitleY}px)`,
    color: "#fff",
    fontSize: 36,
    fontFamily: '"PingFang SC", "Microsoft YaHei", sans-serif',
    fontWeight: 300,
    letterSpacing: 4,
    opacity: subtitleOpacity,
    textAlign: "center",
    width: "80%",
    textShadow: "0 2px 20px rgba(0,0,0,0.6)",
    lineHeight: 1.6
  };
  const lightGlowStyle = {
    position: "absolute",
    top: -100,
    right: -100,
    width: 400,
    height: 400,
    background: "radial-gradient(circle, rgba(255,200,100,0.15) 0%, transparent 70%)",
    pointerEvents: "none",
    opacity: interpolate(frame, [0, durationInFrames * 0.5], [0, 0.3], {
      easing: Easing.inOut(Easing.ease),
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp"
    })
  };
  return /* @__PURE__ */ jsxs(AbsoluteFill, { style: containerStyle, children: [
    imageSrc && /* @__PURE__ */ jsx(Img, { src: imageSrc, style: imageStyle }),
    /* @__PURE__ */ jsx("div", { style: warmOverlayStyle }),
    /* @__PURE__ */ jsx("div", { style: vignetteStyle }),
    /* @__PURE__ */ jsx("div", { style: lightGlowStyle }),
    ambient_sound && /* @__PURE__ */ jsxs("div", { style: ambientIndicatorStyle, children: [
      /* @__PURE__ */ jsx("span", { children: "\u{1F3A7}" }),
      /* @__PURE__ */ jsx("span", { children: "\u73AF\u5883\u97F3 \xB7 \u80E1\u540C" })
    ] }),
    subtitle && /* @__PURE__ */ jsx("div", { style: subtitleStyle, children: subtitle }),
    /* @__PURE__ */ jsx("div", { style: {
      position: "absolute",
      bottom: 0,
      left: 0,
      width: "100%",
      height: "40%",
      background: "linear-gradient(to top, rgba(0,0,0,0.4) 0%, transparent 100%)",
      pointerEvents: "none"
    } })
  ] });
};
var comp_slow_life_montage_default = SlowLifeMontage;
export {
  comp_slow_life_montage_default as default
};
