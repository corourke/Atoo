# Installing without Homebrew

[Installing Atoo](install.md) assumes a Mac with Homebrew. This page
gets you the same three things another way: Python 3.11 or newer,
pipx, and `git`. Then carry on from [step 5](install.md#5-install-atoo).

## macOS

1. **Python.** Download the macOS installer from
   [python.org/downloads](https://www.python.org/downloads/) and run it.
   It puts `python3.12` (or whichever version) in `/usr/local/bin`, beside
   the system's 3.9, which you leave alone. Check: `python3.12 --version`.
2. **`git`.** Run `git --version`. If it offers to install Apple's
   Command Line Tools, say yes.
3. **pipx**, installed with that Python, and put on your `PATH`:

   ```bash
   python3.12 -m pip install --user pipx
   python3.12 -m pipx ensurepath && exec zsh
   ```

4. Check: `pipx --version` prints a version.

## Linux

1. **Python.** Check `python3 --version`: Atoo needs 3.11 or newer.
   Debian 12 and Ubuntu 23.04 or later have one.
2. **pipx**: `sudo apt install pipx` on Debian 12 and Ubuntu 23.04 or
   later; otherwise `python3 -m pip install --user pipx`.
3. **`PATH`**: `pipx ensurepath`, then open a new terminal.
4. **`git`**: `sudo apt install git`, if `git --version` finds none.

## Windows

**Not supported yet: nobody has run Atoo on Windows.** Reading the
code says it should work. If you try it:

1. Install Python from
   [python.org/downloads](https://www.python.org/downloads/), ticking
   *Add python.exe to PATH*.
2. Install [Git for Windows](https://git-scm.com/download/win).
3. In a new Command Prompt:

   ```
   py -m pip install --user pipx
   py -m pipx ensurepath
   ```

4. Open a new Command Prompt, and carry on from
   [step 5](install.md#5-install-atoo).

The configuration file is `C:\Users\<you>\.atoo.config`, and `init`
makes `C:\Users\<you>\Documents\Atoo`, even when your Documents folder
is kept in OneDrive; `atoo init --dir` puts it where you want it.
Atoo reads and writes every file as UTF-8, so save your input list,
conventions and instructions as UTF-8: Excel's *CSV UTF-8* and
Notepad's default both do.

Please [tell us](limitations.md#telling-us) how it went, good or bad.
