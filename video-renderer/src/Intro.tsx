import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { IntroProps } from "./types";

// A still image cannot go through OffthreadVideo (that is for video
// b-roll), so the intro uses <Img> with a slow Ken Burns push -- a static
// frame held for five seconds reads as a broken render otherwise.
export const Intro: React.FC<IntroProps & { palette: string[] }> = ({
  imageStaticPath,
  title,
  voiceoverStaticPath,
  durationSecs,
  palette,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const totalFrames = Math.max(1, Math.ceil(durationSecs * fps));

  const scale = interpolate(frame, [0, totalFrames], [1.0, 1.12], {
    extrapolateRight: "clamp",
  });
  // Fade the last 0.4s so the cut into the main body isn't jarring.
  const fadeFrames = Math.min(Math.ceil(0.4 * fps), totalFrames);
  const opacity = interpolate(
    frame,
    [totalFrames - fadeFrames, totalFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const bg = palette[0] ?? "#111111";
  const fg = palette[1] ?? "#F5F5F5";
  const accent = palette[2] ?? "#FF5A1F";

  return (
    <AbsoluteFill style={{ backgroundColor: bg, opacity }}>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <Img
          src={staticFile(imageStaticPath)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${scale})`,
          }}
        />
      </AbsoluteFill>

      {/* Scrim so the title stays legible over any photo. */}
      <AbsoluteFill
        style={{
          background: "linear-gradient(to bottom, rgba(0,0,0,0.55), rgba(0,0,0,0.15) 45%, rgba(0,0,0,0.75))",
        }}
      />

      {voiceoverStaticPath ? <Audio src={staticFile(voiceoverStaticPath)} /> : null}

      <AbsoluteFill
        style={{ justifyContent: "center", alignItems: "center", padding: 64 }}
      >
        <div
          style={{
            fontSize: 96,
            fontWeight: 900,
            color: fg,
            textAlign: "center",
            lineHeight: 1.05,
            textShadow: "0 6px 24px rgba(0,0,0,0.8)",
            fontFamily: "sans-serif",
            textTransform: "uppercase",
            letterSpacing: -2,
          }}
        >
          {title}
        </div>
        <div
          style={{
            marginTop: 32,
            width: 160,
            height: 10,
            borderRadius: 5,
            backgroundColor: accent,
          }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
