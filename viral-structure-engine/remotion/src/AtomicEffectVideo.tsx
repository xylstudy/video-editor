import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { FloatingMusicUIOverlay, ReferenceEffectTracks, SearchCTACard } from "./components/ReferenceEffects";
import { FilmGrain } from "./components/Effects";

type Point = { frame: number; x: number; y: number; width: number; height: number };
export type AtomicEffect = {
  key: string; parameters: Record<string, unknown>; tracks: Point[];
  tracking_method: string; source_start?: number;
  cutout?: { src: string; box: { x: number; y: number; width: number; height: number } };
};

/** A real source video with one explicitly implemented technique. */
export const AtomicEffectVideo: React.FC<{ src: string; effect: AtomicEffect }> = ({ src, effect }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - 3, fps, config: { damping: 12, stiffness: 180 } });
  const times = effect.tracks.map(point => point.frame);
  const coordinate = (name: "x" | "y" | "width") => effect.tracks.length > 1
    ? interpolate(frame, times, effect.tracks.map(point => point[name]), { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : effect.tracks[0]?.[name] || .5;
  const x = coordinate("x") * 1080;
  const y = coordinate("y") * 1920;
  const width = Math.min(360, Math.max(180, coordinate("width") * 1080 * .8));
  const key = effect.key;
  const cutout = effect.cutout;
  const cutoutStyle: React.CSSProperties = cutout ? { position: "absolute", left: (1 - cutout.box.width) * 540, top: (1 - cutout.box.height) * 960,
    width: cutout.box.width * 1080, height: cutout.box.height * 1920 } : {};
  return <AbsoluteFill style={{ overflow: "hidden", background: "#111" }}>
    <OffthreadVideo src={staticFile(src)} startFrom={effect.source_start || 0} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    {key === "sticker_face" && <svg viewBox="0 0 240 160" style={{ position: "absolute", left: x, top: y, width, transform: `translate(-50%,-50%) scale(${p})`, overflow: "visible" }}>
      <ellipse cx="69" cy="55" rx="32" ry="43" fill="white" stroke="#251b24" strokeWidth="5" transform="rotate(-9 69 55)" />
      <ellipse cx="167" cy="55" rx="32" ry="43" fill="white" stroke="#251b24" strokeWidth="5" transform="rotate(9 167 55)" />
      <ellipse cx={73 + Math.sin(frame / 16) * 7} cy="65" rx="13" ry="23" fill="#17131d" />
      <ellipse cx={163 + Math.sin(frame / 16) * 7} cy="65" rx="13" ry="23" fill="#17131d" />
      <path d="M72 117 Q120 164 170 117 Q120 138 72 117" fill="#c23047" stroke="#fff" strokeWidth="6" strokeLinejoin="round" />
    </svg>}
    {["sticker_stars", "sticker_anger", "sticker_doodle"].includes(key) && <div style={{ position: "absolute", left: x, top: Math.max(180, y - 70), width: 360, height: 160, transform: `translate(-50%,-70%) scale(${p})` }}>
      {[0, 1, 2].map(index => <svg key={index} viewBox="0 0 90 90" style={{ position: "absolute", width: 96, left: index * 123, top: 12 + Math.sin(frame / 7 + index * 2) * 18, transform: `rotate(${-20 + index * 22}deg)` }}>
        <path d="M12 14 Q34 17 32 34 Q16 35 14 57 M76 13 Q55 17 57 35 Q73 37 77 56 M14 75 Q33 71 34 55 Q53 55 57 75" fill="none" stroke="white" strokeWidth="16" strokeLinecap="round" />
        <path d="M12 14 Q34 17 32 34 Q16 35 14 57 M76 13 Q55 17 57 35 Q73 37 77 56 M14 75 Q33 71 34 55 Q53 55 57 75" fill="none" stroke="#17151c" strokeWidth="8" strokeLinecap="round" />
      </svg>)}
    </div>}
    {key === "sticker_arrow" && <svg viewBox="0 0 140 170" style={{ position: "absolute", left: x - 20, top: y - 20, width: 150, transform: `scale(${p}) rotate(-18deg)`, transformOrigin: "10px 5px", filter: "drop-shadow(0 7px 4px #0008)" }}>
      <path d="M10 5 L20 140 L52 106 L84 159 L109 144 L76 93 L126 90 Z" fill="white" stroke="#16151c" strokeWidth="7" strokeLinejoin="round" />
    </svg>}
    {key === "sticker_pop" && <svg viewBox="0 0 260 260" style={{ position: "absolute", left: "50%", top: "43%", width: 280, transform: `translate(-50%,-50%) scale(${p}) rotate(${Math.sin(frame / 15) * 4}deg)`, filter: "drop-shadow(0 12px 10px #0007)" }}>
      <polygon points="78,7 182,7 253,78 253,182 182,253 78,253 7,182 7,78" fill="#df2536" stroke="white" strokeWidth="12" />
      <text x="130" y="178" textAnchor="middle" fill="white" fontSize="143" fontWeight="900" fontFamily="Microsoft YaHei">停</text>
    </svg>}
    {key === "grid_overlay" && <AbsoluteFill style={{ opacity: p }}>
      {[1, 2].map(index => <React.Fragment key={index}>
        <div style={{ position: "absolute", left: `${index * 100 / 3}%`, top: 0, bottom: 0, width: 5, background: "#111", boxShadow: "0 0 0 1px #fff8" }} />
        <div style={{ position: "absolute", top: `${index * 100 / 3}%`, left: 0, right: 0, height: 5, background: "#111", boxShadow: "0 0 0 1px #fff8" }} />
      </React.Fragment>)}
    </AbsoluteFill>}
    {key === "floating_music_ui" && <FloatingMusicUIOverlay {...effect.parameters} />}
    {key === "foreground_silhouette" && <Sequence from={6} durationInFrames={110}><ReferenceEffectTracks tracks={[{ start: 0, end: 110 / fps, type: "foreground_silhouette" }]} /></Sequence>}
    {key === "glitch_reveal" && <ReferenceEffectTracks tracks={[.2, 1.6, 3].map(start => ({ start, end: start + .7, type: "glitch_reveal" }))} />}
    {key === "film_grain" && <><FilmGrain opacity={.23} /><AbsoluteFill style={{ boxShadow: "inset 0 0 190px #0008" }} /></>}
    {key === "search_cta_card" && <Sequence from={25} durationInFrames={95}><SearchCTACard {...effect.parameters} /></Sequence>}
    {cutout && ["torn_paper_outline", "subject_outline"].includes(key) && <>
      <svg style={{ width: 0, height: 0 }}><filter id="paper-edge"><feTurbulence type="fractalNoise" baseFrequency=".035" numOctaves="2" seed="7" /><feDisplacementMap in="SourceGraphic" scale="7" /></filter></svg>
      <div style={{ ...cutoutStyle, transform: `scale(${1 + p * .08}) rotate(${Math.sin(frame / 25) * 2}deg)`, opacity: p,
        filter: "drop-shadow(12px 0 white) drop-shadow(-12px 0 white) drop-shadow(0 12px white) drop-shadow(0 -12px white) drop-shadow(0 15px 8px #0007)" }}>
        <Img src={staticFile(cutout.src)} style={{ width: "100%", height: "100%", filter: key === "torn_paper_outline" ? "url(#paper-edge)" : undefined }} />
      </div>
    </>}
    {cutout && key === "subject_echo" && [1, 2, 3, 4].map(index => <Img key={index} src={staticFile(cutout.src)} style={{ ...cutoutStyle,
      opacity: p * Math.pow(.72, index), transform: `translate(${-index * (36 + Math.sin(frame / 13) * 18)}px,${index * 24}px) scale(${1 - index * .025})` }} />)}
    {cutout && key === "subject_clone" && Array.from({ length: 6 }, (_, index) => {
      const phase = (frame * 4 + index * 220) % 2150;
      const scale = .5 + index % 3 * .12;
      return <Img key={index} src={staticFile(cutout.src)} style={{ position: "absolute", width: cutout.box.width * 1080, height: cutout.box.height * 1920,
        left: 65 + index % 3 * 330, top: phase - 300, opacity: p, transform: `scale(${scale}) rotate(${index * 19 + frame / 3}deg)`, filter: "drop-shadow(0 12px 8px #0006)" }} />;
    })}
  </AbsoluteFill>;
};
