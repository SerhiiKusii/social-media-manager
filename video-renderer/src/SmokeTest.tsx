import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import type { SmokeTestProps } from "./types";

// Trivial 60-frame composition with no external assets, so CI can render
// and ffprobe-assert it fast, as the drift/regression guard for the render
// pipeline without paying for a full render every run.
export const SmokeTest: React.FC<SmokeTestProps> = ({ label }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: "#111", justifyContent: "center", alignItems: "center" }}>
      <div style={{ color: "#fff", fontSize: 48, fontFamily: "sans-serif" }}>
        {label} — frame {frame}
      </div>
    </AbsoluteFill>
  );
};
