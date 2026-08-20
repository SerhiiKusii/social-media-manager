// B-roll tiling. Kept out of MainVideo.tsx so it can be unit-tested
// without importing Remotion or rendering anything.
//
// The problem it solves: a stock clip is typically 6-10s while the body
// runs 20-40s. Playing each clip once left the last frame frozen for the
// remaining ~30s while the voiceover kept talking. Clips are cycled in
// order and repeated as needed to cover the whole segment.

export type BrollSegment = {
  src: string;
  from: number;
  durationInFrames: number;
};

export const buildBrollSegments = (
  paths: string[],
  durationsSecs: number[],
  bodyFrames: number,
  fps: number,
): BrollSegment[] => {
  const usable = paths
    .map((src, i) => ({ src, frames: Math.floor((durationsSecs[i] ?? 0) * fps) }))
    .filter((clip) => clip.frames > 0);

  if (usable.length === 0) {
    // No probed durations (ffprobe failed, or an older props file predating
    // brollDurationsSecs): show the first clip once. That is the previous
    // behaviour -- worse than tiling, but better than a blank background.
    return paths[0] ? [{ src: paths[0], from: 0, durationInFrames: bodyFrames }] : [];
  }

  const segments: BrollSegment[] = [];
  let from = 0;
  for (let i = 0; from < bodyFrames; i++) {
    const clip = usable[i % usable.length]!;
    segments.push({
      src: clip.src,
      from,
      // Truncate the last repeat rather than overrunning the segment.
      durationInFrames: Math.min(clip.frames, bodyFrames - from),
    });
    from += clip.frames;
  }
  return segments;
};
