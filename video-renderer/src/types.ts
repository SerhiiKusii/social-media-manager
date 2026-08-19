import { z } from "zod";

// Mirrors trendstealer.render.props.RenderProps (Python). Keep these two in
// sync by hand — tests/golden/*.json is parsed against this schema in CI as
// the drift guard between the Python and TypeScript halves of the contract.

export const wordTimingSchema = z.object({
  word: z.string(),
  start: z.number().nonnegative(),
  end: z.number().nonnegative(),
});

// An optional lead-in shown before the main body: one still image with a
// slow Ken Burns push, a title card, and its own short voiceover. The
// main segment's captions/timings stay relative to the main voiceover, so
// the intro is additive -- durationSecs below is the MAIN duration, and
// total runtime is introDurationSecs + durationSecs.
export const introSchema = z.object({
  imageStaticPath: z.string(),
  title: z.string(),
  voiceoverStaticPath: z.string().default(""),
  durationSecs: z.number().positive(),
});

export const videoPropsSchema = z.object({
  onScreenHook: z.string(),
  captions: z.array(wordTimingSchema),
  voiceoverStaticPath: z.string(),
  durationSecs: z.number().positive(),
  brandName: z.string(),
  palette: z.array(z.string()),
  brollStaticPaths: z.array(z.string()).default([]),
  intro: introSchema.nullable().default(null),
});

export type IntroProps = z.infer<typeof introSchema>;

export type WordTiming = z.infer<typeof wordTimingSchema>;
export type VideoProps = z.infer<typeof videoPropsSchema>;

export const smokeTestPropsSchema = z.object({
  label: z.string().default("smoke test"),
});

export type SmokeTestProps = z.infer<typeof smokeTestPropsSchema>;
