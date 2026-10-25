# Mifal never writes through a linked rules file; a personal layer lives outside Mifal's block

Many developers keep one personal rules file and link it into several agents' homes: a dotfiles setup where the rules files of two Codex homes are links to the same file, or a file that Claude Code imports. Mifal's install stops and writes nothing when an agent's rules file is a symbolic link, names the link and its target, and offers two ways out: replace the link with a regular file, or wire only the other agents with `--harness`.

A personal layer is your own rules, kept outside Mifal's Marked block in each agent's own regular rules file. Mifal adds, updates and removes only its block, so the rest of the file stays as you wrote it.

Rejected: writing through the link into its target. A shared file feeds every consumer of the link, so a block written there wires homes nobody asked to wire. It would also duplicate the Guide in an agent that already imports that file, and it needs new logic to detect the duplicate. Refusing the link is the cheaper, reversible choice.

Consequence: a developer whose agents share one linked rules file keeps that file for personal rules and gives each agent Mifal serves a regular rules file that holds the personal layer plus Mifal's block. No Mifal command does that for them.
