# Why Atoo?

When building show files, I noticed myself doing much the same thing for every new act, either patching from scratch or copying an existing showfile, following my same patterns, and it was both tedious and error prone. Festival patches were always a compromise, and when things got exciting close to doors, it was all too easy to make a routing mistake or forget something simple.

I found some [prior work](#prior-work) in this area, in terms of generating and auditing show files, but I wanted to take a different approach and start with written audio engineering knowledge, along with my own preferences and conventions that could be applied to any show. I also wanted to be able to verify the board against the input list, and logically trace the signal path for every channel from input to final output.

Lastly, I wanted to be able to type in a change (my favorite example is when an unannounced horn section showed up 30 minutes before doors) and have the program just figure it out, including busses, DCAs, presets, all of it and verify the correctness of the new layout. And if I managed to do something dumb, like mute the drum bus, or double patch the last minute backup vocalist to both the main and vocal busses, I wanted something that would alert me before the show started.

## Why not stick with what you already use?

- **Building by hand**, on the desk or in WING Edit, gives you total control, but every show costs hours, and nothing tells you channel 14 never got its high-pass. Atoo does the layout in minutes and checks it.
- **Copying last month's show file** is hard to beat when you are doing the same band. Not so much when you are editing someone else's show file. Atoo builds the show as you would build it, from the band's input list and your own notes.
- **Channel presets** make quick work of channel and bus setup, but not the routing.  Atoo uses your own presets, AND sets up the patching, busses, sends, DCAs and mains around them.
- **A spreadsheet input list** is great for coordinating with the band, but things can change (usually at the last minute). Atoo makes last minute changes easy, and checks the desk against your input list.

## Prior work

Other tools do some (or all) of what Atoo does, and several came first. They are worth knowing about.

<!-- credit:start -->
**Wing Tools** ([wingtools.theta-tontechnik.de](https://wingtools.theta-tontechnik.de)) by Theta Tontechnik is a browser-based toolset for the WING, available since 2025: routing documentation, a Snapshot Linter with a large rule catalog and one-click fixes, a snapshot generator, signal-flow views, and a live desk connection. It runs in the browser with nothing to install, and works from snapshot files or a connected desk. Atoo's fixed audit rules are inspired by its linter catalog. If you want to document, lint and fix existing snapshots, look at Wing Tools.

**Show-file generators** turn a channel list into a show file, quickly, generally starting from a template:

- the snapshot generator in **Wing Tools**, above;
- **ShowBuilder** ([showbuilder.crazyamazingdesigns.com](https://showbuilder.crazyamazingdesigns.com/)) by Crazy Amazing Designs builds a routed, labeled scene file from a questionnaire about your gear, for the X32 and M32;
- **StageOn Connect** ([stageon.app/connect](https://stageon.app/connect)) sends channel names and routing from a StageOn stage plot to the console over the network.

Atoo starts from your written conventions and an input list, can set up new and complex routing, and writes each setting to the desk and reads it back.

**Show-file checkers** check a show against a list of common mistakes:

- the Snapshot Linter in **Wing Tools**, above.

Atoo checks the desk against your input list and conventions, and keeps watching it right up to show time and while the show is running.

**Plain-language remotes** allow quick edits by typing, such as names, colors and routes:

- **Console Whisperer** by Nathan Lively sets channel names, colors and routes through Mixing Station;
- MCP servers such as **ConsoleMCP** ([github.com/bulyaki/ConsoleMCP](https://github.com/bulyaki/ConsoleMCP)) and **x32-wing-mcp** ([github.com/feimpraim/x32-wing-mcp](https://github.com/feimpraim/x32-wing-mcp)) let an AI assistant read and set desk parameters directly.

With Atoo, a typed change goes through the same checks as a full build. It is previewed, written, read back, and can be undone on its own, and nothing else on the desk moves.
<!-- credit:end -->

## What Atoo does differently

- **Your conventions rule, show after show.** They are your house rules in plain English: *"Every vocal channel gets the VOX preset and a pre-fader send to that singer's in-ear monitor at -10dB"* once, and every show with vocals gets it, whether a four-piece tonight or a twelve-piece next week.
- **Validated before it is written.** Code checks the draft against the desk's real limits and your conventions. A stereo pair that starts on an even socket, or a patch to a socket the desk does not have, is caught at your laptop, not at soundcheck.
- **Checked against the input list.** Routings, mute groups, DCAs, phantom power, built in checks and your own watch rules are all done against the input list so there is no guesswork involved.
- **Written to the desk, then read back.** There is no show file to load over the top of your show. Each setting is written over the network and read back, and anything that did not land is named. Every write is journalled and can be undone.
- **A late change moves nothing else.** Type *"trumpet, sax and trombone on LCL 21-23, Band DCA"* at 6pm, and those three channels go into free strips with their presets, sends and DCA. The strips around them are read before and after the write to prove nothing else moved.
- **It watches the show against your rules.** It re-reads the desk every couple of seconds and checks the signal path for every channel. It catches the Band DCA pulled to the floor or the Aux channel that got repatched.
- **It runs on your laptop.** There is no Atoo account and no subscription. Your show files stay with you, and the code is open source.

## What it costs you

- **Writing your conventions down is work.** A starter file is included, but the plan is only as good as what you state. If you always copy last week's show and that works, keep doing it.
- **(Today) a build needs your own AI API key**, which you pay for. Atoo is built and tested on Claude; local models are being tested but have not worked as well so far. A build takes a couple of minutes, not seconds.
- **WING only.** The Compact, the full-size WING and the Rack.

Next: [try the Demo show](../../README.md#try-it-in-two-minutes-with-no-desk), or [install it](install.md).
