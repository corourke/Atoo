# Presets

A library of WING channel presets (`.chn`), made by Atoo's
maintainer on his own desk: one per common source, and named the way the
starter conventions name them.

| Preset | For |
|---|---|
| Kick In (`Kick.chn`), Snare, HiHat, H Tom, M Tom, Fl Tom, OH, Perc | drums and percussion |
| Bass, E Gtr, Ac Gtr, Keys, Piano | the band |
| Trumpet, T Bone, A Sax, T Sax, B Sax | horns |
| Vocal, Speech | singers and talkers |

A preset is matched by the name saved inside the file when it was
exported, not by its filename, and every file here is named for its
preset except `Kick.chn`, which is **Kick In**. `atoo presets`
lists what each one is called. The preset's name need not match the
channel's either: the Kick channel uses "Kick In" and is still called
Kick.

`Mix Bus.bus` is the bus preset for the mix busses (Drums, Horns,
Vocals): a compressor and a flat EQ, and no effect. The starter
conventions give every mix bus this one.

`FX Vox Verb.bus` and `FX Snare Verb.bus` are bus presets for the FX
busses: each carries its bus's EQ and compressor and the reverb inserted
on it. The starter conventions give each FX bus the bus preset of the
same name, and a build loads its reverb into an FX engine and inserts it
on the bus, switched on. To add one, save the bus preset on the desk
with its effect inserted and export it as a `.bus` file here.

`atoo init` copies this folder into your Atoo folder as your
preset library, and the Demo show is built with it. They are starting
points: replace them with your own.

## Adding or updating a preset

1. On the desk or in WING-EDIT, save the channel preset under the name
   your conventions use for it (that is the name Atoo matches on).
2. Export it as a `.chn` file into this folder (in an Atoo checkout,
   `starter/presets/`; in your own Atoo folder, `presets/`).
3. Run `atoo presets` and check it lists the name you meant.

In an Atoo checkout, the exported file carries the desk's own name in
`creator_name`: change it to `WING-PP-SERIAL01` before you share it.
(Rebuilding the Demo show from a changed set is done in the development
repository.)
