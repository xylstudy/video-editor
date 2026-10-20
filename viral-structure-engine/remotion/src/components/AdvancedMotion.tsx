import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  OffthreadVideo,
  interpolate,
  random,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { registerComponent } from "./registry";

type MotionProps = Record<string, unknown> & {
  durationInFrames?: number;
  imagePath?: string;
  foregroundSourceId?: string;
  backgroundSourceId?: string;
  images?: string[];
  imageUrls?: string[];
  text?: string;
  subtitle?: string;
  subtitleText?: string;
  accentColor?: string;
  accent_color?: string;
  intensity?: number;
  beatFrames?: number[];
  beat_frames?: number[];
};

const FONT = "'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif";

const clamp = (value: number, min = 0, max = 1) =>
  Math.min(max, Math.max(min, value));

const getText = (props: MotionProps) =>
  String(props.text || props.subtitleText || props.subtitle || "");

const getAccent = (props: MotionProps) =>
  String(props.accentColor || props.accent_color || "#ff4d67");

const getImages = (props: MotionProps): string[] => {
  const candidates = [
    ...(Array.isArray(props.images) ? props.images : []),
    ...(Array.isArray(props.imageUrls) ? props.imageUrls : []),
    props.imagePath,
    props.backgroundSourceId,
    props.foregroundSourceId,
  ];
  return Array.from(new Set(candidates.filter((item): item is string => typeof item === "string" && item.length > 0)));
};

const isVideo = (src: string) => /\.(mp4|mov|webm|mkv|avi)(?:[?#].*)?$/i.test(src);

const resolveSource = (src: string) =>
  src.startsWith("/") && !src.startsWith("//") ? staticFile(src.slice(1)) : src;

const Media: React.FC<{
  src?: string;
  style?: React.CSSProperties;
  fit?: "cover" | "contain";
}> = ({ src, style, fit = "cover" }) => {
  if (!src) {
    return <AbsoluteFill style={{ background: "linear-gradient(145deg, #111827, #030712)" }} />;
  }
  const mediaStyle: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: fit,
    ...style,
  };
  const resolved = resolveSource(src);
  return isVideo(src)
    ? <OffthreadVideo src={resolved} muted style={mediaStyle} />
    : <Img src={resolved} style={mediaStyle} />;
};

const Finish: React.FC<{ accent?: string; grain?: number; vignette?: number }> = ({
  accent = "#ff4d67",
  grain = 0.11,
  vignette = 0.56,
}) => {
  const frame = useCurrentFrame();
  const grainX = Math.round(random(`grain-x-${frame}`) * 90);
  const grainY = Math.round(random(`grain-y-${frame}`) * 90);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill style={{ background: `linear-gradient(155deg, ${accent}20 0%, transparent 36%, #05081655 100%)`, mixBlendMode: "screen" }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse at center, transparent 38%, rgba(0,0,0,${vignette}) 100%)` }} />
      <AbsoluteFill
        style={{
          opacity: grain,
          mixBlendMode: "overlay",
          backgroundImage: "repeating-radial-gradient(circle at 20% 30%, #fff 0 0.7px, transparent 0.8px 3px)",
          backgroundSize: "5px 5px",
          backgroundPosition: `${grainX}px ${grainY}px`,
        }}
      />
    </AbsoluteFill>
  );
};

const EmptyHint: React.FC = () => (
  <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", color: "#94a3b8", font: `600 34px ${FONT}` }}>
    暂无可用素材
  </AbsoluteFill>
);

export const FocusBlurResolve: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const text = getText(props);
  const duration = Number(props.durationInFrames || fps * 3);
  const p = spring({ frame, fps, config: { damping: 22, stiffness: 90, mass: 0.8 } });
  const exit = interpolate(frame, [duration - 12, duration], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const blur = interpolate(p, [0, 1], [32, 0]);
  const tracking = interpolate(p, [0, 1], [22, 2]);
  return (
    <AbsoluteFill style={{ backgroundColor: "#05070d", overflow: "hidden" }}>
      <Media src={images[0]} style={{ transform: `scale(${interpolate(frame, [0, duration], [1.1, 1.02], { extrapolateRight: "clamp" })})`, filter: "brightness(.48) saturate(1.12)" }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: 90 }}>
        <div style={{ color: "white", fontFamily: FONT, fontSize: Number(props.fontSize || 88), fontWeight: 800, lineHeight: 1.12, textAlign: "center", letterSpacing: tracking, filter: `blur(${blur}px)`, transform: `scale(${interpolate(p, [0, 1], [1.12, 1])})`, opacity: p * exit, textShadow: "0 10px 45px rgba(0,0,0,.65)" }}>
          {text}
        </div>
      </AbsoluteFill>
      <Finish accent={getAccent(props)} />
    </AbsoluteFill>
  );
};

export const KineticWarp: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const words = getText(props).trim().split(/\s+/).filter(Boolean);
  const units = words.length > 1 ? words : Array.from(getText(props));
  const accent = getAccent(props);
  return (
    <AbsoluteFill style={{ background: "#05060a", overflow: "hidden" }}>
      <Media src={images[0]} style={{ filter: "brightness(.38) contrast(1.12) saturate(1.25)", transform: `scale(${1.04 + frame / (fps * 150)})` }} />
      <AbsoluteFill style={{ justifyContent: "center", padding: "0 78px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "8px 22px", perspective: 900 }}>
          {units.map((unit, index) => {
            const p = spring({ frame: frame - index * 2.2, fps, config: { damping: 15, stiffness: 165, mass: 0.55 } });
            const y = interpolate(p, [0, 1], [120 + index * 5, 0]);
            const rotate = interpolate(p, [0, 1], [index % 2 ? 22 : -22, 0]);
            return (
              <span key={`${unit}-${index}`} style={{ display: "inline-block", color: index === units.length - 1 ? accent : "#fff", font: `900 ${Number(props.fontSize || 94)}px/1.08 ${FONT}`, letterSpacing: -3, opacity: p, transform: `translateY(${y}px) rotate(${rotate}deg) skewX(${interpolate(p, [0, 1], [-18, 0])}deg) scaleY(${interpolate(p, [0, 1], [1.7, 1])})`, textShadow: "0 14px 42px rgba(0,0,0,.7)" }}>
                {unit}
              </span>
            );
          })}
        </div>
      </AbsoluteFill>
      <Finish accent={accent} grain={0.14} />
    </AbsoluteFill>
  );
};

export const MaskRevealUp: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const lines = getText(props).split(/[\n，。！？]/).filter(Boolean).slice(0, 3);
  return (
    <AbsoluteFill style={{ background: "#080a10" }}>
      <Media src={images[0]} style={{ filter: "brightness(.55) saturate(.85)", transform: `scale(${interpolate(frame, [0, fps * 4], [1.12, 1.02], { extrapolateRight: "clamp" })})` }} />
      <AbsoluteFill style={{ justifyContent: "flex-end", padding: "0 72px 270px" }}>
        {lines.map((line, index) => {
          const p = spring({ frame: frame - 7 - index * 5, fps, config: { damping: 18, stiffness: 130 } });
          return (
            <div key={`${line}-${index}`} style={{ overflow: "hidden", marginTop: 4 }}>
              <div style={{ color: "white", font: `850 ${Number(props.fontSize || 82)}px/1.15 ${FONT}`, transform: `translateY(${interpolate(p, [0, 1], [110, 0])}px)`, opacity: p, textShadow: "0 8px 35px #000" }}>
                {line}
              </div>
            </div>
          );
        })}
        <div style={{ marginTop: 24, width: `${interpolate(frame, [10, 28], [0, 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}%`, height: 7, borderRadius: 9, background: getAccent(props) }} />
      </AbsoluteFill>
      <Finish accent={getAccent(props)} />
    </AbsoluteFill>
  );
};

export const RGBGlitchText: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const images = getImages(props);
  const text = getText(props);
  const burst = Math.max(0, Math.sin(frame * 2.35)) * (frame < 18 ? 1 : 0.12);
  const base: React.CSSProperties = { position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 70, textAlign: "center", font: `900 ${Number(props.fontSize || 96)}px/1.08 ${FONT}`, letterSpacing: -3 };
  return (
    <AbsoluteFill style={{ background: "#020307", overflow: "hidden" }}>
      <Media src={images[0]} style={{ filter: `brightness(.42) contrast(${1.08 + burst * .25}) saturate(1.35)` }} />
      <div style={{ ...base, color: "#00e5ff", opacity: 0.7 * burst, transform: `translate(${10 * burst}px, ${-3 * burst}px)`, mixBlendMode: "screen" }}>{text}</div>
      <div style={{ ...base, color: "#ff194f", opacity: 0.7 * burst, transform: `translate(${-10 * burst}px, ${3 * burst}px)`, mixBlendMode: "screen" }}>{text}</div>
      <div style={{ ...base, color: "white", transform: `translateX(${Math.sin(frame * 5.1) * burst * 4}px)`, textShadow: "0 12px 45px #000" }}>{text}</div>
      {frame < 16 && Array.from({ length: 5 }).map((_, index) => <div key={index} style={{ position: "absolute", left: 0, right: 0, top: `${18 + index * 15 + random(index) * 8}%`, height: 5 + random(index + 8) * 16, background: index % 2 ? "#00e5ff44" : "#ff174444", transform: `translateX(${Math.sin(frame + index) * 35}px)` }} />)}
      <Finish accent={getAccent(props)} grain={0.16} />
    </AbsoluteFill>
  );
};

const Card: React.FC<{ src: string; index: number; frame: number; fps: number; width?: number; height?: number }> = ({ src, index, frame, fps, width = 720, height = 1040 }) => {
  const p = spring({ frame: frame - index * 4, fps, config: { damping: 16, stiffness: 125, mass: 0.7 } });
  const rotation = (random(`card-r-${index}`) - 0.5) * 13;
  const x = (random(`card-x-${index}`) - 0.5) * 170;
  return (
    <div style={{ position: "absolute", left: "50%", top: "50%", width, height, padding: 14, borderRadius: 28, background: "rgba(255,255,255,.92)", boxShadow: "0 30px 90px rgba(0,0,0,.6)", opacity: p, transform: `translate(-50%, -50%) translate(${x}px, ${interpolate(p, [0, 1], [700, index * -24])}px) rotate(${interpolate(p, [0, 1], [rotation * 2.2, rotation])}deg) scale(${interpolate(p, [0, 1], [.72, 1])})` }}>
      <Media src={src} style={{ borderRadius: 18 }} />
    </div>
  );
};

export const BrollStack: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props).slice(0, 5);
  if (!images.length) return <EmptyHint />;
  return (
    <AbsoluteFill style={{ background: "linear-gradient(145deg, #161827, #05060a)", overflow: "hidden" }}>
      {images.map((src, index) => <Card key={`${src}-${index}`} src={src} index={index} frame={frame} fps={fps} />)}
      <div style={{ position: "absolute", left: 58, right: 58, bottom: 120, color: "white", font: `850 62px/1.15 ${FONT}`, textShadow: "0 6px 30px #000", zIndex: 9 }}>{getText(props)}</div>
      <Finish accent={getAccent(props)} />
    </AbsoluteFill>
  );
};

export const SplitScreenBurst: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  if (!images.length) return <EmptyHint />;
  const panels = Array.from({ length: 4 }, (_, i) => images[i % images.length]);
  return (
    <AbsoluteFill style={{ background: "#030406", display: "grid", gridTemplateColumns: "1fr 1fr", gridTemplateRows: "1fr 1fr", gap: 10, padding: 10 }}>
      {panels.map((src, index) => {
        const p = spring({ frame: frame - index * 2.5, fps, config: { damping: 18, stiffness: 170 } });
        return <div key={`${src}-${index}`} style={{ overflow: "hidden", opacity: p, transform: `scale(${interpolate(p, [0, 1], [.45, 1])})`, clipPath: `inset(${interpolate(p, [0, 1], [50, 0])}% 0)` }}><Media src={src} style={{ transform: `scale(${1.15 - p * .08})`, filter: `brightness(${.72 + index * .05}) saturate(1.2)` }} /></div>;
      })}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: 75 }}>
        <div style={{ color: "white", background: "rgba(0,0,0,.58)", backdropFilter: "blur(14px)", border: "1px solid rgba(255,255,255,.28)", borderRadius: 20, padding: "24px 34px", font: `900 66px/1.12 ${FONT}`, textAlign: "center", transform: `scale(${spring({ frame: frame - 12, fps, config: { damping: 14, stiffness: 150 } })})` }}>{getText(props)}</div>
      </AbsoluteFill>
      <Finish accent={getAccent(props)} grain={0.09} />
    </AbsoluteFill>
  );
};

export const ParallaxPhoto: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const bg = String(props.backgroundSourceId || images[0] || "");
  const fg = String(props.foregroundSourceId || images[1] || images[0] || "");
  const duration = Number(props.durationInFrames || fps * 4);
  const progress = clamp(frame / Math.max(1, duration - 1));
  if (!bg) return <EmptyHint />;
  return (
    <AbsoluteFill style={{ background: "#05070b", overflow: "hidden", perspective: 1200 }}>
      <Media src={bg} style={{ transform: `translate3d(${interpolate(progress, [0, 1], [-18, 18])}px, ${interpolate(progress, [0, 1], [-8, 14])}px, 0) scale(${interpolate(progress, [0, 1], [1.15, 1.25])})`, filter: "brightness(.62) blur(3px) saturate(1.12)" }} />
      {fg && <AbsoluteFill style={{ transform: `translate3d(${interpolate(progress, [0, 1], [38, -34])}px, ${interpolate(progress, [0, 1], [22, -18])}px, 80px) scale(${interpolate(progress, [0, 1], [1.03, 1.13])})`, filter: "drop-shadow(0 25px 40px rgba(0,0,0,.42))" }}><Media src={fg} fit="contain" /></AbsoluteFill>}
      <div style={{ position: "absolute", left: 62, right: 62, bottom: 160, color: "white", font: `850 66px/1.15 ${FONT}`, textShadow: "0 7px 30px #000" }}>{getText(props)}</div>
      <Finish accent={getAccent(props)} />
    </AbsoluteFill>
  );
};

export const PolaroidCollage: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  if (!images.length) return <EmptyHint />;
  const cards = Array.from({ length: Math.min(4, Math.max(3, images.length)) }, (_, i) => images[i % images.length]);
  const positions = [[-185, -370, -10], [180, -160, 8], [-150, 210, -5], [190, 390, 11]];
  return (
    <AbsoluteFill style={{ background: "radial-gradient(circle at 30% 20%, #342b38, #0b0b12 60%)", overflow: "hidden" }}>
      {cards.map((src, index) => {
        const p = spring({ frame: frame - index * 5, fps, config: { damping: 15, stiffness: 120 } });
        const [x, y, r] = positions[index];
        return <div key={`${src}-${index}`} style={{ position: "absolute", left: "50%", top: "50%", width: 590, height: 690, padding: "18px 18px 90px", background: "#f5f1e8", boxShadow: "0 30px 75px rgba(0,0,0,.55)", transform: `translate(-50%,-50%) translate(${x}px, ${interpolate(p, [0, 1], [y + 700, y])}px) rotate(${r}deg) scale(${interpolate(p, [0, 1], [.7, 1])})`, opacity: p }}><Media src={src} /></div>;
      })}
      <div style={{ position: "absolute", left: 70, right: 70, bottom: 80, color: "#fff", font: `800 55px/1.2 ${FONT}`, textAlign: "center", textShadow: "0 7px 28px #000" }}>{getText(props)}</div>
      <Finish accent={getAccent(props)} grain={0.18} />
    </AbsoluteFill>
  );
};

export const BeatMontage: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const duration = Number(props.durationInFrames || fps * 3);
  if (!images.length) return <EmptyHint />;
  const configured = (props.beatFrames || props.beat_frames || []).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  const beats = configured.length ? configured : Array.from({ length: Math.max(2, images.length) }, (_, i) => Math.round(i * duration / Math.max(2, images.length)));
  const beatIndex = Math.max(0, beats.filter((beat) => beat <= frame).length - 1);
  const beatStart = beats[beatIndex] || 0;
  const nextBeat = beats[beatIndex + 1] || duration;
  const local = clamp((frame - beatStart) / Math.max(1, nextBeat - beatStart));
  const hit = interpolate(frame - beatStart, [0, 2, 6], [1, .7, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <Media src={images[beatIndex % images.length]} style={{ transform: `scale(${interpolate(local, [0, 1], [1.16, 1.02])}) translateX(${(beatIndex % 2 ? -1 : 1) * interpolate(local, [0, 1], [14, -10])}px)`, filter: `brightness(${.82 + hit * .2}) contrast(1.12) saturate(1.22)` }} />
      <AbsoluteFill style={{ background: "white", opacity: hit * .34, mixBlendMode: "screen" }} />
      <div style={{ position: "absolute", left: 60, right: 60, bottom: 145, color: "white", font: `900 65px/1.1 ${FONT}`, textShadow: "0 8px 32px #000", transform: `translateY(${hit * -12}px)` }}>{getText(props)}</div>
      <Finish accent={getAccent(props)} grain={0.13} />
    </AbsoluteFill>
  );
};

export const HeroPushIn: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const duration = Number(props.durationInFrames || fps * 4);
  const push = interpolate(frame, [0, duration], [1, 1.22], { extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  const title = spring({ frame: frame - 8, fps, config: { damping: 18, stiffness: 110 } });
  return (
    <AbsoluteFill style={{ background: "#030408", overflow: "hidden" }}>
      <Media src={images[0]} style={{ transform: `scale(${push})`, filter: "brightness(.55) contrast(1.1) saturate(1.18)" }} />
      <AbsoluteFill style={{ justifyContent: "center", padding: 72 }}>
        <div style={{ width: 70, height: 8, borderRadius: 10, background: getAccent(props), marginBottom: 28, transform: `scaleX(${title})`, transformOrigin: "left" }} />
        <div style={{ color: "white", font: `900 ${Number(props.fontSize || 96)}px/1.02 ${FONT}`, letterSpacing: -4, opacity: title, transform: `translateY(${interpolate(title, [0, 1], [80, 0])}px)`, textShadow: "0 14px 46px #000" }}>{getText(props)}</div>
      </AbsoluteFill>
      <Finish accent={getAccent(props)} />
    </AbsoluteFill>
  );
};

export const CinematicGrainScene: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const duration = Number(props.durationInFrames || fps * 4);
  return (
    <AbsoluteFill style={{ background: "#050509", overflow: "hidden" }}>
      <Media src={images[0]} style={{ transform: `scale(${interpolate(frame, [0, duration], [1.04, 1.13], { extrapolateRight: "clamp" })})`, filter: "brightness(.76) contrast(1.18) saturate(.82) sepia(.1)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(180deg, #0b244744, transparent 48%, #ff6b3544)", mixBlendMode: "color" }} />
      <div style={{ position: "absolute", left: 64, right: 64, bottom: 150, color: "#f7f1e8", font: `700 54px/1.25 ${FONT}`, letterSpacing: 2, textShadow: "0 5px 25px #000" }}>{getText(props)}</div>
      <Finish accent={getAccent(props)} grain={Number(props.grain || .22)} vignette={0.68} />
    </AbsoluteFill>
  );
};

export const NeonLightRays: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const images = getImages(props);
  const accent = getAccent(props);
  const sweep = (frame * 2.8) % 160 - 30;
  return (
    <AbsoluteFill style={{ background: "#02040a", overflow: "hidden" }}>
      <Media src={images[0]} style={{ filter: "brightness(.46) contrast(1.22) saturate(1.38)" }} />
      <AbsoluteFill style={{ opacity: .62, mixBlendMode: "screen", background: `conic-gradient(from ${-28 + frame * .25}deg at 50% -8%, transparent 0deg, ${accent}80 10deg, transparent 22deg, #22d3ee55 42deg, transparent 57deg)` }} />
      <div style={{ position: "absolute", top: "-20%", left: `${sweep}%`, width: "16%", height: "145%", background: `linear-gradient(90deg, transparent, ${accent}aa, #fff8, transparent)`, filter: "blur(28px)", transform: "rotate(14deg)", mixBlendMode: "screen" }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: 78 }}><div style={{ color: "white", font: `900 ${Number(props.fontSize || 88)}px/1.08 ${FONT}`, textAlign: "center", textShadow: `0 0 18px ${accent}, 0 8px 40px #000` }}>{getText(props)}</div></AbsoluteFill>
      <Finish accent={accent} grain={0.12} />
    </AbsoluteFill>
  );
};

export const EchoStack: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const images = getImages(props);
  const source = images[0];
  const pulse = Math.sin(Math.min(frame, 12) / 12 * Math.PI);
  if (!source) return <EmptyHint />;
  return (
    <AbsoluteFill style={{ background: "#050505", overflow: "hidden" }}>
      {[-1, 0, 1].map((direction, index) => (
        <AbsoluteFill
          key={direction}
          style={{
            opacity: direction === 0 ? 1 : 0.34 * pulse,
            transform: `translateX(${direction * (20 + pulse * 34)}px) scale(${1.02 + index * 0.012})`,
            filter: direction === 0 ? "contrast(1.08) saturate(1.18)" : `hue-rotate(${direction * 18}deg) saturate(1.5)`,
            mixBlendMode: direction === 0 ? "normal" : "screen",
          }}
        >
          <Media src={source} />
        </AbsoluteFill>
      ))}
      <AbsoluteFill style={{ background: `linear-gradient(90deg, ${getAccent(props)}33, transparent 35%, transparent 65%, #22d3ee33)` }} />
      <Finish accent={getAccent(props)} grain={0.1} vignette={0.4} />
    </AbsoluteFill>
  );
};

export const DoodlePop: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const p = spring({ frame: frame - 2, fps, config: { damping: 10, stiffness: 220, mass: 0.45 } });
  const accent = getAccent(props);
  const symbol = String(props.symbol || "!!");
  const position = props.position && typeof props.position === "object"
    ? props.position as Record<string, unknown>
    : {};
  const motionPath = Array.isArray(props.motion_path)
    ? props.motion_path.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
  const firstPoint = motionPath[0] || position;
  const lastPoint = motionPath[motionPath.length - 1] || position;
  const duration = Math.max(1, Number(props.durationInFrames || 30) - 1);
  const pathProgress = clamp(frame / duration);
  const x = interpolate(pathProgress, [0, 1], [Number(firstPoint.x ?? .82), Number(lastPoint.x ?? firstPoint.x ?? .82)]);
  const y = interpolate(pathProgress, [0, 1], [Number(firstPoint.y ?? .18), Number(lastPoint.y ?? firstPoint.y ?? .18)]);
  if (!images[0]) return <EmptyHint />;
  return (
    <AbsoluteFill style={{ background: "#080808", overflow: "hidden" }}>
      <Media src={images[0]} style={{ transform: `scale(${1.06 + Math.sin(frame / 5) * .012})`, filter: "contrast(1.08) saturate(1.22)" }} />
      <div style={{ position: "absolute", left: `${x * 100}%`, top: `${y * 100}%`, color: accent, font: `1000 142px/1 ${FONT}`, WebkitTextStroke: "8px #111", paintOrder: "stroke", transform: `translate(-50%, -50%) rotate(12deg) scale(${interpolate(p, [0, 1], [.1, 1])})`, textShadow: "10px 12px 0 #fff" }}>{symbol}</div>
      {[0, 1, 2].map((index) => <div key={index} style={{ position: "absolute", left: `${10 + index * 12}%`, top: `${22 + index * 7}%`, width: 90, height: 14, borderRadius: 12, background: index % 2 ? "white" : accent, transform: `rotate(${-35 + index * 18}deg) scaleX(${p})`, transformOrigin: "right" }} />)}
      <Finish accent={accent} grain={0.08} vignette={0.42} />
    </AbsoluteFill>
  );
};

export const TornPaperFrame: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const images = getImages(props);
  const p = spring({ frame, fps, config: { damping: 16, stiffness: 150 } });
  if (!images[0]) return <EmptyHint />;
  const paperShape = "polygon(1% 4%,8% 1%,15% 5%,23% 2%,31% 5%,40% 1%,49% 4%,58% 1%,67% 5%,76% 2%,85% 5%,98% 1%,96% 12%,99% 22%,96% 33%,99% 44%,96% 55%,99% 66%,96% 77%,99% 88%,96% 99%,86% 96%,76% 99%,66% 96%,56% 99%,46% 96%,36% 99%,26% 96%,16% 99%,2% 96%,5% 85%,1% 74%,4% 63%,1% 52%,4% 41%,1% 30%,4% 19%)";
  return (
    <AbsoluteFill style={{ background: "#111", overflow: "hidden" }}>
      <Media src={images[0]} style={{ filter: "brightness(.48) blur(8px) saturate(.7)", transform: "scale(1.12)" }} />
      <div style={{ position: "absolute", inset: "7%", padding: Number(props.border_width || 18), background: String(props.accent_color || "#fff"), clipPath: paperShape, filter: "drop-shadow(0 22px 36px rgba(0,0,0,.55))", transform: `rotate(${interpolate(p, [0, 1], [-3, 0])}deg) scale(${interpolate(p, [0, 1], [.72, 1])})`, opacity: p }}>
        <div style={{ width: "100%", height: "100%", overflow: "hidden", clipPath: paperShape }}><Media src={images[0]} style={{ transform: `scale(${1.08 + frame / (fps * 180)})`, filter: "contrast(1.08) saturate(1.18)" }} /></div>
      </div>
      <Finish accent="#E60012" grain={0.11} vignette={0.36} />
    </AbsoluteFill>
  );
};

export const GridMemory: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const images = getImages(props);
  if (!images[0]) return <EmptyHint />;
  const line = "rgba(8,8,8,.72)";
  return (
    <AbsoluteFill style={{ background: "#050505", overflow: "hidden" }}>
      <Media src={images[0]} style={{ transform: `scale(${1.02 + Math.min(frame, 40) * .0026})`, filter: "contrast(1.08) saturate(1.2)" }} />
      {[1, 2].map((index) => <div key={`v-${index}`} style={{ position: "absolute", top: 0, bottom: 0, left: `${index * 33.333}%`, width: 5, background: line, boxShadow: "0 0 10px rgba(255,255,255,.2)" }} />)}
      {[1, 2].map((index) => <div key={`h-${index}`} style={{ position: "absolute", left: 0, right: 0, top: `${index * 33.333}%`, height: 5, background: line, boxShadow: "0 0 10px rgba(255,255,255,.2)" }} />)}
      <AbsoluteFill style={{ border: `10px solid ${getAccent(props)}99`, boxSizing: "border-box", opacity: interpolate(frame, [0, 7, 16], [0, .8, .25], { extrapolateRight: "clamp" }) }} />
      <Finish accent={getAccent(props)} grain={0.13} vignette={0.38} />
    </AbsoluteFill>
  );
};

export const PanelFoldReveal: React.FC<MotionProps> = (props) => {
  const frame = useCurrentFrame();
  const images = getImages(props);
  if (!images[0]) return <EmptyHint />;
  const duration = Math.max(1, Number(props.durationInFrames || 36));
  const panels = [
    "polygon(0 0,50% 0,25% 50%)",
    "polygon(50% 0,100% 0,75% 50%)",
    "polygon(0 0,25% 50%,0 100%)",
    "polygon(100% 0,100% 100%,75% 50%)",
    "polygon(0 100%,25% 50%,50% 100%)",
    "polygon(50% 100%,75% 50%,100% 100%)",
    "polygon(25% 50%,50% 0,75% 50%,50% 100%)",
  ];
  return (
    <AbsoluteFill style={{ background: "#130607", overflow: "hidden" }}>
      <Media src={images[0]} style={{ filter: "brightness(.28) saturate(.8)", transform: "scale(1.08)" }} />
      {panels.map((clipPath, index) => {
        const start = index * 2;
        const p = interpolate(frame, [start, Math.min(duration - 1, start + 12)], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.out(Easing.cubic),
        });
        const direction = index % 2 === 0 ? -1 : 1;
        return (
          <AbsoluteFill
            key={clipPath}
            style={{
              clipPath,
              opacity: p,
              transform: `perspective(1100px) rotateY(${direction * (1 - p) * 82}deg) scale(${.82 + p * .18})`,
              transformOrigin: "50% 50%",
              filter: `brightness(${.7 + p * .3}) saturate(1.2)`,
            }}
          >
            <Media src={images[0]} />
          </AbsoluteFill>
        );
      })}
      <Finish accent={getAccent(props)} grain={0.08} vignette={0.3} />
    </AbsoluteFill>
  );
};

const advancedComponents: Record<string, React.FC<MotionProps>> = {
  focus_blur_resolve: FocusBlurResolve,
  kinetic_warp: KineticWarp,
  mask_reveal_up: MaskRevealUp,
  rgb_glitch_text: RGBGlitchText,
  broll_stack: BrollStack,
  split_screen_burst: SplitScreenBurst,
  parallax_photo: ParallaxPhoto,
  polaroid_collage: PolaroidCollage,
  beat_montage: BeatMontage,
  hero_push_in: HeroPushIn,
  cinematic_grain: CinematicGrainScene,
  neon_light_rays: NeonLightRays,
  echo_stack: EchoStack,
  doodle_pop: DoodlePop,
  torn_paper_frame: TornPaperFrame,
  grid_memory: GridMemory,
  panel_fold_reveal: PanelFoldReveal,
};

for (const [name, component] of Object.entries(advancedComponents)) {
  registerComponent(name, component as React.FC<Record<string, unknown>>);
}

export const ADVANCED_COMPONENT_NAMES = Object.keys(advancedComponents);
