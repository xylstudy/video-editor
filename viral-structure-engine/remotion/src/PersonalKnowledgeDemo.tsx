import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { DualTransitionLayer } from "./components/DualTransitions";
import { FilmGrain } from "./components/Effects";
import { DoodlePop, EchoStack, TornPaperFrame } from "./components/AdvancedMotion";
import { FloatingMusicUIOverlay, SearchCTACard } from "./components/ReferenceEffects";
import type { TransitionType } from "./types/schema";
import { AtomicEffectVideo, type AtomicEffect } from "./AtomicEffectVideo";

type Clip = { src: string; duration: number; role: string; effect: string; transition: TransitionType; motion?: string; playback_rate?: number; atomic?: AtomicEffect };
export type PersonalKnowledgeDemoProps = {
  title: string; knowledge_type: string; duration_frames: number; edited: Clip[];
  technique: string; grade: string; film: boolean; music_ui: boolean; search_cta: boolean;
  subtitle?: boolean; black_dip?: boolean; audio: string; source: string; reference_recut?: boolean;
};

const Footage: React.FC<{ clip: Clip; start?: number }> = ({ clip, start = 0 }) => {
  const frame = useCurrentFrame();
  if (clip.effect === "atomic" && clip.atomic) return <AtomicEffectVideo src={clip.src} effect={clip.atomic} />;
  if (clip.effect === "doodle") return <DoodlePop images={[`/${clip.src}`]} symbol="!!" position={{ x: .72, y: .23 }} accent_color="#ffcf36" durationInFrames={clip.duration} />;
  if (clip.effect === "paper") return <TornPaperFrame images={[`/${clip.src}`]} />;
  if (clip.effect === "echo") return <EchoStack images={[`/${clip.src}`]} />;
  const scale = clip.motion === "punch" ? interpolate(frame, [0, 10, 22], [1.2, 1.03, 1], { extrapolateRight: "clamp" })
    : clip.motion === "drift" ? 1.02 + Math.min(frame / clip.duration, 1) * .07 : 1;
  return <OffthreadVideo src={staticFile(clip.src)} startFrom={Math.floor(start * (clip.playback_rate || 1))} playbackRate={clip.playback_rate || 1} muted style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${scale})` }} />;
};

const BlackDip: React.FC = () => {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{ background: "black", opacity: interpolate(frame, [0, 3, 9], [1, 1, 0]) }} />;
};

const Timeline: React.FC<{ props: PersonalKnowledgeDemoProps }> = ({ props }) => {
  let offset = 0;
  const grade = props.grade === "original" ? undefined : props.grade === "film" ? "saturate(.7) contrast(1.12) sepia(.16)"
    : props.grade === "fresh" ? "saturate(1.22) contrast(.95) brightness(1.06)"
    : props.grade === "cinematic" ? "saturate(1.12) contrast(1.15)" : "saturate(1.04) sepia(.18) contrast(1.04)";
  return <AbsoluteFill style={{ overflow: "hidden" }}>
    {props.edited.map((clip, index) => {
      const from = offset;
      offset += clip.duration;
      const overlap = clip.transition === "cut" ? 0 : Math.min(12, clip.duration - 1);
      const effectName = ({ paper: "撕纸画框", doodle: "手绘涂鸦", echo: "动态重影" } as Record<string, string>)[clip.effect];
      return <Sequence key={index} from={from} durationInFrames={clip.duration} premountFor={15}>
        <AbsoluteFill style={{ filter: grade }}>
          <DualTransitionLayer transitionType={clip.transition} overlapFrames={overlap} totalDurationInFrames={clip.duration}
            currentContent={<Footage clip={clip} />}
            outgoingContent={index > 0 && overlap ? <Footage clip={{ ...props.edited[index - 1], effect: "", motion: "none" }} start={Math.max(0, props.edited[index - 1].duration - overlap)} /> : null} />
        </AbsoluteFill>
        {effectName && <div style={{ position: "absolute", left: 48, bottom: 160, fontSize: 30, color: "white", background: "#1119", padding: "9px 16px", borderRadius: 8 }}>{effectName}</div>}
        {props.subtitle && <div style={{ position: "absolute", bottom: 230, left: 80, right: 80, textAlign: "center", fontSize: 40, color: "#ffe481", textShadow: "0 2px 10px #000" }}>{["沿着光，走进这座城", "把目光交给路上的细节", "这一刻，慢慢记住"][index % 3]}</div>}
        {props.black_dip && index === Math.floor(props.edited.length / 2) && <Sequence durationInFrames={10}><BlackDip /></Sequence>}
      </Sequence>;
    })}
    {props.film && <FilmGrain opacity={.15} />}
    {props.music_ui && <Sequence durationInFrames={Math.min(210, props.duration_frames)}><FloatingMusicUIOverlay track_title="路过的每一刻" artist="技法示例 · 演示鼓点" /></Sequence>}
    {props.search_cta && <Sequence from={props.duration_frames - 45} durationInFrames={45}><SearchCTACard query="继续探索下一段旅程" platform="搜索" /></Sequence>}
  </AbsoluteFill>;
};

export const PersonalKnowledgeDemo: React.FC<PersonalKnowledgeDemoProps> = (props) => (
  <AbsoluteFill style={{ background: "#101018", fontFamily: "'Microsoft YaHei', sans-serif", color: "white", overflow: "hidden" }}>
    <Audio src={staticFile(props.audio)} volume={.65} loop />
    {/* Shared effects use 1080×1920 design coordinates, like TechniqueDemo. */}
    <div style={{ position: "absolute", width: 1080, height: 1920, transform: "scale(.5)", transformOrigin: "top left" }}>
      <Timeline props={props} />
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(#0007,transparent 15%,transparent 82%,#0009)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", top: 50, left: 48, right: 48, fontSize: 32, textShadow: "0 2px 8px #000" }}>{props.title}</div>
      <div style={{ position: "absolute", bottom: 64, left: 48, right: 48, fontSize: 30, lineHeight: 1.6, textShadow: "0 2px 8px #000" }}>{props.technique}</div>
    </div>
  </AbsoluteFill>
);
