# Sources and maintenance

This is Mifal's local interface specialist, not an upstream Impeccable or
LottieFiles plugin installation. Matt's upstream methodology is unchanged.
The local prose adapts selected reviewed guidance, with these sources:

- Impeccable 4.9.2, copyright Paul Bakaus and contributors, Apache-2.0,
  revision `d41d9860b0094dcb68030657da63461212835aaa` (untagged; its manifests
  read 4.9.2): entry, shape, operate, craft-floor and animate, first adapted
  at 4.8.0 revision `4f956490f0056ae1ff5ea80372cf56e83c001d3c`. [Repository](https://github.com/pbakaus/impeccable/tree/d41d9860b0094dcb68030657da63461212835aaa).
  The 2026-11-01 review of changes since `bbcb29d9dee6c94915d760bcfc36818ad5be66ad`
  adopted mode-scaled ambition and driving each interactive state; it declined
  the craft-floor exception that keeps marked bans above a pinned brief.
  The 2026-11-18 review of changes since `4f95649` read the changed animate
  and the new new-work, new-work-world, critique-rubric and motion-reviewer
  files. It adopted the hover rule, motion evidence judged by a fresh
  reviewer in at most two rounds, product questions before any look, and
  references that set the craft bar rather than the style. It declined the
  concept-seed roll, decision server, catalog worlds, comp build paths, CLI
  motion capture (agent-browser captures instead) and Nielsen scoring. The
  visual judge, static-before-motion order and prototype token controls are
  Mifal's own, from its 2026-11 research on design agents.
- LottieFiles motion-design 1.0.0, copyright LottieFiles, MIT, revision
  `2e1f3c052dd70c60b598413e2fc5d7704d9e9896`: main, context-adaptation and
  quality-checklist, adapted at `f9a8a041b85185ee4881b3471d3415e939aac772`.
  [Repository](https://github.com/LottieFiles/motion-design-skill/tree/2e1f3c052dd70c60b598413e2fc5d7704d9e9896).
  The 2026-11-18 review of the changes since found only a handoff to the
  hosted Creator MCP for file exports; engines.md lists it as an explicit
  choice, and no prose was adopted.
- Official runtime sources and their scope boundaries are linked in engines.md.

Changes are intentional: existing task/context instead of a second lifecycle;
no binary launcher/hook installation; bounded contextual craft rather than
categorical visual bans; accessibility/runtime precedence over motion rules.
The original packages offer more tools than this content-only adaptation.

Updating this guidance, or any vendored skill, from upstream is a reviewed change:
compare the changed upstream sections with the reviewed revisions, keep the
compatibility decisions above, update the provenance in `third_party/`, and rerun
the skill and layout checks. Repositories and skill bodies were inspected;
animation and runtime quality were not benchmarked.

Retain the included upstream license texts with this adapted guidance.
