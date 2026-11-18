# Conditional creative engines

Read only for the requested output. This is a selection/reference map, not an
installed runtime bundle. Inspect the project lockfile and applicable official
docs before implementing. A source pointer is not an executed capability.

| Output | Selected branch | Load when needed |
|---|---|---|
| Simple website feedback | CSS/native browser APIs | Existing platform docs; no extra runtime required |
| Component state/layout/gesture motion | Existing Motion, if appropriate | [Official Motion guidance](https://github.com/motiondivision/ai-kit/blob/d1c5c26f424adfd47c112d894e9d424b57338c7e/plugins/motion/skills/motion/SKILL.md) and applicable best-practices file; paid MCP/editor paths are separate choices |
| Complex GSAP timeline/scroll scene | Existing GSAP, if appropriate | [Official GSAP skills](https://github.com/greensock/gsap-skills/tree/aed9cfd3277740755f6bfc1155c7aa645403b760/skills) and version-matched docs; load the actual needed body, not the whole bundle |
| React Three Fiber scene | R3F only when the project uses it | [Fundamentals](https://github.com/EnzeD/r3f-skills/blob/4a11805f097396fb0b893172efd1e359e8051f92/skills/r3f-fundamentals/SKILL.md), [animation](https://github.com/EnzeD/r3f-skills/blob/4a11805f097396fb0b893172efd1e359e8051f92/skills/r3f-animation/SKILL.md), then current project-version docs |
| Procedural illustration, explainer or interactive drawn art | Anidoodle, scoped to the project | [Reviewed entry](https://github.com/alexgreensh/anidoodle/blob/f649db6eb823562ae41608119beb53f04d9d7c05/skills/anidoodle/SKILL.md); load its applicable reference and inspect the project integration before running tools |
| Rendered video/composition | Remotion, scoped to the project | [Official consumer skills](https://github.com/remotion-dev/skills/tree/473352613039e718e46655a26df224851e84c4aa/skills), selecting markup/timing or the required creation/render branch |
| Rendered animation file (MP4, GIF, WebM, dotLottie, Lottie JSON) | LottieFiles Creator MCP, a hosted service | Only when the user asks for such a file and chooses the service; [reviewed handoff](https://github.com/LottieFiles/motion-design-skill/blob/2e1f3c052dd70c60b598413e2fc5d7704d9e9896/skills/motion-design/reference/export-and-render.md). Connecting it is the user's decision, not this skill's |

Match the branch to the real task. Tools may complement one another, but adding
a second engine needs an actual requirement. Runtime dependencies, generated
asset services and paid tooling remain explicit task decisions. A design skill
does not authorize publishing or a dependency migration.

## Known source boundaries

- Reviewed GSAP ScrollTrigger instructions reverse refreshPriority ordering;
  official docs say priority 1 refreshes before 0. Its horizontal sample also
  contains undefined `Max.max`, incorrect units and missing scrub. Use the
  [official runtime contract](https://gsap.com/docs/v3/Plugins/ScrollTrigger/)
  rather than copying that recipe.
- Anidoodle's host supports mount/state/pause/play/destroy and interactive input.
  Real output quality, performance and cross-browser behavior are untested here.
  Its optional Remotion backend is in the reviewed manifest; Hyperframes is
  documented but its install path was not verified. **Hyperframes is unselected.**
- R3F guidance is not generic Three.js or native-platform certification. Use
  actual project APIs and loaders; a newer recipe does not authorize an upgrade.
- Remotion's frame-driven rendering rules belong to video output. They do not
  prohibit CSS animation in the website.
- MengTo/Emil references and Pro Max's broad design generator are not additional
  default owners. Use a specific reference only when it answers a concrete gap.

For a new unfamiliar dependency, apply DDD within the current Matt phase.
Reference revisions are starting evidence, not automatic update targets.
