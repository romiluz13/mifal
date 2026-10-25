# UI, UX and motion acceptance

Read during planning when work changes a user journey, visual direction or
interaction, including backend changes that alter user-visible behavior.
Read again before accepting the affected implementation. For research or
plan-only work, define the checks; execution remains outside that deliverable.
This is Mifal's acceptance guidance within the selected engineering
phase, not another lifecycle, tracker or installed design methodology.

## Select the work, then the specialist

Keep UI and UX responsibilities distinct; one agent can perform both.
UI covers visual direction and interface craft. UX covers whether a person
can complete the intended task, understand the state and recover from errors.
The Team Lead selects applicable procedures in the brief and checks their
use on return. Without a team, the executing agent makes these selections
in its existing task plan; no Team Lead session or fleet is required.

| Changed behavior | Select | Leave unloaded unless separately relevant |
|---|---|---|
| Backend work with no user-journey effect | Normal engineering checks | This reference, visual design and motion skills |
| New UI or a substantial visual redesign | The shared `frontend-design` Matt interface branch, plus the relevant UX checks below | Competing full design packages; motion libraries without a task need |
| Form, navigation, loading, error or recovery behavior | This reference, [the affected design/UX sections](../../frontend-design/references/interface/design.md) in the `frontend-design` Matt branch and the selected build/debug procedure | A visual redesign for a behavior-only repair |
| Purposeful animation or complex interaction | `frontend-design` motion guidance, relevant UX checks and DDD's official documentation for the actual installed library/platform | A new animation library or skill merely for polish |
| Design-stage accessibility review | An applicable audit if exposed to this worker and permitted | Treating a static design audit as runtime accessibility proof |

Use the repository's design system and accepted visual direction. Preserve
existing library choices unless the task justifies a change. A visual
specialist's preference cannot replace journey requirements or the brief.
Resolve conflicting guidance by requirements, platform and source scope;
record a consequential choice in the existing plan.

Matt uses one existing discovery entry: load `frontend-design` and follow its
local Matt branch, reading only the selected references. It combines scoped
UI/UX guidance with conditional motion craft; [source and update policy](../../frontend-design/references/interface/SOURCES.md)
names the content-only adaptations. Team Lead chooses and verifies this branch;
a single agent selects it in the existing plan. Optional art/3D/video engines
remain task-scoped, not additional default design or development owners.

Verify available skills/tools in the actual worker. A skill file can exist
without its CLI or credentials being usable. Load selected bodies before
their work; for a discovery stub such as `agent-browser`, also load the
installed CLI's workflow guide before running browser commands. If an
applicable tool is unavailable, use a permitted equivalent or mark the
required check untested. Installation is a separate decision.

## Define and exercise the affected journey

Before building, name the person, starting state, intended task and observable
success in the existing plan or brief. Select only checks affected by the
change; a small repair needs a short walkthrough, not a second QA program.

- **Task completion:** traverse the real controls from the stated starting
  point. Record steps and the observed outcome. Direct API calls, seeded
  storage and test fixtures can prepare a scenario, but cannot replace the
  user interactions the acceptance claim covers.
- **State and recovery:** check relevant loading, empty, success and failure
  states. For input or network failures, inspect the message, preserved input,
  recovery action and the completed retry. Exercise back/cancel and repeated
  submission where the changed behavior can lose work or duplicate actions.
- **Input and layout:** inspect relevant mobile/desktop layouts and overflow.
  Exercise keyboard navigation, visible focus and applicable touch controls.
  Define any required assistive-technology checks separately; a screenshot
  does not establish keyboard or screen-reader behavior.
- **Motion:** state the purpose. For changed animation, check reduced-motion
  behavior, interruption/repeated input, cleanup and the actual target device
  or recorded simulation. Preserve necessary state feedback when motion is
  reduced. Record performance observations as observations unless measured.
- **Visual craft:** when visual direction changed, compare rendered states
  with the brief/design system, not only source code or an initial mockup.

Capture the revision, environment, starting state, viewport/input mode,
steps, observed results and evidence pointers in the existing receipt or
task note. Each selected claim is passed, failed or untested with a reason.
Use screenshots for visual claims and interaction traces/checks for behavior.
Keep secrets and private user data out of evidence.

## Accept or correct

The lead checks the required procedure loads, decisive evidence and final
revision. If a relevant specialist was omitted, establish why and request
the missing procedure/check when it matters; late reading alone is not
evidence of earlier compliance. The single executing agent applies the same
gate. A required failed or blocked check keeps the affected gate incomplete.
Use a bounded correction within the existing workflow and authorization.

An agent walkthrough can expose broken behavior. It does not prove that
real users understand the product. Record consequential usability assumptions
for user validation instead of reporting them as tested. No skill set or
passed checklist establishes universal UX quality or accessibility conformance.

## Source boundaries

The shared `frontend-design` preserves its provider visual guidance and adds
the local Matt interface branch for UI/UX and conditional motion. This is a
configured procedure; live design quality and user outcomes require the actual
project exercise.

These local acceptance choices are informed by
[WCAG 2.2 error identification](https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html)
and [animation from interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html).
The former is Level A; the latter is Level AAA, so reduced-motion expectations
here are a project quality criterion, not a claim that every motion defect
violates AA. Evaluate the applicable criteria and their exceptions before
making a conformance claim.
