import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { VideoProps } from "./types";

export const MainVideo: React.FC<VideoProps> = ({
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
