import assert from "node:assert/strict";
import { test } from "node:test";
import { buildBrollSegments } from "./broll";

const FPS = 30;

const totalCovered = (segments: { from: number; durationInFrames: number }[]) =>
  segments.reduce((max, s) => Math.max(max, s.from + s.durationInFrames), 0);

test("tiles a short clip to cover a much longer body", () => {
  // The actual bug: a 6s clip under a 36s body left ~30s frozen.
  const bodyFrames = 36 * FPS;
  const segments = buildBrollSegments(["a.mp4"], [6], bodyFrames, FPS);

  assert.equal(segments.length, 6);
  assert.equal(totalCovered(segments), bodyFrames);
});

test("leaves no gap between consecutive segments", () => {
  const bodyFrames = 40 * FPS;
  const segments = buildBrollSegments(["a.mp4", "b.mp4"], [6, 9.7], bodyFrames, FPS);

  let expectedFrom = 0;
  for (const segment of segments) {
    assert.equal(segment.from, expectedFrom);
    expectedFrom += segment.durationInFrames;
  }
});

test("cycles through the available clips in order", () => {
  const segments = buildBrollSegments(["a.mp4", "b.mp4", "c.mp4"], [2, 2, 2], 12 * FPS, FPS);
  assert.deepEqual(
    segments.map((s) => s.src),
    ["a.mp4", "b.mp4", "c.mp4", "a.mp4", "b.mp4", "c.mp4"],
  );
});

test("never overruns the body -- the last repeat is truncated", () => {
  const bodyFrames = 10 * FPS;
  const segments = buildBrollSegments(["a.mp4"], [4], bodyFrames, FPS);

  assert.equal(totalCovered(segments), bodyFrames);
  const last = segments[segments.length - 1]!;
  assert.ok(last.durationInFrames < 4 * FPS, "final segment should be clipped short");
});

test("falls back to a single stretched clip when durations are unknown", () => {
  // ffprobe failure, or a props file written before brollDurationsSecs
  // existed. Showing one clip is the old behaviour; a blank screen is not.
  const bodyFrames = 30 * FPS;
  const segments = buildBrollSegments(["a.mp4"], [], bodyFrames, FPS);

  assert.deepEqual(segments, [{ src: "a.mp4", from: 0, durationInFrames: bodyFrames }]);
});

test("ignores clips whose duration is zero", () => {
  const segments = buildBrollSegments(["bad.mp4", "good.mp4"], [0, 5], 10 * FPS, FPS);
  assert.ok(
    segments.every((s) => s.src === "good.mp4"),
    "a clip with unknown duration must not be tiled",
  );
});

test("returns nothing when there is no b-roll at all", () => {
  assert.deepEqual(buildBrollSegments([], [], 30 * FPS, FPS), []);
});
