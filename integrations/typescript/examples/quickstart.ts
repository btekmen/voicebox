/**
 * Quickstart: list profiles, speak a line, save the audio.
 *
 * Start Voicebox (desktop app, or `python -m backend.main --port 17493`), then:
 *   bun run examples/quickstart.ts "Hello from Voicebox"
 *   # or with Node 18+: npx tsx examples/quickstart.ts "..."
 */

import { VoiceboxClient } from "../src/index.js";

const text = process.argv[2] ?? "Hello from the Voicebox TypeScript client.";

const vb = new VoiceboxClient({ clientId: "quickstart" });

if (!(await vb.isUp())) {
  console.error("Voicebox isn't reachable. Start the app (or the backend on port 17493).");
  process.exit(1);
}

const profiles = await vb.listProfiles();
console.log(`${profiles.length} voice profiles:`);
for (const p of profiles.slice(0, 10)) {
  console.log(`  - ${p.name}  (${p.voiceType ?? "?"}, ${p.language ?? "?"})`);
}

if (profiles.length === 0) {
  console.error("No profiles yet — create one in the app first.");
  process.exit(1);
}

const voice = profiles[0].name;
console.log(`\nGenerating with '${voice}' ...`);
const gen = await vb.speakAndWait(text, { profile: voice });
const out = await vb.downloadAudio(gen.id, "quickstart.wav");
console.log(`Done: ${out}${gen.duration ? `  (${gen.duration.toFixed(1)}s)` : ""}`);
