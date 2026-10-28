# Bus presets: mix and FX busses

A **bus preset** is a bus's processing, saved on the desk: its EQ and compressor, and on an FX bus the effect inserted on it. Atoo puts one on a bus when your conventions name it.

- **On a mix bus** it is processing only. The starter's "Mix Bus" preset is a compressor and a flat EQ, and every mix bus in the starter conventions takes it (Drums, Horns, Vocals).
- **On an FX bus** it is also the effect. A WING effect is heard only through an insert: a reverb is loaded into one of the sixteen FX engines and inserted on a bus, and channels send to the bus.

**Saving one.** On the desk (or in WING-EDIT), set up the bus as you want it: its EQ and compressor, and for an FX bus the effect inserted on it with its parameters. Save it as a bus preset under the name your conventions will use ("Mix Bus", "Vox Verb"), and export it as a `.bus` file into your preset library. `atoo presets` lists it under **bus presets** ([Ask the library what it is called](presets.md#ask-the-library-what-it-is-called)).

**Naming one.** In the conventions, say which bus takes it: "Every mix bus takes the bus preset "Mix Bus"", "Each FX bus takes the bus preset of the same name" (see [Writing conventions](conventions.md#mix-and-fx-busses-name-a-bus-preset)). A bus preset has its own names: one called "Vocal" never answers for the channel preset "Vocal".

**What a build does with it.** It puts the bus preset's values into the plan, as it does a channel preset's. A preset with no effect, like "Mix Bus", needs nothing else: no engine and no insert. A preset with an effect also gets an engine:

- the **engine it was saved from**, when that engine is free and can hold the effect;
- otherwise the first free one that can. Reverbs, delays and modulation effects (chorus, flanger, pitch) can only go on engines **1-8**; other effects go on 9-16 first, to leave 1-8 for them.

Each choice is a note (`fx.engine-allocated`). So is a preset saved with its insert bypassed: it is switched **on**, because an FX bus with its effect bypassed is silent (`fx.insert-switched-on`). On the Demo show, the Drums and Vocals mix busses take "Mix Bus", the Vox Verb bus takes the Vox Verb bus preset, and `verify` says what will be written and loaded:

```
atoo verify --plan starter/demo-show/plan.json --input starter/demo-show/input.csv
```

```
0 error(s), 0 warning(s), 4 note(s)

  [info] plan: 12 channel(s) carry a preset's values, written at the processing stage and read back like every other write: ch 1 Kick In (83), ch 2 Snare (83), ch 3 H Tom (83), ch 4 Fl Tom (83), ch 5 OH (83), ch 6 Bass (83), ch 7 E Gtr (83), ch 8 E Gtr (83), ch 9 Keys (83), ch 10 Vocal (80), ch 11 Vocal (80), ch 12 Vocal (80)  (preset.expanded)
  [info] plan: 3 bus(ses) carry a bus preset's processing, written at the processing stage and read back like every other write: Drums: 'Mix Bus' (55), Vocals: 'Mix Bus' (55), Vox Verb: 'Vox Verb' (55)  (preset.bus-expanded)
  [info] plan: 1 FX insert(s) are loaded and switched on, each read back: Vox Verb: V-REV on FX5 (saved bypassed, switched on)  (fx.inserts)
  [info] channels[Music]: aux 1 'Music' is not on the input list; built because instructions.md says 'Walk-in music ("Music") on Aux 1, stereo, source LCL 3-4. Fader at -20dB', on LCL 3-4 as it states  (reconcile.from-instructions)

APPLICABLE: notes only -- choices made where the conventions were silent.
```

**What stops a plan** is only what the desk cannot hold, each an error naming the bus: a reverb or delay on engines 9-16 (`fx.engine-not-offered`), more such effects than engines 1-8 (`fx.no-engine`), two busses on one engine (`fx.engine-shared`), an effect the desk does not have (`fx.unknown-model`), or a parameter value it has no setting for (`fx.value-not-offered`).

**What apply writes**, in this order: the engine's effect, then its parameters (the effect decides which parameters exist, so they come after it), then the bus's EQ and compressor, then the bus's insert, pointed at the engine and switched on. A mix bus's preset writes only the EQ and compressor. Each is read back and journalled, and `atoo undo` takes it off again. A bus preset never sets the bus's width, routing, fader, name or color. Engines no bus uses are left alone by `patch` and `amend`, and reset by a full apply.

**A change that adds a bus** (`atoo patch`: the horns arriving with a new Horns bus) gives it its preset the same way, from the library the show was built with (or `--presets`, or `[presets] default`), and its effect, if it has one, an engine the busses already on the desk leave free. See the worked example in [Patching a running show](patch.md#try-it-with-no-console-and-no-model).

Neither a bus preset's effect nor a mix bus's compressor has yet been confirmed on a desk.

## See also

- [Using channel presets](presets.md): the library, and how a preset is named
- [Writing conventions](conventions.md#mix-and-fx-busses-name-a-bus-preset)
- [What a full apply changes on the desk](what-apply-changes.md)
