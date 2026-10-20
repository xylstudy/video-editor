import React from "react";
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { registerComponent } from "./registry";

type EffectTrack = {
  start: number;
  end: number;
  type: string;
  component?: string;
  parameters?: Record<string, unknown>;
};

const font = "Inter, PingFang SC, Microsoft YaHei, sans-serif";

const GlassPill: React.FC<{
  delay: number;
  x: number;
  y: number;
  width: number;
  children: React.ReactNode;
}> = ({ delay, x, y, width, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 16, stiffness: 130, mass: 0.7 } });
  return (
    <div
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        width,
        padding: "18px 20px",
        borderRadius: 24,
        color: "white",
        background: "linear-gradient(145deg, rgba(24,27,34,.82), rgba(8,10,15,.62))",
        border: "1px solid rgba(255,255,255,.24)",
        boxShadow: "0 18px 55px rgba(0,0,0,.42)",
        backdropFilter: "blur(18px)",
        opacity: p,
        transform: `translate3d(${interpolate(p, [0, 1], [70, 0])}px, ${interpolate(p, [0, 1], [35, 0])}px, 0) rotateY(${interpolate(p, [0, 1], [-24, -7])}deg) scale(${interpolate(p, [0, 1], [.72, 1])})`,
        fontFamily: font,
      }}
    >
      {children}
    </div>
  );
};

export const FloatingMusicUIOverlay: React.FC<Record<string, unknown>> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const title = String(props.track_title || props.title || "正在播放 · 城市漫游");
  const artist = String(props.artist || "Ato Radio");
  const drift = Math.sin(frame / (fps * 0.65)) * 7;
  const base = spring({ frame, fps, config: { damping: 18, stiffness: 105 } });
  const split = spring({ frame: frame - Math.round(fps * 1.35), fps, config: { damping: 16, stiffness: 135 } });

  return (
    <AbsoluteFill style={{ pointerEvents: "none", perspective: 1200, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          left: "8%",
          top: "18%",
          width: "54%",
          padding: "22px 24px",
          borderRadius: 25,
          color: "white",
          background: "linear-gradient(145deg, rgba(17,20,27,.88), rgba(7,9,14,.68))",
          border: "1px solid rgba(255,255,255,.22)",
          boxShadow: "0 24px 70px rgba(0,0,0,.48)",
          backdropFilter: "blur(20px)",
          opacity: base,
          transform: `translate3d(0, ${drift}px, 0) rotateY(-8deg) rotateZ(-1.5deg) scale(${interpolate(base, [0, 1], [.82, 1])})`,
          transformOrigin: "left center",
          fontFamily: font,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ width: 62, height: 62, borderRadius: 15, background: "linear-gradient(135deg,#f0f0f0,#878f9e)", display: "grid", placeItems: "center", color: "#111", fontSize: 30 }}>♫</div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 25, fontWeight: 750, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{title}</div>
            <div style={{ marginTop: 5, fontSize: 18, opacity: .62 }}>{artist}</div>
          </div>
        </div>
        <div style={{ marginTop: 19, height: 3, background: "rgba(255,255,255,.22)", borderRadius: 3 }}>
          <div style={{ width: `${22 + ((frame * 0.62) % 65)}%`, height: "100%", background: "white", borderRadius: 3 }} />
        </div>
        <div style={{ display: "flex", justifyContent: "center", gap: 34, marginTop: 18, fontSize: 28, alignItems: "center" }}>
          <span>‹‹</span><span style={{ fontSize: 38 }}>▶</span><span>››</span>
        </div>
      </div>

      <div style={{ opacity: split }}>
        <GlassPill delay={Math.round(fps * 1.30)} x={67} y={18} width={92}><div style={{ fontSize: 28 }}>☀</div><div style={{ height: 78, width: 8, margin: "10px auto 0", borderRadius: 8, background: "linear-gradient(#fff 52%,rgba(255,255,255,.2) 52%)" }} /></GlassPill>
        <GlassPill delay={Math.round(fps * 1.47)} x={80} y={22} width={92}><div style={{ fontSize: 28 }}>♪</div><div style={{ height: 78, width: 8, margin: "10px auto 0", borderRadius: 8, background: "linear-gradient(#fff 68%,rgba(255,255,255,.2) 68%)" }} /></GlassPill>
        <GlassPill delay={Math.round(fps * 1.67)} x={65} y={43} width={170}><div style={{ fontSize: 18, fontWeight: 700 }}>专注模式</div><div style={{ fontSize: 15, opacity: .58, marginTop: 6 }}>沉浸播放</div></GlassPill>
      </div>
    </AbsoluteFill>
  );
};

const MediaLayer: React.FC<{ src: string }> = ({ src }) => {
  if (!src) return <AbsoluteFill style={{ background: "#090b12" }} />;
  const isVideo = /\.(mp4|mov|webm|avi|mkv)(\?|$)/i.test(src);
  const style: React.CSSProperties = { width: "100%", height: "100%", objectFit: "cover" };
  return isVideo ? <OffthreadVideo muted src={src} style={style} /> : <Img src={src} style={style} />;
};

export const FloatingMusicUIScene: React.FC<Record<string, unknown>> = (props) => (
  <AbsoluteFill>
    <MediaLayer src={String(props.imagePath || props.src || "")} />
    <FloatingMusicUIOverlay {...props} />
  </AbsoluteFill>
);

export const SearchCTACard: React.FC<Record<string, unknown>> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - 4, fps, config: { damping: 18, stiffness: 105 } });
  const query = String(props.query || props.search_text || "继续探索下一段旅程");
  const platform = String(props.platform || "抖音");
  return (
    <AbsoluteFill style={{ background: "radial-gradient(circle at 20% 80%,#0f777366,transparent 42%), radial-gradient(circle at 90% 20%,#702b7355,transparent 45%), linear-gradient(145deg,#11182a,#05070d)", color: "white", fontFamily: font, alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: "78%", border: "1px solid rgba(255,255,255,.35)", borderRadius: 30, padding: "54px 46px", background: "rgba(8,12,22,.43)", backdropFilter: "blur(20px)", boxShadow: "0 30px 90px rgba(0,0,0,.38)", opacity: p, transform: `translateY(${interpolate(p, [0, 1], [70, 0])}px) scale(${interpolate(p, [0, 1], [.9, 1])})` }}>
        <div style={{ textAlign: "center", fontSize: 27, opacity: .72 }}>大家都在</div>
        <div style={{ textAlign: "center", marginTop: 8, fontSize: 50, fontWeight: 900 }}>♪ {platform}</div>
        <div style={{ marginTop: 38, height: 66, borderRadius: 33, background: "white", color: "#171a20", display: "flex", alignItems: "center", padding: "0 25px", gap: 16, fontSize: 23 }}><span>⌕</span><span style={{ flex: 1 }}>{query}</span><span>搜索</span></div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 55 }}>
          <div style={{ fontSize: 19, lineHeight: 1.8, opacity: .68 }}><div>▣ 收藏这段旅程</div><div>↗ 分享给同行的人</div></div>
          <div style={{ width: 118, height: 118, background: "repeating-conic-gradient(#111 0 8deg,#fff 8deg 16deg)", border: "9px solid white", borderRadius: 12, boxShadow: "0 8px 24px #0008" }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

const GlitchBlocksOverlay: React.FC = () => {
  const frame = useCurrentFrame();
  const shift = (frame % 4) * 18;
  const blocks = [
    { top: 7, left: -8, width: 73, height: 13 },
    { top: 26, left: 29, width: 77, height: 9 },
    { top: 45, left: -4, width: 58, height: 17 },
    { top: 68, left: 38, width: 68, height: 11 },
    { top: 84, left: 5, width: 82, height: 8 },
  ];
  return (
    <AbsoluteFill style={{ pointerEvents: "none", overflow: "hidden", background: frame % 3 === 0 ? "rgba(255,255,255,.18)" : "transparent" }}>
      {blocks.map((block, index) => (
        <React.Fragment key={index}>
          <div style={{ position: "absolute", ...block, left: `${block.left + shift / 5}%`, top: `${block.top}%`, width: `${block.width}%`, height: `${block.height}%`, background: "rgba(255,20,70,.52)", mixBlendMode: "screen", transform: `translateX(${-12 - shift}px) skewX(-12deg)`, filter: "contrast(1.8)" }} />
          <div style={{ position: "absolute", ...block, left: `${block.left + shift / 7}%`, top: `${block.top + 1}%`, width: `${block.width}%`, height: `${block.height}%`, background: "rgba(0,225,255,.55)", mixBlendMode: "screen", transform: `translateX(${12 + shift}px) skewX(12deg)`, filter: "contrast(1.8)" }} />
        </React.Fragment>
      ))}
      <AbsoluteFill style={{ background: "repeating-linear-gradient(0deg, transparent 0 5px, rgba(255,255,255,.16) 6px 7px)", mixBlendMode: "overlay" }} />
    </AbsoluteFill>
  );
};

const BlackDipOverlay: React.FC<{ frames: number }> = ({ frames }) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, Math.max(0, frame / Math.max(1, frames - 1)));
  return <AbsoluteFill style={{ pointerEvents: "none", background: "black", opacity: Math.sin(progress * Math.PI) }} />;
};

const ForegroundSilhouetteOverlay: React.FC<{ frames: number }> = ({ frames }) => {
  const frame = useCurrentFrame();
  const x = interpolate(frame, [0, Math.max(1, frames - 1)], [-32, 112]);
  const y = 22 + Math.sin(frame / 9) * 4;
  return (
    <div
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        width: "28%",
        height: "14%",
        background: "rgba(4,5,7,.9)",
        clipPath: "polygon(0 52%,34% 40%,46% 0,54% 0,66% 40%,100% 52%,66% 63%,58% 100%,42% 100%,34% 63%)",
        filter: "drop-shadow(0 8px 12px rgba(0,0,0,.35))",
        transform: `rotate(${-8 + Math.sin(frame / 12) * 4}deg)`,
        pointerEvents: "none",
      }}
    />
  );
};

export const ReferenceEffectTracks: React.FC<{ tracks?: EffectTrack[] }> = ({ tracks = [] }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {tracks.map((track, index) => {
        const start = Math.max(0, Math.round(Number(track.start || 0) * fps));
        const end = Math.max(start + 1, Math.round(Number(track.end || 0) * fps));
        const kind = track.component || track.type;
        let overlay: React.ReactNode = null;
        if (kind === "floating_music_ui") overlay = <FloatingMusicUIOverlay {...(track.parameters || {})} />;
        if (kind === "glitch_reveal") overlay = <GlitchBlocksOverlay />;
        if (kind === "black_dip") overlay = <BlackDipOverlay frames={end - start} />;
        if (kind === "foreground_silhouette") overlay = <ForegroundSilhouetteOverlay frames={end - start} />;
        if (!overlay) return null;
        return (
          <Sequence key={`${track.type}-${index}`} from={start} durationInFrames={end - start}>
            {overlay}
          </Sequence>
        );
      })}
    </>
  );
};

registerComponent("floating_music_ui", FloatingMusicUIScene as React.FC<Record<string, unknown>>);
registerComponent("search_cta_card", SearchCTACard as React.FC<Record<string, unknown>>);
