Deconstruct why the source video below holds attention, then rebuild that
structure around the brand described in the system prompt. Never copy the
source script, audio, or footage verbatim — only the underlying retention
pattern (the first-3-second hook, pacing, and structure).

Source video transcript (analysis input only — do not quote it directly):
{transcript}

Source video caption (may be empty):
{caption}

{change_request_section}

{hook_performance_section}

Produce a ScriptPlan for the brand's product that:
- opens with an on-screen hook using the same retention pattern as the source
- has a spoken_script a text-to-speech voice will read aloud in {min_script_secs}-{max_script_secs} seconds
  when read at a natural pace. This is a hard ceiling, not a target to fill:
  roughly 2.5 words per second, so keep it under {max_script_secs} seconds of speech.
  Cut any sentence that does not earn its place -- a viewer leaving early costs
  more than anything you would have said at the end.
- includes a short caption with a call-to-action for the post itself
- names the hook_pattern you used (e.g. "problem-agitate-solve", "pattern-interrupt", "before-after")
