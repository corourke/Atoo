# How Atoo works

Atoo builds a show from three files you write, checks it, writes it to the desk, then watches the desk while you work. This page explains each piece, using the Demo show you just looked at.

## The three files you write

**Your conventions**, written once, used for every show. These are your house rules, in plain English: how you lay out a desk, which preset each kind of source gets, what goes in each DCA and mute group. A few lines from the starter conventions:

```markdown
- Color coding: Drums-Red, Bass-Blue, Guitars-Pink, Keys-Cyan, Horns-Amber, Vocals-Green, Playback-Yellow.
- Start every channel's head-amp gain at 20dB and its trim at 0dB.
- Channel order: drums, then bass, guitars, keys, horns, vocals, and playback last.
```

Edit them until they read like the way you work. See [Writing conventions](conventions.md).

**The input list**, one per show: one row for each thing plugged in, usually straight from the band's rider. The Demo show's starts:

```csv
order,patch,name,category,type,model,phantom,notes
1,AES50-A 1,Kick,drums,Mic,Beta 91A,TRUE,Boundary mic inside the kick
2,AES50-A 2,Snare,drums,Mic,SM57,FALSE,Top
```

`category` decides which DCAs, mute groups and mix buses a channel joins, and `phantom` turns on 48V. Leave `patch` blank and Atoo picks a socket. See [Writing an input list](input-lists.md).

**The instructions**, one per show, optional: what is different about tonight. Extra channels, the monitor mixes, where each output goes. They are read after your conventions, so they win where the two disagree:

```markdown
- "Vox Wedge": Lead Vox's wedge. Lead Vox sends to it. Patch to AES50-A output 1.
```

The three files live together in a [show folder](show-bundles.md), except your conventions, which every show shares.

## The plan

From those three files, Atoo builds a **plan**: every setting the desk will be given, channel by channel, with where each value came from. It is Build's step 04 in the browser, and `plan.json` in the show folder.

A model drafts the plan. Code then checks the draft against what the desk can really do and against your conventions, before anything can be written. Where your files left something open, such as whether a bus is mono or stereo, Atoo makes the usual choice and tells you, in an INFO note with what it was decided from. If a choice is wrong, state it in your conventions and the next build follows it.

## From files to desk

1. **Build.** A model drafts the plan from your three files, and code checks it.
2. **Verify.** The checks end in a verdict. Only `BLOCKED: do not apply.` stops you; notes and warnings are for you to read ([Reading findings](reading-findings.md)).
3. **Apply.** A preview shows what would change on the desk. Then each setting is written and read back, and anything that didn't land is named. Every write is recorded, so you can undo it.
4. **Watch.** Atoo re-reads the desk every couple of seconds, traces the signal path for every channel, and checks it against your plan and your own watch conditions. It catches the DCA pulled to the floor or the input that got repatched.

## Changing a show

- **Before the desk is set**, change a file and build again. Or edit the plan's tables in Build's step 04 directly: a patch, a name, a DCA or a send. Saving those updates the plan with no model.
- **Once the show is on the desk**, type the change in plain English, for example *"trumpet, sax and trombone on LCL 21-23, Band DCA"*. Atoo patches it on in free strips, and nothing already running moves ([Patch a show](patch-a-show.md)).

## Next

[Set up Atoo](configuration.md): your own Atoo folder, your desk and your presets.
