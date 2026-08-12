import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { videoPropsSchema } from "./types";

// Drift guard between the Python half of the contract (props.py) and this
// zod schema: tests/unit/test_render_props.py generates/validates the same
// golden file from the Python side.
test("golden video props match the zod schema", () => {
  const raw = readFileSync(
    new URL("../../tests/golden/video_props.golden.json", import.meta.url),
    "utf-8",
  );
  const data: unknown = JSON.parse(raw);
  const result = videoPropsSchema.safeParse(data);
  assert.ok(result.success, result.success ? "" : JSON.stringify(result.error.format()));
});

test("rejects props missing required fields", () => {
  const result = videoPropsSchema.safeParse({ onScreenHook: "hi" });
  assert.equal(result.success, false);
});
