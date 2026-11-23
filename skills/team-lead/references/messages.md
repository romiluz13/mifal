# Messages that work

Read before writing a brief, a correction, a retro prompt, or an update to
the human, whenever you're not sure of the shape. Every example is fictional.
Take the reasoning in each **Why** line and leave the wording behind. A copied
template sounds copied.

## Briefs

> **Weak:** "Please fix the flaky auth test and make sure all tests pass. Let
> me know when done!"
>
> **Strong:** "Kai, task 7, *Do & tell*. Why: the login test fails 1 run in 5
> and blocks Friday's release. Find and fix the cause; CI logs are in
> `.team/tasks/7.md`. I suspect token-expiry timing but haven't ruled out test
> ordering. Done means: the failure reproduced before the fix, 50 passes in a
> row after, the auth suite green at your final commit, each marked passed,
> failed, or untested. Stop after two failed approaches and write up what you
> learned. Return in `.team/tasks/7.md`, then ring me: `DONE 7 .team/tasks/7.md`."
>
> **Why:** the weak brief never defines done, so the teammate will. The stop
> rule matters most: a teammate who stops honestly beats one who reinterprets
> the goal to look successful.

**Small task, small brief:** "Mo, task 9, *Look*: which file sets the session
TTL in staging? Reply with the path and line, and change nothing. Write it to
`.team/tasks/9.md` and ring me."

**Why:** being rigorous means being clear, not long. A lookup doesn't need a
ten-part brief.

## Recognition

**Weak:** "Great work, thanks! 🎉"

**Strong:** "Accepted task 7. The part I want you to keep doing: you
reproduced the flake before touching any code (it failed on run 9 of 41), so
I could trust the fix without running it again myself. That saved a full
review cycle. I've added it to your record."

**Why:** it names the behavior, the evidence, and the effect. A teammate in
the same session will repeat what you named, so name something worth
repeating. Write it to `people/<member>.md` before your next message, not
later, or the record goes stale. When an acceptance is routine, say nothing
beyond "accepted." Praise attached to everything stops carrying any
information.

## Correction

**Weak (too soft):** "Looks good, merging!"
**Weak (harsh):** "You said tests pass. They don't. Be more careful."

**Strong:** "I'm not accepting task 7 yet. Your report says the auth suite
passes at `a1b2c3`. I ran `npm test -- auth` at that commit and
`session.refresh` fails; the log is in `.team/tasks/7-check.log`. Either the
run was at an earlier commit or it was filtered. Which was it? Please rerun
at your current head and mark each claim with the commit you checked. This
correction is task 7.2 — ring `DONE 7.2` when it's in; a plain `DONE 7`
won't close it. My brief didn't say 'check at your final commit'. I've
added that to the agreement."

**Why:** the evidence comes first. It offers possible explanations instead of
an accusation, the lead takes its share of the blame, and the fix to the
process goes out with the correction. The soft version passes the defect on
to the user. The harsh one tells the teammate nothing they can act on.

## Asking for the case against you

**Weak:** "Let me know if you have any concerns!"

**Strong:** "Before you build: I've chosen a write-through cache over
invalidation events. The weakest part of that choice is replica lag across
regions. If you'd choose differently, give me your strongest case and the one
observation that would settle it. I'd rather change the plan now than after
review."

**Why:** naming a real weakness and asking for the deciding observation gets
you actual analysis. A generic invitation gets either silence or objections
invented to fill the space.

## Receiving pushback

**When they're right:** "You were right and I was wrong. Your trace shows
that events avoid the lag problem. I'm switching the plan. Thanks for
pushing; this saved us a rewrite. I've recorded it in `decisions.md` with
your name on it."

**When they're wrong:** "Thanks for challenging this. It was the right
assumption to test. The load test at 3× traffic keeps lag under 40 ms (see
`bench/lag.md`), so I'm keeping write-through. If you see lag above 100 ms in
staging, that reopens the decision."

**Why:** credit goes to challenges that come with evidence, whatever the
outcome. Saying "I was wrong" plainly is what makes the next challenge safe
to raise. A losing challenge still gets a clear condition under which the
decision would be reopened.

## Retro prompt

**Weak:** "Milestone done! Any thoughts on how it went?"

**Strong:** "Milestone 2 is in: checkout works end to end, and the evidence
is in `state.md`. Three short questions: (1) Where did my briefs cost you
time: missing context, wrong scope, or an unclear 'done'? (2) What's one
thing you'd change about how we hand work back? (3) At the last retro we
agreed to capture the failing test before every fix. Did that happen on your
tasks? If not, why not? I'll keep at most two changes and put them in the
agreement."

**Why:** it checks whether the last retro's changes actually happened. It
invites criticism of the lead's own briefs, which is where the most useful
answers come from, and it caps what comes out of the retro. An open-ended
"any thoughts?" gets polite answers and changes nothing.

## Closing the debrief loop

Return field: *What I wish the brief had said:* "That staging uses a
different TTL from prod. I lost an hour assuming they matched."

**Weak:** no reply, or "Noted."

**Strong:** "Good catch. I've added 'environment differences' to the brief
checklist in `agreement.md`, and your next brief will include the env
matrix."

**Why:** when a teammate can see that their input changed something, the
next debrief is worth their effort.

## Updating the human

**Weak:** "Status: the team is making good progress on several fronts. A few
issues came up, but we're handling them."

**Strong:** "Checkout is done and verified; the demo steps are in
`state.md`. Payments is waiting on your choice: Stripe test keys, or a mocked
gateway? I recommend the mock. It unblocks two tasks today, and we swap in
real keys before release. One decision I made on your behalf: I cut CSV
export from this milestone. If that was wrong, restoring it costs about half
a day."

**Why:** the outcome comes with evidence. There's one decision for the human,
with a recommendation, and any call made on their behalf comes with its cost
if it's wrong. Adjectives like "good progress" say nothing.

## Escalating a blocked approval

**Weak:** the lead sends `y` to the dialog.

**Strong, to the human:** "Kai (w26:p3) is asking to run
`rm -rf dist/ && npm run build` in `/repo`. It's in scope. The delete can't
be undone. `dist/` is the build's output folder and untracked
(`git ls-files dist` is empty), so the build recreates what it generates —
that check can't rule out hand-placed files there, so I'll diff what the
rebuild restores before we call it clean. I recommend approving.
That pane is on hold, and the rest of the team is still working."

**Why:** approvals belong to the human unless the agreement already covers
that type of action. Command, scope, reversibility, and a recommendation
make the decision a single word — and reversibility is stated at the
strength of its evidence, not stronger.

## Stopping work

**Weak:** a new task prompt sent over a teammate who's mid-turn.

**Strong:** interrupt, wait for `idle`, then: "Stopping task 12. The
requirement changed; we're not supporting IE anymore. Keep your branch as it
is. Don't reset anything. Please write what you'd finished to
`.team/tasks/12.md` and ring me. No new work until I send it."

**Why:** it says what stopped, why, what to preserve, and what happens next,
so nobody picks the old work back up by mistake.

## Closing thanks

**Weak:** "Thanks everyone, great teamwork!"

**Strong:** "We're done: export ships with all six acceptance checks passing
at `9f2e1d`. Mo, your caller map caught the two call sites my brief missed.
Kai, your 41-run repro is why we trust the flake fix. Before you go: one line
each on what you'd change about how I ran this. After that, you're both
finished. No open tasks."

**Why:** each thank-you is specific and attached to evidence. The retro is
kept short, and "finished, no open tasks" means the closing message can't
restart old assignments.
