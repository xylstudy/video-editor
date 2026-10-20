import { Composition } from "remotion";
import { VideoSchemeComposition } from "./VideoScheme";
import type { RenderInput } from "./types/schema";
// 注册所有动态组件（含 LLM 生成的自定义组件）
import "./dynamic/index";
// Stable, hand-authored motion recipes available to scheme.json via custom:{name}.
import "./components/AdvancedMotion";
import "./components/ReferenceEffects";
import { KenBurnsTestSuite } from "./KenBurnsTest";
import { EffectsShowcase } from "./EffectsShowcase";
import { BeijingVlog } from "./BeijingVlog";
import { ForegroundSplitShowcase } from "./ForegroundSplit";
import { BeijingVlogSegmented } from "./BeijingVlogSegmented";
import { VlogTechniquesShowcase } from "./VlogTechniquesShowcase";
import { BeijingVlogVariety, BEIJING_VARIETY_DURATION } from "./BeijingVlogVariety";
import { TechniqueDemo, getDemoDuration, type TechniqueDemoProps } from "./TechniqueDemo";
import { CinematicDemo, CINEMATIC_DEMO_DURATION } from "./CinematicDemo";

const fps = 30;

function calcDurationInFrames(props: Record<string, unknown>): number {
  const scheme = (props as unknown as RenderInput).scheme;
  if (!scheme?.storyboard?.length) return 30 * 60;

  const totalSec = scheme.storyboard.reduce(
    (acc, f) => acc + (f.duration ?? 3),
    0
  );
  return Math.max(30, Math.ceil(totalSec * fps));
}

const defaultProps: RenderInput = {
  scheme: {
    id: "default",
    title: "Vlog",
    target_topic: "",
    target_duration: 60,
    structure_type: "",
    storyboard: [],
    total_duration: 60,
  },
  material_map: {},
};

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="VideoScheme"
        component={VideoSchemeComposition as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={30 * 60}
        fps={fps}
        width={1080}
        height={1920}
        defaultProps={defaultProps as unknown as Record<string, unknown>}
        calculateMetadata={({ props }) => {
          const scheme = (props as unknown as RenderInput).scheme;
          return {
            durationInFrames: calcDurationInFrames(props),
            width: scheme?.canvas_width || 1080,
            height: scheme?.canvas_height || 1920,
            props,
          };
        }}
      />
      <Composition
        id="KenBurnsTest"
        component={KenBurnsTestSuite}
        durationInFrames={240}
        fps={fps}
        width={1080}
        height={1920}
      />
      <Composition
        id="EffectsShowcase"
        component={EffectsShowcase}
        durationInFrames={270}
        fps={fps}
        width={1080}
        height={1920}
      />
      <Composition
        id="BeijingVlog"
        component={BeijingVlog as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={315}
        fps={fps}
        width={1080}
        height={1920}
        defaultProps={{ material_map: {} }}
      />
      <Composition
        id="ForegroundSplit"
        component={ForegroundSplitShowcase as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={30 + 10 * 60 + 30}
        fps={fps}
        width={1080}
        height={1920}
        defaultProps={{ material_map: {} }}
      />
      <Composition
        id="BeijingVlogSegmented"
        component={BeijingVlogSegmented as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={30 + 12 * 50 + 50 + 35 + 30}
        fps={fps}
        width={1080}
        height={1920}
      />
      <Composition
        id="VlogTechniquesShowcase"
        component={VlogTechniquesShowcase as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={30 + 10 * 45 + 45 + 30 + 30}
        fps={fps}
        width={1080}
        height={1920}
      />
      <Composition
        id="BeijingVlogVariety"
        component={BeijingVlogVariety as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={BEIJING_VARIETY_DURATION}
        fps={fps}
        width={1080}
        height={1920}
      />
      {/* 知识库单条技法演示：540x960 小尺寸，DesignFrame 内部按 1080x1920 设计坐标渲染 */}
      <Composition
        id="TechniqueDemo"
        component={TechniqueDemo as unknown as React.FC<Record<string, unknown>>}
        durationInFrames={80}
        fps={fps}
        width={540}
        height={960}
        defaultProps={{ kind: "transition", tech_id: "fade", title: "淡入" } as TechniqueDemoProps as unknown as Record<string, unknown>}
        calculateMetadata={({ props }) => ({
          durationInFrames: getDemoDuration((props as unknown as TechniqueDemoProps).kind),
          props,
        })}
      />
      {/* 进阶特效示范：粒子 / 真实运动模糊 / 卡点爆发 */}
      <Composition
        id="CinematicDemo"
        component={CinematicDemo}
        durationInFrames={CINEMATIC_DEMO_DURATION}
        fps={fps}
        width={1080}
        height={1920}
      />
    </>
  );
};
