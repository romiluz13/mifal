# Team Lead

The skill for leading a fleet of coding agents as an engineering manager: owning the outcome, briefing well, checking evidence, and improving every cycle. This glossary fixes the language that skill, its references, and the team record share.

## Language

**Transport**:
The runtime that hosts workers and carries coordination: a multiplexer, or a single agent's subagent mechanism.
_Avoid_: Channel (a channel is a transport plus an identity scheme)

**Transport seam**:
The boundary where the team's coordination verbs (identity, dispatch, observation, handoff) meet a concrete transport. A new transport replaces the mapping, never the method.
_Avoid_: Adapter layer, abstraction

**Lead**:
The session that owns the outcome and coordinates members. Runs as a peer in a pane, not above the fleet.
_Avoid_: Orchestrator, controller, master

**Member**:
A worker agent in the fleet, known by name and pane, with a capacity ledger in the team record.
_Avoid_: Agent (when a specific fleet participant is meant), worker process

**Role folder**:
A specialist's context package: its own instructions and skills, entered by spawning with its working directory there.
_Avoid_: Persona, profile

**Capability brief**:
The brief section that names the skills fitting a task, with when-to-use wording, and the envelope for the member's own choices.
_Avoid_: Skill list, tool config

**Tool ledger**:
The return field listing the skills and MCPs a member used, considered and rejected, with reasons.
_Avoid_: Tool report, usage log

**Skill inventory**:
The record of what a member can use (skills, MCPs, harness features), built from the lead's curation plus the member's self-report at onboarding.
_Avoid_: Skill registry, capability matrix

**Doorbell**:
A member's signal that attention is needed. Four types: `DONE`, `HELP`, `HELD`, `STOPPED`.
_Avoid_: Notification (which is the transport mechanism, not the signal)

**HELP**:
A doorbell type: blocked with a specific question for the lead, answerable by resuming with guidance.
_Avoid_: Caller ping, escalation

**HELD**:
A doorbell type: blocked on an approval that belongs to the human.
_Avoid_: Permission request

**Recruitment**:
The flow where the lead identifies a capability gap, searches the skill pool, and proposes a new member (role, skill fit, model) for the human to approve.
_Avoid_: Spawning (which is mechanical), hiring

**Stewardship**:
The lead's responsibility for tooling fit: curating skill candidates, keeping the inventory current, and holding members to the governing AGENTS.md.
_Avoid_: Management, supervision

**Brief pin**:
The digest of a brief's lead-owned text, taken above its `## Return` line with checkbox state ignored. The lead stamps it at dispatch and the receipt check compares it at acceptance, so a worker cannot cut a Done-means claim or edit the Outcome unnoticed.
_Avoid_: Brief hash, signature (it detects an edit; it does not authenticate who made it)
