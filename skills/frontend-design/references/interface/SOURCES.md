# Sources and maintenance

This is Mifal's local interface specialist, not an upstream Impeccable or
LottieFiles plugin installation. Matt's upstream methodology is unchanged.
The local prose adapts selected reviewed guidance, with these sources:

- Impeccable 4.8.0, copyright Paul Bakaus and contributors, Apache-2.0,
  revision `4f956490f0056ae1ff5ea80372cf56e83c001d3c` (untagged; its manifests
  read 4.8.0, 32 commits after the `skill-v4.8.0` tag): entry, shape, operate,
  craft-floor and animate. [Repository](https://github.com/pbakaus/impeccable/tree/4f956490f0056ae1ff5ea80372cf56e83c001d3c).
  The 2026-11-01 review of changes since `bbcb29d9dee6c94915d760bcfc36818ad5be66ad`
  adopted mode-scaled ambition and driving each interactive state; it declined
  the craft-floor exception that keeps marked bans above a pinned brief.
- LottieFiles motion-design 1.0.0, copyright LottieFiles, MIT, revision
  `f9a8a041b85185ee4881b3471d3415e939aac772`: main, context-adaptation and
  quality-checklist. [Repository](https://github.com/LottieFiles/motion-design-skill/tree/f9a8a041b85185ee4881b3471d3415e939aac772).
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
