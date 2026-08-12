import { z } from "zod";

// Mirrors trendstealer.render.props.RenderProps (Python). Keep these two in
// sync by hand — tests/golden/*.json is parsed against this schema in CI as
// the drift guard between the Python and TypeScript halves of the contract.

export const wordTimingSchema = z.object({
  word: z.string(),
  start: z.number().nonnegative(),
  end: z.number().nonnegative(),
});

export const videoPropsSchema = z.object({
  onScreenHook: z.string(),
  captions: z.array(wordTimingSchema),
  voiceoverStaticPath: z.string(),
  durationSecs: z.number().positive(),
  brandName: z.string(),
  palette: z.array(z.string()),
  brollStaticPaths: z.array(z.string()).default([]),
});

export type WordTiming = z.infer<typeof wordTimingSchema>;
export type VideoProps = z.infer<typeof videoPropsSchema>;

export const smokeTestPropsSchema = z.object({
  label: z.string().default("smoke test"),
});

export type SmokeTestProps = z.infer<typeof smokeTestPropsSchema>;
