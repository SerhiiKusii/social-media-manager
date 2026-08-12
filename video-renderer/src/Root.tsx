import React from "react";
import { Composition } from "remotion";
import { MainVideo } from "./MainVideo";
import { SmokeTest } from "./SmokeTest";
import { smokeTestPropsSchema, videoPropsSchema } from "./types";

const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="MainVideo"
        component={MainVideo}
        durationInFrames={30 * FPS}
        fps={FPS}
        width={1080}
        height={1920}
        schema={videoPropsSchema}
        defaultProps={{
          onScreenHook: "Wait for it...",
          captions: [],
          voiceoverStaticPath: "",
          durationSecs: 30,
          brandName: "Acme",
          palette: ["#111111", "#F5F5F5", "#FF5A1F"],
          brollStaticPaths: [],
        }}
        calculateMetadata={async ({ props }) => ({
          durationInFrames: Math.max(1, Math.ceil(props.durationSecs * FPS)),
        })}
      />
      <Composition
        id="SmokeTest"
        component={SmokeTest}
        durationInFrames={60}
        fps={FPS}
        width={1080}
        height={1920}
        schema={smokeTestPropsSchema}
        defaultProps={{ label: "smoke test" }}
      />
    </>
  );
};
