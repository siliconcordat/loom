# Contextual Compute

Status: `proposed`. This note records a design for how the Siliconcordat stack should spend compute. It does not change a shipped verifier, schema, or load gate. No measurement in this note is claimed as `verified`.

## Claim

A brain is a contextual computer. Hormones set parameters. The autonomic nervous system governs those parameters. The heart's own neurons are a separate computing hub, in the same sense that one region of a field-programmable gate array (FPGA) stays resident while another region does the work.
The somatic system then computes inside the parameters that are already set. Closed pathways are not evaluated, so the main computer stays efficient.

The same split is the proposed shape of this stack. An ancillary hub sets a parameter field before a task arrives. A fixed cloud model does the heavy computation only inside the pathways that field left open.

## Two hubs

The ancillary hub is not the model that answers. It runs beside that model, and it runs earlier than the question. In a person, the autonomic system and the cardiac neurons keep a state. Rest at home. Alert on the street.
The cortex does not, at the moment of an attack, decide to leave rest and enter adrenaline. The heightened state is already in place. A fast danger response at home is not available, and it does not have to be suppressed, because those pathways are closed.

On silicon the ancillary hub is the adaptive model. The cloud model is the somatic computer. The cloud model stays a fixed frontier model. It does the heavy work. It does not also decide, inside that same forward pass, which of its domains are allowed to wake up.

## Parameters are the hormone field

Hormones do not carry the content of a thought. They open some pathways and close others. The adaptive model's parameters do that job. They form an environment beside the Model Context Protocol (MCP). The field is a taste setter. It holds the person's preferences, which tools exist, which reflexes are armed, and the custom place the person is working in.

That environment is the local fusion of three layers. The operating system (`warp`) is the body. The harness (`exo`) is where a person steers. The structural broker (`mde`) is the set of tools and syntax zones on offer. Small models and their adapters (`weft`) sit in that fusion and express the open parameter set. The cloud model meets the person only through this fusion.

## Only open parameters activate

A closed pathway is never scored. In a biology research session the astrophysics parameters stay shut. Fluid dynamics is a term in both fields. The overlap does not matter. The word arrives, and only the open set is eligible. Astrophysics parameters are not run and then discarded. They were never activated. That is the saved compute.

The same rule covers taste, tools, and place. A tool that the session has closed is absent from the offer. A refusal after the model has already considered the tool is the slow version. It has already paid for the closed pathway.

Shaping the cloud model's output after the heavy compute is that same slow version. It tries to invent the parameter change in the moment. The hub's job is to make that moment unnecessary.

## Crude weight edits are not the aiming method

Writing a weight-space program by hand is too crude to set this field. The map from a named behavior to a set of coordinates is coarse. Training the frontier model would move the fixed shell, which is the wrong target. The frontier weights stay read-only, as `warp` and `weft` already require.

The proposed middle is a hybrid. Data flows program the adaptive parameters. A flow chooses which data moves, in what order, and toward which part of the local fusion. A compiler turns that flow into a bounded adapter for the small models. The adapter stays re-derivable from the public flow. A hidden weight delta loses the precision and breaks the existing rule that every adapter is re-derivable from public inputs.

The cloud model arranges and uses those flows. It does not become the adaptive model. Ingestion is the return flow. What the person does is carried back on a slow clock, and the next parameter field is different because of it.

## What the person touches

The person lives in the fusion, not in the frontier weights. The work surface has four proposed properties. None of them is shipped by this note.

The model reads text as text. A terminal pane is captured as characters. A picture is reserved for something that is not text.

A diagram or a mind map is stored as an indented list or as a mermaid graph. The model reads that source. It does not recover the graph by looking at a picture of it.

The person can steer while work is in progress. A queued note arrives at the next gap between steps. Stopping the turn is a separate gesture. Context for the task is already set when the task starts, so a steer changes the next step inside the open set. It does not reopen a closed domain by accident.

The shared record has two sides. One side is the person's. The other side is the model's. Text moves only on request. Merge folds the person's changes into the model side and leaves the person's side as it was. Rebase onto the model replays the person's side on top of the model side. Rebase onto the person replays the model side on top of the person's side. A conflict is shown with markers on the side that changed.

Session controls sit on that surface. Focus is a line that says what the model is doing. A lock is a phrase that stays in force until the person removes it. Knobs bias the next step, such as holding back, widening scope, or asking first. These controls are harness state. They are not hidden-state edits inside the frontier model.

Focus, attention lock, a vector of future bias, and scrubbing a step come from Spaceship IDE by Chuanqi Sun. This stack does not copy that project. It uses the ideas as a session queue. Realtime token steering is a different experiment and is not claimed here.

## What each layer owns

These are proposed consequences. They do not relax a current fail-closed gate.

`loom` keeps this note and the falsifier below. The FPGA image is a design analogy, not a claim that a measured silicon block exists.

`warp` is the body. A closed pathway is not mounted. Sandboxes and `warp-modeld` stay fail-closed. One template still compiles onto a lightweight client and a power host. The static shell stays resident. Recovery, ports, and the load gate do not move when a session changes taste. Dynamic pieces swap inside that shell.

`weft` compiles the parameter field. Direct weight-space programming is not the aiming method. The compiler input is a public data flow or an already public written rule. Frontier weights stay the read-only base `W0`.

`exo` is where a person steers. The open parameter set is already loaded when a task starts. A steer can arrive at the next safe gap without cancelling the turn. The two-sided record moves only on merge or rebase.

`mde` offers the open tool set and the open syntax zones for the session. A closed tool is not listed. Zone tags remain the syntax-level names of pathways.

## Falsifier

The gate fails if a biology session still loads or scores an astrophysics adapter when the prompt mentions fluid dynamics. A later refusal is not success. Success is that the closed adapter was not activated.

## Standing

Every statement above is `proposed`, except where it points at an existing public rule. Those existing rules are the read-only base weights, the fail-closed adapter load, and adapters that can be derived again from public inputs. This note adds no new schema and no new test.

Source for the interaction ideas: Spaceship IDE, Chuanqi Sun, https://github.com/chuanqisun/spaceship
