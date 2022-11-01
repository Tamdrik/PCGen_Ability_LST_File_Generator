# PCGen Ability LST File Generator
A user-friendly GUI written in Python to generate PCGen-compatible .lst files for homebrew abilities. Currently compatible with Pathfinder 1e, D&D 3.5e, and D&D 5e. 

## Instructions (Windows)
1) Download the [latest release](https://github.com/Tamdrik/PCGen_Ability_LST_File_Generator/releases) as a Windows executable file.
2) Run the executable. 

All the dependencies and modules needed are included in the executable.

## Instructions (Running from source)
1) The .py file does have some dependencies, namely the **TK** and **tkinter-tooltip** packages. These can be installed via
	- `pip install tk`
	- `pip install tkinter-tooltip`
2) Download [pcgen_ability_lst_generator.py](https://raw.githubusercontent.com/Tamdrik/PCGen-Ability-LST-File-Generator/main/pcgen_ability_lst_generator.py).
3) Run pcgen_ability_lst_generator.py from your terminal.

## Known Issues
- Does not handle any mechanically-applied bonuses, only descriptions on the character sheet.  Bonuses are too diverse and complex to reasonably implement in a GUI/wizard, and if a user is able to do this properly, they're probably comfortable with editing .lst files directly anyway (or editing the BONUS tag in the generic "other fields" section of the GUI).
- Will strip SUBRACEs if loaded and re-saved (and doesn't support them in general).
- Doesn't support multiple race prerequisite options (e.g., requires either Halfling or Gnome)
- Many unsupported tokens, prerequisites, etc.  For example, does not support:
  -- "OR"-type requirements (e.g.: either Str or Dex must be 13 or higher; must have Power Attack or 15 Dex)
    --- Note: "OR"-type requirements can be documented in the "narrative requirements" field (using PRETEXT:)
- Cannot edit existing .MODs.  The program can't necessarily find the ability the .MOD is based on, so it will never be able to fully edit arbitrary .MODs using the full GUI.  Editing .MODs that refer to loaded abilities might be possible, but probably a pain to code given the current data structure. 

## Reporting
Consider this program an active work-in-progress, and as such please report any issues, bugs, or glitches. Please also pass along any other suggestions or comments you may have. I will try to get to them all in a timely fashion. I can be found in the PCGen Discord, username Tamdrik#0553.
