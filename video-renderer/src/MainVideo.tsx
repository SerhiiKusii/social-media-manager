import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Intro } from "./Intro";
import type { VideoProps } from "./types";

// The main body, unaware of any intro: its caption timings are relative
// to its own voiceover starting at frame 0. MainVideo wraps this in a
// Sequence so the intro can shift it without touching the timings.
const Body: React.FC<Omit<VideoProps, "intro">> = ({
  onScreenHook,
  captions,
  voiceoverStaticPath,
  brandName,
  palette,
  brollStaticPaths,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const activeWord = captions.find((c) => t >= c.start && t < c.end);
  const bg = palette[0] ?? "#111111";
  const fg = palette[1] ?? "#F5F5F5";

  return (
    <AbsoluteFill style={{ backgroundColor: bg }}>
      {brollStaticPaths[0] ? (
        <OffthreadVideo
          src={staticFile(brollStaticPaths[0])}
          style={{ width: "100%", height: "100%", objectFit: "cover", opacity: 0.6 }}
          muted
        />
      ) : null}

      {voiceoverStaticPath ? <Audio src={staticFile(voiceoverStaticPath)} /> : null}

      <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: 120 }}>
        <div
          style={{
            fontSize: 64,
            fontWeight: 800,
            color: fg,
            textAlign: "center",
            maxWidth: "85%",
            textShadow: "0 4px 12px rgba(0,0,0,0.6)",
            fontFamily: "sans-serif",
          }}
        >
          {onScreenHook}
        </div>
      </AbsoluteFill>

      <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 160 }}>
        <div
          style={{
            fontSize: 48,
            fontWeight: 700,
            color: fg,
            textAlign: "center",
            maxWidth: "80%",
            textShadow: "0 4px 12px rgba(0,0,0,0.6)",
            fontFamily: "sans-serif",
          }}
        >
          {activeWord?.word ?? ""}
        </div>
      </AbsoluteFill>

      <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "flex-end", padding: 24 }}>
        <div style={{ fontSize: 24, color: fg, opacity: 0.7, fontFamily: "sans-serif" }}>
          {brandName}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const MainVideo: React.FC<VideoProps> = (props) => {
  const { fps } = useVideoConfig();
  const { intro, ...body } = props;

  if (!intro) {
    return <Body {...body} />;
  }

  const introFrames = Math.max(1, Math.ceil(intro.durationSecs * fps));
  const bodyFrames = Math.max(1, Math.ceil(body.durationSecs * fps));

  return (
    <AbsoluteFill>
      <Sequence durationInFrames={introFrames}>
        <Intro {...intro} palette={body.palette} />
      </Sequence>
      <Sequence from={introFrames} durationInFrames={bodyFrames}>
        <Body {...body} />
      </Sequence>
    </AbsoluteFill>
  );
};
