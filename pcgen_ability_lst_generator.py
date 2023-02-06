import datetime
from tkinter import *
from tkinter import filedialog
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import ttk
from tktooltip import ToolTip
import re
import os
import winreg

# import copy

"""
KNOWN ISSUES AND LIMITATIONS:
- Does not handle class abilities and other abilities besides Feats, Traits, and GM-Awarded abilities.
- Does not handle any mechanically-applied bonuses, only descriptions on the character sheet.  Bonuses are too diverse
    and complex to reasonably implement in a GUI/wizard, and if a user is able to do this properly, they're probably
    comfortable with editing .lst files directly anyway (or editing the BONUS tag in the generic "other fields" section
    of the GUI).
- Will strip SUBRACEs if loaded and re-saved (and doesn't support them in general).
- Doesn't support multiple race prerequisite options (e.g., requires either Halfling or Gnome)
- Many unsupported tokens, prerequisites, etc.  For example, does not support:
  -- "OR"-type requirements (e.g.: either Str or Dex must be 13 or higher; must have Power Attack or 15 Dex)
    --- Note: "OR"-type requirements can be documented in the "narrative requirements" field (using PRETEXT:)
- Cannot edit existing .MODs.  The program can't necessarily find the ability the .MOD is based on, so it will never
    be able to fully edit arbitrary .MODs using the full GUI.  Editing .MODs that refer to loaded abilities might be 
    possible, but probably a pain to code. 

TO-DO:
- Thorough testing, writing/reading/writing repeatedly, etc.
- Possibly allow removing/modifying PRExxx fields from 'other fields' and saving as a MOD.

v0.1.0 (1 Nov 2022):
Feature-complete initial public beta release.  Could still use significant testing.

v0.1.1 (unreleased):
Removed some vestigial references to spells from code based on spell generator.   

v0.2.0 (5 Feb 2023):
Fixed bug in generating a PCC file.

v0.2.1 (6 Feb 2023):
Added a Windows registry check to try to find PCGen install location if cannot find it in default location.
"""

PCGEN_TAB_SIZE = 6  # Used to format field spacing when writing to a .lst file
VERSION = "0.2.1 (beta)"
BUILD_DATE = "6 February 2023"

ALIGNMENTS = ("LG", "NG", "CG", "LN", "N", "CN", "LE", "NE", "CE")


class Ability:
    def __init__(self, name: str, ability_type: str, desc: str, subtypes: list = [],
                 required_race: str = "None", required_feats: list = [], required_str: int = 0, required_dex: int = 0,
                 required_con: int = 0, required_int: int = 0, required_wis: int = 0, required_cha: int = 0,
                 required_bab: int = 0, required_level: int = 0, mult: bool = False, stack: bool = False,
                 key: str = None, pretext: str = "", other_fields: list = [], mode: str = "Pathfinder 1e"):
        """
        Type representing a Pathfinder/3.5e/5e ability to be stored in a PCGen .lst file.

        :param name: Name of ability
        :param ability_type: Type of ability.  Valid values are "Feat", "Trait", "GM_Award"
        :param desc: Full description of ability
        :param subtypes: Type of trait or feat (list of string values).
            Typical values for feats include: Combat, General, Teamwork, ItemCreation, Metamagic, Grit, Style, Critical,
                Panache, Targeting, Weapon Mastery, Item Mastery, Mount, Animal [refers to companion feats], or
                Performance
            Traits should only have a single element, which should be from the following list: Social, Religion, Faith,
                Campaign, Race, Combat, Equipment, Magic, Mount, or Family.
        :param required_race: Race associated with Race Traits and Feats, e.g., Human, Half-Orc, Dwarf, Elf, Ratfolk.
            Defaults to "None".
        :param required_feats: List of feats that are a prerequisite for this ability
        :param required_str: Minimum strength required
        :param required_dex: Minimum dexterity required
        :param required_con: Minimum constitution required
        :param required_int: Minimum intelligence required
        :param required_wis: Minimum wisdom required
        :param required_cha: Minimum charisma required
        :param required_bab: Minimum base attack bonus required
        :param required_level: Minimum total character level required
        :param mult: Ability can be taken multiple times
        :param stack: Ability stacks with itself
        :param key: Unique key for referencing ability (usually same as name)
        :param pretext: Narrative requirements/prerequisites for the ability that aren't mechanically enforced by PCGen
        :param other_fields: Additional fields that this tool doesn't explicitly support except to write back to a .lst
        :param mode: Valid values are "Pathfinder 1e", "D&D 3.5e", or "D&D 5e" (affects how abilities get written to
            .lst)
        """
        self.fields = {}
        self.tags = {}
        self.prerequisites = {}
        self.prestat = {}
        self.prealign = {}
        self.fields['name'] = name.strip()
        if key is None:
            self.fields['key'] = self.fields['name']
        else:
            self.fields['key'] = key
        self.fields['desc'] = desc.strip()
        self.fields['ability_type'] = ability_type.strip()
        self.fields['ability_subtypes'] = subtypes
        self.fields['mult'] = mult
        self.fields['stack'] = stack
        self.fields['pretext'] = pretext
        self.prerequisites['race'] = required_race.strip()
        self.prerequisites['feats'] = required_feats
        self.prerequisites['level'] = required_level
        self.prestat['bab'] = required_bab
        self.prestat['str'] = required_str
        self.prestat['dex'] = required_dex
        self.prestat['con'] = required_con
        self.prestat['int'] = required_int
        self.prestat['wis'] = required_wis
        self.prestat['cha'] = required_cha
        for alignment in ALIGNMENTS:
            self.prealign[alignment] = False
        self.tags['desc'] = "DESC:"
        self.tags['type'] = "TYPE:"
        self.tags['race'] = "PRERACE:1,"
        self.tags['feats'] = "PREABILITY:"
        self.tags['stats'] = "PRESTAT:"
        self.tags['bab'] = "PRETOTALAB:"
        self.tags['level'] = "PREVARGTEQ:TL,"
        self.tags['mult'] = "MULT:"
        self.tags['stack'] = "STACK:"
        self.tags['key'] = "KEY:"
        self.tags['pretext'] = "PRETEXT:"

        self.other_fields = []
        for field in other_fields:
            self.other_fields.append(field.strip())
        self.mode = mode

    @staticmethod
    def generate_ability(lst_string: str):
        """
        This will build an Ability object from a PCGen .lst string/entry.

        :param lst_string: A line/entry from a PCGen ability .lst file
        :return: Ability corresponding to the .lst string passed in as an argument, or None if it is not a valid
                ability type handled by this class.
        """
        if lst_string.strip().startswith("#"):
            return None
        ability_dict = {}
        tokens = list(filter(None, lst_string.split("\t")))
        ability_dict['name'] = tokens.pop(0)
        ability_dict['key'] = ability_dict['name']
        ability_dict['type'] = ""
        ability_dict['subtypes'] = []
        for alignment in ALIGNMENTS:
            ability_dict[alignment] = False
        ability_dict['race'] = "None"
        ability_dict['str'] = 0
        ability_dict['dex'] = 0
        ability_dict['con'] = 0
        ability_dict['int'] = 0
        ability_dict['wis'] = 0
        ability_dict['cha'] = 0
        ability_dict['bab'] = 0
        ability_dict['mult'] = False
        ability_dict['stack'] = False
        ability_dict['desc'] = ""
        ability_dict['feats'] = []
        ability_dict['pretext'] = ""
        ability_dict['other_fields'] = []
        for token in tokens:
            token = token.strip()
            if token.startswith("CATEGORY:"):
                if token.count("FEAT") > 0:
                    ability_dict["type"] = "Feat"
            elif token.startswith("KEY:"):
                ability_dict["key"] = token.split(":", maxsplit=1)[1]
            elif token.startswith("TYPE:"):
                if token.count("Trait") > 0 and token.count("RacialTrait") == 0:
                    ability_dict["type"] = "Trait"
                elif token.count("GM_Award") > 0:
                    ability_dict["type"] = "GM_Award"
                subtokens = token.split(":", maxsplit=1)[1].split(".")
                for subtoken in subtokens:
                    subtype = subtoken.replace("Trait", "")
                    subtype = subtype.replace("SpecialQuality", "")
                    subtype = subtype.replace("GM_Award", "")
                    if len(subtype) > 0 and subtype.count("Basic") == 0 and ability_dict["subtypes"].count(
                            "Race") == 0:
                        ability_dict["subtypes"].append(subtype)
            elif token.startswith("!PREALIGN:"):
                for alignment in ALIGNMENTS:
                    ability_dict[alignment] = True
                subtokens = token.split(":", maxsplit=1)[1].split(",")
                for subtoken in subtokens:
                    ability_dict[subtoken] = False
            elif token.startswith("PRERACE:"):
                # Note this will mangle some race prerequisites that include a RACESUBTYPE tag
                subtokens = token.split(":", maxsplit=1)[1].split(",")
                race = subtokens[1]
                race = race.replace("%", "")
                ability_dict['race'] = race
            elif token.startswith("PRESTAT:"):
                subtokens = token.split(":", maxsplit=1)[1].split(",")
                subtokens = subtokens[1].split("=")
                ability_dict[subtokens[0].lower()] = int(subtokens[1])
            elif token.startswith("PRETOTALAB:"):
                ability_dict['bab'] = int(token.split(":", maxsplit=1)[1])
            elif token.startswith("PREABILITY:") and token.count("CATEGORY=FEAT") > 0:
                subtokens = token.split(":", maxsplit=1)[1].split(",")
                ability_dict['feats'] = subtokens[2:]
            elif token.startswith("DESC:"):
                ability_dict['desc'] = token.split(":", maxsplit=1)[1]
            elif token.startswith("MULT:"):
                ability_dict['mult'] = (token.split(":", maxsplit=1)[1].upper().count("YES") > 0)
            elif token.startswith("STACK:"):
                ability_dict['stack'] = (token.split(":", maxsplit=1)[1].upper().count("YES") > 0)
            elif token.startswith("PREMULT:"):
                token_value = token.split(":", maxsplit=1)[1]
                token_value = token_value.split(",", maxsplit=1)[1]
                subtokens = Ability.parse_premult(token_value)
                parseable = False
                for subtoken in subtokens:
                    if subtoken.startswith("PRERACE:"):
                        subtokens = subtoken.split(":", maxsplit=1)[1].split(",")
                        race = subtokens[1]
                        race = race.replace("%", "")
                        if ability_dict['race'].count("None") > 0:
                            parseable = True
                            ability_dict['race'] = race
                    elif subtoken.startswith("PREVARGTEQ:") and subtoken.count("PreStatScore_DEX") > 0:
                        parseable = True
                        subtokens = subtoken.split(":", maxsplit=1)[1].split(",")
                        ability_dict['dex'] = int(subtokens[1])
                    elif subtoken.startswith("PREVARGTEQ:") and subtoken.count("PreStatScore_INT") > 0:
                        parseable = True
                        subtokens = subtoken.split(":", maxsplit=1)[1].split(",")
                        ability_dict['int'] = int(subtokens[1])
                if not parseable:
                    ability_dict['other_fields'].append(token)
            elif token.startswith("PREVARGTEQ:") and token.count("PreStatScore_STR") > 0:
                subtokens = token.split(":", maxsplit=1)[1].split(",")
                ability_dict['str'] = int(subtokens[1])
            elif token.startswith("PREVARGTEQ:TL"):
                ability_dict['level'] = int(token.split(",", maxsplit=1)[1])
            elif token.startswith("PRETEXT:"):
                ability_dict['pretext'] = token.split(":", maxsplit=1)[1]
            else:
                ability_dict['other_fields'].append(token)
        if len(ability_dict['type']) > 0:
            ability = Ability(name=ability_dict['name'], ability_type=ability_dict['type'],
                              subtypes=ability_dict['subtypes'], required_race=ability_dict['race'],
                              required_str=ability_dict['str'], required_dex=ability_dict['dex'],
                              required_con=ability_dict['con'], required_int=ability_dict['int'],
                              required_wis=ability_dict['wis'], required_cha=ability_dict['cha'],
                              required_bab=ability_dict['bab'], required_feats=ability_dict['feats'],
                              mult=ability_dict['mult'], stack=ability_dict['stack'],
                              pretext=ability_dict['pretext'],
                              desc=ability_dict['desc'], other_fields=ability_dict['other_fields'])
            ability.fields['key'] = ability_dict['key']
            for alignment in ALIGNMENTS:
                ability.prealign[alignment] = ability_dict[alignment]
            return ability
        else:
            return None

    @staticmethod
    def parse_premult(token: str) -> list:
        """
        Returns all PRExxx subtokens in a PREMULT token.

        :param token: Token string following a "PREMULT:#," tag.  Should not include the first argument of the
            PREMULT tag, which is the number of PRExxx conditions that must be met from the list of PRExxx subtags.
        :return: List of individual PRExxx tag subtoken strings
        """
        tokens = token.split("],[")
        result = []
        for token in tokens:
            token = token.replace("[", "")
            token = token.replace("]", "")
            result.append(token)
        return result

    def __str__(self) -> str:
        """
        :return: String representation of an ability: the corresponding line in a PCGen .lst file.  Formatted so that
                 most fields are aligned into columns if editor tab with is set to PCGEN_TAB_SIZE (global variable)
        """
        excess_tabs = 0
        field_width = {}

        ability_string = self.fields['name']
        for i in range(0, 6 - int(len(self.fields['name']) / PCGEN_TAB_SIZE)):
            ability_string += "\t"
        if len(self.fields['name']) > 6 * PCGEN_TAB_SIZE:
            excess_tabs = int((len(self.fields['name']) - 6 * PCGEN_TAB_SIZE) / PCGEN_TAB_SIZE)

        if self.fields['key'] == self.fields['name']:
            tabs = 6
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            ability_string += "\t" * tabs
        else:
            ability_string += self.tags['key'] + self.fields['key']
            (tabs, et) = self.calculate_tabs_raw(token=self.tags['key'] + self.fields['key'], field_width=6)
            excess_tabs += et
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            ability_string += "\t" * tabs

        field_width["type"] = 4
        type_string = "\tCATEGORY:"
        if self.fields["ability_type"] == "Feat":
            tabs = 3
            while tabs > 1 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            ability_string += type_string + "FEAT" + "\t" * tabs
            type_string = "TYPE:" + ".".join(self.fields["ability_subtypes"])
        elif self.fields["ability_type"] == "Trait":
            ability_string += type_string + "Special Ability" + "\t"
            type_string = "TYPE:Trait."
            if self.fields["ability_subtypes"][0] in ("Combat", "Social", "Magic", "Faith"):
                type_string = type_string + "BasicTrait."
            type_string = type_string + self.fields["ability_subtypes"][0] + "Trait"
            if self.fields["ability_subtypes"][0].count("Race") > 0 and self.prerequisites["race"].count("None") == 0:
                type_string = type_string + "." + self.prerequisites["race"].title() + "Trait"
        else:
            ability_string += type_string + "Special Ability" + "\t"
            type_string = "TYPE:GM_Award.SpecialQuality"
        (tabs, et) = self.calculate_tabs_raw(token=type_string, field_width=field_width["type"])
        excess_tabs += et
        while tabs > 0 and excess_tabs > 0:
            tabs -= 1
            excess_tabs -= 1
        ability_string = ability_string + "\t" + type_string + "\t" * tabs

        stats = ["con", "wis", "cha"]
        if self.mode != "Pathfinder 1e":
            stats.append("str")
            stats.append("dex")
            stats.append("int")
        stats_required = []
        for stat in stats:
            if self.prestat[stat] > 0:
                stats_required.append(stat)

        if len(stats_required) > 0:
            ability_string = ability_string + "\t" + self.tags['stats'] + str(len(stats_required))
            for stat in stats_required:
                ability_string = ability_string + "," + stat.upper() + "=" + str(self.prestat[stat])
        if self.mode == "Pathfinder 1e" and (self.prestat['dex'] > 0 or self.prestat['str'] > 0 or
                                             self.prestat['int'] > 0):
            if self.prestat['dex'] > 0:
                if not any("PreStatScore_DEX" in field for field in self.other_fields):
                    self.other_fields.append("\t" + "PREMULT:1,[PREVARGTEQ:PreStatScore_DEX," +
                                             str(self.prestat['dex']) + "],[PREVARGTEQ:FeatDexRequirement," +
                                             str(self.prestat['dex']) + "]")
            if self.prestat['str'] > 0:
                if not any("PreStatScore_STR" in field for field in self.other_fields):
                    self.other_fields.append("\t" + "PREVARGTEQ:PreStatScore_STR," + str(self.prestat['str']))
            if self.prestat['int'] > 0:
                if not any("PreStatScore_INT" in field for field in self.other_fields):
                    self.other_fields.append("\t" + "PREMULT: 1, [PREVARGTEQ: PreStatScore_INT, " +
                                             str(self.prestat['int']) +
                                             "], [PREVARGTEQ: CombatFeatIntRequirement, " +
                                             str(self.prestat['int']) + "]")
            ability_string += "\t" * 4
        elif len(stats_required) == 0:
            ability_string += "\t" * 4

        field_width["prealign"] = 5
        disallowed_alignments = []
        align_string = ""
        for alignment in self.prealign.keys():
            if not self.prealign[alignment]:
                disallowed_alignments.append(alignment)
        if len(disallowed_alignments) < 9:
            align_string = "!PREALIGN:" + ",".join(disallowed_alignments)
        (tabs, et) = self.calculate_tabs_raw(token=align_string, field_width=field_width["prealign"])
        excess_tabs += et
        while tabs > 0 and excess_tabs > 0:
            tabs -= 1
            excess_tabs -= 1
        ability_string = ability_string + "\t" + align_string + "\t" * tabs

        field_width['race'] = 4
        if self.prerequisites["race"] != "None":
            if self.fields["ability_type"] == "Trait":
                # Look for PREMULT defining race prerequisite in other_fields, and either replace it or add it if
                #  it doesn't already exist
                premult_string = "PREMULT:1,[PRERACE:1," + self.prerequisites["race"] + \
                                 "],[PREABILITY:1,CATEGORY=Special Ability,Adoptive Race ~ " + \
                                 self.prerequisites["race"] + "]"
                premult_found = False
                for index in range(0, len(self.other_fields)):
                    if "PREMULT:1," in self.other_fields[index] and "PRERACE:1," in self.other_fields[index]:
                        self.other_fields[index] = premult_string
                        premult_found = True
                if not premult_found:
                    self.other_fields.append(premult_string)

                ability_string += "\t" * (field_width["race"] + 1)
            else:
                race_string = self.tags["race"] + self.prerequisites["race"]
                (tabs, et) = self.calculate_tabs_raw(token=race_string, field_width=field_width["race"])
                excess_tabs += et
                while tabs > 0 and excess_tabs > 0:
                    tabs -= 1
                    excess_tabs -= 1
                ability_string = ability_string + "\t" + race_string + "\t" * tabs
        else:
            tabs = field_width["race"] + 1
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            ability_string = ability_string + "\t" * tabs

        if self.fields["ability_type"] == "Trait":
            premult_present = False
            for field in self.other_fields:
                if field.count("PREMULT:1,[") > 0 and field.count("PREVAREQ:BypassTraitRestriction,1") > 0:
                    premult_present = True
            if not premult_present:
                self.other_fields.append("PREMULT:1,[PREABILITY:1,CATEGORY=Special Ability," + self.fields['key'] +
                                         "],[PREVAREQ:BypassTraitRestriction,1],[!PREABILITY:1,CATEGORY:Special Ability,TYPE." +
                                         self.fields['ability_subtypes'][0] + "Trait]")

        if self.prestat["bab"] > 0:
            ability_string = ability_string + "\t" + self.tags["bab"] + str(self.prestat["bab"])
        else:
            tabs = 3
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            ability_string = ability_string + "\t" * tabs

        if self.prerequisites["level"] > 0:
            ability_string = ability_string + "\t" + self.tags["level"] + str(self.prerequisites["level"])
        else:
            tabs = 4
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            ability_string = ability_string + "\t" * tabs

        field_width["feats"] = 11
        feats_string = ""
        if len(self.prerequisites['feats']) > 0:
            feats_string = self.tags['feats'] + str(len(self.prerequisites['feats'])) + ",CATEGORY=FEAT"
            for feat in self.prerequisites['feats']:
                feats_string = feats_string + "," + str(feat)
        (tabs, et) = self.calculate_tabs_raw(token=feats_string, field_width=field_width["feats"])
        excess_tabs += et
        while tabs > 0 and excess_tabs > 0:
            tabs -= 1
            excess_tabs -= 1
        ability_string = ability_string + "\t" + feats_string + "\t" * tabs

        if self.fields['mult']:
            ability_string = ability_string + "\t" + self.tags['mult'] + "YES\t"
            choice_exists = False
            for field in self.other_fields:
                if field.count("CHOOSE") > 0:
                    choice_exists = True
            if not choice_exists:
                self.other_fields.append("CHOOSE:NOCHOICE")
        else:
            ability_string = ability_string + "\t" + self.tags['mult'] + "NO\t"

        if self.fields['stack']:
            ability_string = ability_string + "\t" + self.tags['stack'] + "YES\t"
        else:
            ability_string = ability_string + "\t" + self.tags['stack'] + "NO\t"

        if self.fields['ability_type'] == "GM_Award":
            cost_present = False
            for field in self.other_fields:
                if field.count("COST:") > 0:
                    cost_present = True
            if not cost_present:
                self.other_fields.append("COST:0")

        if len(self.fields['desc']) > 0:
            ability_string = ability_string + "\t\tDESC:" + self.fields['desc']

        if len(self.fields['pretext']) > 0:
            ability_string = ability_string + "\t" + self.tags['pretext'] + self.fields['pretext']

        if len(self.other_fields) > 0:
            for field in self.other_fields:
                if len(field.strip()) > 0:
                    ability_string = ability_string + "\t\t" + field.strip()

        return ability_string

    def __eq__(self, other) -> bool:
        """ Two Abilities are considered the same if they share a common name or key, case-insensitive. """
        return self.fields['name'].upper() == other.fields['name'].upper() or \
            self.fields['key'].upper() == other.fields['key'].upper()

    def calculate_tabs(self, field_name: str, field_width: int) -> tuple:
        """
        Formatting helper function to determine how many tabs need to be added to token to align columns of fields.
        Calls "calculate_tabs_raw" to do actual calculations after building the full token string to pass it.  Only
        works with fields that are stored as a raw string, not lists such as classes and descriptors.

        :param field_name: Name of field from Ability.fields/Ability.tags dict keys (e.g., "name")
        :param field_width: How many tabs this token's column should span
        :return: Tuple containing number of padding tabs needed, followed by how many extra tabs wide the column is, if
                 it is larger than the designated field width.  This second value is used to reduce the tab padding of
                 subsequent tokens in order to try to "catch up" when this token is over-sized.
        """
        token = self.tags[field_name] + self.fields[field_name]
        return self.calculate_tabs_raw(token=token, field_width=field_width)

    @staticmethod
    def calculate_tabs_raw(token: str, field_width: int) -> tuple:
        """
        Formatting helper function to determine how many tabs need to be added to token to align columns of fields.

        :param token: Full text of token string, including tag name (e.g., "TYPE:Combat.Teamwork")
        :param field_width: How many tabs this token's column should span
        :return: Tuple containing number of padding tabs needed, followed by how many extra tabs wide the column is, if
                 it is larger than the designated field width.  This second value is used to reduce the tab padding of
                 subsequent tokens in order to try to "catch up" when this token is over-sized.
        """
        token = token.strip()
        tabs = (field_width - int(len(token) / PCGEN_TAB_SIZE))
        excess_tabs = 0
        if len(token) > field_width * PCGEN_TAB_SIZE:
            excess_tabs = int(len(token) / PCGEN_TAB_SIZE) - field_width
        return (tabs, excess_tabs)


class Mod:
    def __init__(self, base_ability: Ability, modified_ability: Ability):
        """
        Class representing an ability ".MOD" entry in a PCGen .lst file.  The values in the modified_ability will be
        compared with those in the base Ability to find differences and generate a .MOD string in the __str__ function.

        :param base_ability: The Ability being modified
        :param modified_ability: What the base Ability should be modified to
        """

        self.base_ability = base_ability
        self.modified_ability = modified_ability

        self.mode = self.modified_ability.mode
        self.key = self.base_ability.fields['key']

    def __str__(self) -> str:
        """
        :return: String representation of a MOD: the corresponding line in a PCGen .lst file.  Formatted so that
                 most fields are aligned into columns if editor tab with is set to PCGEN_TAB_SIZE (global variable)
        """
        excess_tabs = 0
        field_width = {}

        mod_string = ""
        field_width['key'] = 11
        if self.modified_ability.fields['ability_type'] == "Feat":
            mod_string += "CATEGORY=FEAT|" + self.modified_ability.fields['key'] + ".MOD"
        else:
            mod_string += "CATEGORY=Special Ability|" + self.modified_ability.fields['key'] + ".MOD"
        (tabs, et) = Ability.calculate_tabs_raw(token=mod_string, field_width=field_width['key'])
        excess_tabs += et
        mod_string += "\t" * (tabs + 1)

        field_width['type'] = 5
        clear_subtypes = False
        added_subtypes = []
        for subtype in self.base_ability.fields['ability_subtypes']:
            if subtype not in self.modified_ability.fields['ability_subtypes']:
                clear_subtypes = True
        for subtype in self.modified_ability.fields['ability_subtypes']:
            if subtype not in self.base_ability.fields['ability_subtypes'] or clear_subtypes:
                added_subtypes.append(subtype)
        if self.base_ability.fields['ability_type'] == "Trait" and \
                (self.modified_ability.prerequisites['race'] != self.base_ability.prerequisites['race']) and \
                self.base_ability.fields['ability_subtypes'][0].count("Race") > 0:
            clear_subtypes = True
        if clear_subtypes:
            mod_string += "\tTYPE:.clear\t"
        else:
            tabs = 3
            while tabs > 1 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            mod_string += "\t" * tabs

        if len(added_subtypes) > 0 or clear_subtypes:
            type_string = "TYPE:"
            if self.base_ability.fields["ability_type"] == "Feat":
                type_string += ".".join(added_subtypes)
            elif self.base_ability.fields["ability_type"] == "Trait":
                type_string += "Trait."
                if self.modified_ability.fields["ability_subtypes"][0] in ("Combat", "Social", "Magic", "Faith"):
                    type_string += "BasicTrait."
                type_string = type_string + self.modified_ability.fields["ability_subtypes"][0] + "Trait"
                if self.modified_ability.fields["ability_subtypes"][0].count("Race") > 0 and \
                        self.modified_ability.prerequisites["race"].count("None") == 0:
                    type_string = type_string + "." + self.modified_ability.prerequisites["race"].title() + "Trait"
            else:
                type_string += "GM_Award.SpecialQuality"
            (tabs, et) = Ability.calculate_tabs_raw(token=type_string, field_width=field_width["type"])
            excess_tabs += et
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            mod_string = mod_string + "\t" + type_string + "\t" * tabs
        else:
            mod_string += "\t" * (field_width['type'] + 1)

        clear_prerequisites = False
        if (self.base_ability.prerequisites['race'] != self.modified_ability.prerequisites['race']) or \
                (self.base_ability.prerequisites['level'] != self.modified_ability.prerequisites['level']) or \
                (self.base_ability.fields['pretext'] != self.modified_ability.fields['pretext']):
            clear_prerequisites = True
        for stat in self.modified_ability.prestat.keys():
            if self.base_ability.prestat[stat] != self.modified_ability.prestat[stat] and \
                    self.base_ability.prestat[stat] != 0:
                clear_prerequisites = True
        for align in ALIGNMENTS:
            if self.base_ability.prealign[align] != self.modified_ability.prealign[align]:
                clear_prerequisites = True
        for feat in self.base_ability.prerequisites['feats']:
            if feat not in self.modified_ability.prerequisites['feats']:
                clear_prerequisites = True

        if clear_prerequisites:
            mod_string += "\tPRE:.clear\t"
        else:
            mod_string += "\t\t\t"

        stats = ["con", "wis", "cha"]
        if self.mode != "Pathfinder 1e":
            stats.append("str")
            stats.append("dex")
            stats.append("int")
        stats_required = []
        for stat in stats:
            if self.modified_ability.prestat[stat] > 0 and (
                    clear_prerequisites or self.base_ability.prestat[stat] == 0):
                stats_required.append(stat)

        if len(stats_required) > 0:
            mod_string = mod_string + "\t" + self.modified_ability.tags['stats'] + str(len(stats_required))
            for stat in stats_required:
                mod_string = mod_string + "," + stat.upper() + "=" + str(self.modified_ability.prestat[stat])

        if self.mode == "Pathfinder 1e" and (
                self.modified_ability.prestat['dex'] > 0 or self.modified_ability.prestat['str'] > 0 or
                self.modified_ability.prestat['int'] > 0):
            premult_string = {}
            premult_string['str'] = "PREVARGTEQ:PreStatScore_STR," + str(self.modified_ability.prestat['str'])
            premult_string['dex'] = "PREMULT:1,[PREVARGTEQ:PreStatScore_DEX," + \
                                    str(self.modified_ability.prestat['dex']) + \
                                    "],[PREVARGTEQ:FeatDexRequirement," + \
                                    str(self.modified_ability.prestat['dex']) + "]"
            premult_string['int'] = "PREMULT: 1, [PREVARGTEQ: PreStatScore_INT, " + \
                                    str(self.modified_ability.prestat['int']) + \
                                    "], [PREVARGTEQ: CombatFeatIntRequirement, " + \
                                    str(self.modified_ability.prestat['int']) + "]"
            for stat in ('str', 'dex', 'int'):
                if self.modified_ability.prestat[stat] > 0 and \
                        (clear_prerequisites or self.base_ability.prestat[stat] == 0):
                    premult_found = False
                    for index in range(0, len(self.modified_ability.other_fields)):
                        if ("PreStatScore_" + stat.upper()) in self.modified_ability.other_fields[index]:
                            self.modified_ability.other_fields[index] = premult_string[stat]
                            premult_found = True
                    if not premult_found:
                        self.modified_ability.other_fields.append(premult_string[stat])
            mod_string += "\t" * 4
        elif len(stats_required) == 0:
            mod_string += "\t" * 4

        field_width["prealign"] = 5
        disallowed_alignments = []
        align_string = ""
        for alignment in ALIGNMENTS:
            if not self.modified_ability.prealign[alignment]:
                disallowed_alignments.append(alignment)
        if len(disallowed_alignments) < 9 and clear_prerequisites:
            align_string = "!PREALIGN:" + ",".join(disallowed_alignments)
        (tabs, et) = Ability.calculate_tabs_raw(token=align_string, field_width=field_width["prealign"])
        excess_tabs += et
        while tabs > 0 and excess_tabs > 0:
            tabs -= 1
            excess_tabs -= 1
        mod_string = mod_string + "\t" + align_string + "\t" * tabs

        field_width['race'] = 4
        if self.modified_ability.prerequisites["race"] != "None" and \
                (clear_prerequisites or self.base_ability.prerequisites['race'] == "None"):
            if self.modified_ability.fields["ability_type"] == "Trait":
                # Look for PREMULT defining race prerequisite in other_fields, and either replace it or add it if
                #  it doesn't already exist
                premult_string = "PREMULT:1,[PRERACE:1," + self.modified_ability.prerequisites["race"] + \
                                 "],[PREABILITY:1,CATEGORY=Special Ability,Adoptive Race ~ " + \
                                 self.modified_ability.prerequisites["race"] + "]"
                premult_found = False
                for index in range(0, len(self.modified_ability.other_fields)):
                    if "PREMULT:1," in self.modified_ability.other_fields[index] and \
                            "PRERACE:1," in self.modified_ability.other_fields[index]:
                        self.modified_ability.other_fields[index] = premult_string
                        premult_found = True
                if not premult_found:
                    self.modified_ability.other_fields.append(premult_string)

                mod_string += "\t" * (field_width["race"] + 1)
            else:
                race_string = self.modified_ability.tags["race"] + self.modified_ability.prerequisites["race"]
                (tabs, et) = Ability.calculate_tabs_raw(token=race_string, field_width=field_width["race"])
                excess_tabs += et
                while tabs > 0 and excess_tabs > 0:
                    tabs -= 1
                    excess_tabs -= 1
                mod_string = mod_string + "\t" + race_string + "\t" * tabs
        else:
            tabs = field_width["race"] + 1
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            mod_string = mod_string + "\t" * tabs

        if self.modified_ability.fields["ability_type"] == "Trait" and \
                (clear_prerequisites or
                 self.modified_ability.fields['ability_subtypes'][0] != self.base_ability.fields['ability_subtypes'][
                     0]):
            premult_present = False
            for field in self.modified_ability.other_fields:
                if field.count("PREMULT:1,[") > 0 and field.count("PREVAREQ:BypassTraitRestriction,1") > 0:
                    premult_present = True
            if not premult_present:
                self.modified_ability.other_fields.append("PREMULT:1,[PREABILITY:1,CATEGORY=Special Ability," +
                                                          self.modified_ability.fields['key'] +
                                                          "],[PREVAREQ:BypassTraitRestriction,1],[!PREABILITY:1,CATEGORY:Special Ability,TYPE." +
                                                          self.modified_ability.fields['ability_subtypes'][
                                                              0] + "Trait]")

        if self.modified_ability.prestat["bab"] > 0 and (clear_prerequisites or self.base_ability.prestat["bab"] == 0):
            mod_string = mod_string + "\t" + self.modified_ability.tags["bab"] + \
                         str(self.modified_ability.prestat["bab"])
        else:
            tabs = 3
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            mod_string = mod_string + "\t" * tabs

        if self.modified_ability.prerequisites["level"] > 0 and \
                (clear_prerequisites or self.base_ability.prerequisites['level'] == 0):
            mod_string = mod_string + "\t" + self.modified_ability.tags["level"] + \
                         str(self.modified_ability.prerequisites["level"])
        else:
            tabs = 4
            while tabs > 0 and excess_tabs > 0:
                tabs -= 1
                excess_tabs -= 1
            mod_string = mod_string + "\t" * tabs

        field_width["feats"] = 11
        feats_string = ""
        added_feats = []
        for feat in self.modified_ability.prerequisites['feats']:
            if feat not in self.base_ability.prerequisites['feats'] or clear_prerequisites:
                added_feats.append(feat)
        if len(added_feats) > 0:
            feats_string = self.modified_ability.tags['feats'] + str(len(added_feats)) + ",CATEGORY=FEAT,"
            feats_string = feats_string + ",".join(added_feats)
        (tabs, et) = Ability.calculate_tabs_raw(token=feats_string, field_width=field_width["feats"])
        excess_tabs += et
        while tabs > 0 and excess_tabs > 0:
            tabs -= 1
            excess_tabs -= 1
        mod_string = mod_string + "\t" + feats_string + "\t" * tabs

        if len(self.modified_ability.fields['pretext']) > 0 and (clear_prerequisites or
                                                                 len(self.base_ability.fields['pretext']) == 0):
            mod_string = mod_string + "\t" + self.modified_ability.tags['pretext'] + \
                         self.modified_ability.fields['pretext']

        if self.modified_ability.fields['mult'] and not self.base_ability.fields['mult']:
            mod_string = mod_string + "\t" + self.modified_ability.tags['mult'] + "YES\t"
            choice_exists = False
            for field in self.modified_ability.other_fields:
                if field.count("CHOOSE") > 0:
                    choice_exists = True
            if not choice_exists:
                self.modified_ability.other_fields.append("CHOOSE:NOCHOICE")
        elif not self.modified_ability.fields['mult'] and self.base_ability.fields['mult']:
            mod_string = mod_string + "\t" + self.modified_ability.tags['mult'] + "NO\t"
        else:
            mod_string += "\t" * 3

        if self.modified_ability.fields['stack'] and not self.base_ability.fields['stack']:
            mod_string = mod_string + "\t" + self.modified_ability.tags['stack'] + "YES\t"
        elif not self.modified_ability.fields['stack'] and self.base_ability.fields['stack']:
            mod_string = mod_string + "\t" + self.modified_ability.tags['stack'] + "NO\t"
        else:
            mod_string += "\t" * 3

        if self.modified_ability.fields['desc'] != self.base_ability.fields['desc']:
            mod_string = mod_string + "\t\tDESC:.clear\tDESC:" + self.modified_ability.fields['desc']

        added_other_fields = []
        for field in self.modified_ability.other_fields:
            if field not in self.base_ability.other_fields or \
                    (clear_prerequisites and field.count("PRE", 0, 4) > 0):
                added_other_fields.append(field)
        if len(added_other_fields) > 0:
            for field in added_other_fields:
                if len(field.strip()) > 0:
                    mod_string = mod_string + "\t\t" + field.strip()

        return mod_string

    @staticmethod
    def extract_key(lst_string: str) -> str:
        return lst_string.split("|")[1].split(".")[0]


class AbilityGenerator:
    def __init__(self, abilities=[], mods=[], other_entries=[]):
        """
        Initialize the AbilityGenerator class mainly by building all the GUI elements.  This maintains the list of
        abilities for each system, as well as the loading/saving of the list to file.  It contains a AbilityEditor
        instance to edit/create individual abilities.

        :param abilities: Starting ability list, if any (defaults to empty list).  Stored in list as type Ability.
        :param mods: Starting list of ability mods, represented as strings as the mod would be represented as a line in
                        a .lst file (defaults to empty list).  This program can create new mods from existing
                        abilities but not edit existing mods.
        :param other_entries: Similar to the 'mods' parameter, but these are ability entries that aren't directly
                        supported by this tool, such as class abilities.
        """
        modes = ("Pathfinder 1e", "D&D 3.5e", "D&D 5e")
        self.config_file = "pcg_ability_lst_generator.cfg"
        self.default_directory = "."
        self.default_system = "Pathfinder 1e"
        self.load_config()
        self.win = Tk(screenName=None, baseName=None, className='Tk')
        self.win.title("PCGen Homebrew Ability Generator")
        self.win.protocol("WM_DELETE_WINDOW", self.on_exit)
        self.win.focus_set()
        self.system_mode = StringVar(self.win)
        self.system_mode.set(self.default_system)
        self.ability_list = {}
        self.mod_list = {}
        self.other_entries = {}
        for mode in modes:
            self.ability_list[mode] = []
            self.mod_list[mode] = []
            self.other_entries[mode] = []
        self.ability_list[self.system_mode.get()] = abilities
        self.mod_list[self.system_mode.get()] = mods
        self.other_entries[self.system_mode.get()] = other_entries

        menubar = Menu(self.win)
        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save abilities/MODs to LST file", command=self.save_abilities)
        file_menu.add_command(label="Load abilities/MODs from LST file", command=self.load_abilities)
        file_menu.add_command(label="Save only MODs to LST file", command=self.save_mods)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=file_menu)

        system_menu = Menu(menubar, tearoff=0)
        for mode in modes:
            system_menu.add_radiobutton(label=mode, variable=self.system_mode, value=mode,
                                        command=self.set_system)
        menubar.add_cascade(label="System", menu=system_menu)

        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="What is a MOD?", command=self.mod_help)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.win.config(menu=menubar)

        # Build left frame with ability list and associated buttons
        self.left_frame = Frame(self.win, width=200)
        self.left_frame.pack(side=LEFT, fill=BOTH)
        self.ability_list_frame = Frame(self.left_frame, width=200)
        self.ability_list_frame.pack(side=TOP, fill=BOTH)
        self.ability_list_label = Label(self.ability_list_frame, text=self.system_mode.get())
        self.ability_list_label.pack(side=TOP)

        self.ability_mod_frame = ttk.Frame(self.ability_list_frame)
        self.ability_mod_tabs = ttk.Notebook(self.ability_mod_frame)
        self.ability_mod_tabs.bind('<ButtonRelease-1>', self.update_buttons)

        self.ability_tab_frame = ttk.Frame(self.ability_mod_tabs)
        self.ability_scrollbar = Scrollbar(self.ability_tab_frame)
        self.ability_lb = Listbox(self.ability_tab_frame, height=32, width=30, selectmode=SINGLE, font=('Arial', 10))
        self.ability_lb.bind("<Double-1>", self.edit_ability)
        self.ability_mod_tabs.add(self.ability_tab_frame, text="Abilities")

        self.mods_tab_frame = ttk.Frame(self.ability_mod_tabs)
        self.mod_scrollbar = Scrollbar(self.mods_tab_frame)
        self.mods_lb = Listbox(self.mods_tab_frame, height=32, width=30, selectmode=SINGLE, font=('Arial', 10),
                               fg="Blue")
        for mod in self.mod_list[self.system_mode.get()]:
            self.mods_lb.insert(END, Mod.extract_key(mod))

        self.ability_mod_tabs.add(self.mods_tab_frame, text="MODs")
        (self.mod_tab_id, self.ability_tab_id) = (1, 0)

        # self.scrollbar = Scrollbar(self.ability_list_frame)
        # self.scrollbar = Scrollbar(self.ability_mod_frame)
        # self.scrollbar.pack(side=RIGHT, fill=BOTH)
        self.ability_scrollbar.pack(side=RIGHT, fill=BOTH)
        self.mod_scrollbar.pack(side=RIGHT, fill=BOTH)

        for ability in self.ability_list[self.system_mode.get()]:
            self.ability_lb.insert(END, ability.fields['name'])

        self.mods_lb.config(yscrollcommand=self.mod_scrollbar.set)
        self.mod_scrollbar.config(command=self.mods_lb.yview)
        self.mods_lb.pack(fill=BOTH, expand=True)

        self.ability_lb.config(yscrollcommand=self.ability_scrollbar.set)
        self.ability_scrollbar.config(command=self.ability_lb.yview)
        self.ability_lb.pack(fill=BOTH, expand=True)

        self.ability_mod_tabs.pack(expand=True, fill=BOTH)
        self.ability_mod_frame.pack(side=TOP, expand=True, fill=BOTH)

        # Build buttons at bottom of left frame
        self.ability_list_button_frame = Frame(self.left_frame, width=200, height=20)
        self.ability_list_button_frame.pack(side=TOP, fill=BOTH)

        self.edit_ability_button = Button(self.ability_list_button_frame, text="Edit Ability", width=15,
                                          command=self.edit_ability)
        ToolTip(self.edit_ability_button, "Note that this tool cannot edit MODs.")
        self.edit_ability_button.pack(side=LEFT, pady=(0, 10))
        self.remove_ability_button = Button(self.ability_list_button_frame, text="Remove Ability", width=15,
                                            command=self.remove_ability)
        self.remove_ability_button.pack(side=LEFT, pady=(0, 10))

        # Build ability editing frame
        self.ability_editor = AbilityEditor(master=self.win, generator=self)
        self.ability_editor.pack(side=RIGHT, fill=BOTH, expand=True)

    def run(self) -> None:
        """ Initiate the main loop of the AbilityGenerator GUI. """
        self.win.mainloop()

    def update_buttons(self, arg=None) -> None:
        if self.ability_mod_tabs.tab(self.ability_mod_tabs.select(), "text") == "Abilities":
            self.edit_ability_button.configure(state="normal")
        else:
            self.edit_ability_button.configure(state="disabled")

    def set_system(self) -> None:
        """
        Update everything according to selected system mode.  Swaps ability lists & re-initializes ability editing frame
        to reflect elements that are relevant to current system.
        """
        self.ability_list_label.configure(text=self.system_mode.get())
        self.ability_lb.delete(0, END)
        for ability in self.ability_list[self.system_mode.get()]:
            self.ability_lb.insert(END, ability.fields['name'])
        self.mods_lb.delete(0, END)
        for mod in self.mod_list[self.system_mode.get()]:
            self.mods_lb.insert(END, Mod.extract_key(mod))

        self.ability_editor.destroy()
        self.ability_editor.__init__(master=self.win, generator=self)
        self.ability_editor.pack(side=RIGHT, fill=BOTH, expand=True)
        self.default_system = self.system_mode.get()

    def get_system(self) -> str:
        return self.system_mode.get()

    def add_ability(self, ability: Ability) -> None:
        for a in self.ability_list[self.system_mode.get()]:
            if a.fields['name'] == ability.fields['name'] or a.fields['key'] == ability.fields['key']:
                answer = messagebox.askyesno("Duplicate ability", "Ability already exists in list.  Overwrite?")
                if answer:
                    self.ability_list[self.system_mode.get()].remove(a)
                    i = self.ability_lb.get(0, END).index(a.fields['name'])
                    self.ability_lb.delete(i)
                    break
                else:
                    return

        self.ability_list[self.system_mode.get()].append(ability)
        self.ability_lb.insert(END, ability.fields['name'])

    def add_mod(self, mod: Mod) -> None:
        for m in self.mod_list[self.system_mode.get()]:
            if Mod.extract_key(m) == mod.key:
                answer = messagebox.askyesno("Duplicate mod", "Mod already exists in list.  Overwrite?")
                if answer:
                    self.mod_list[self.system_mode.get()].remove(m)
                    i = self.mods_lb.get(0, END).index(mod.key)
                    self.mods_lb.delete(i)
                    break
                else:
                    return

        self.mod_list[self.system_mode.get()].append(str(mod))
        self.mods_lb.insert(END, mod.key)

    def remove_ability(self) -> None:
        """ Deletes the selected ability from the list. """
        if self.ability_mod_tabs.tab(self.ability_mod_tabs.select(), "text") == "Abilities":
            try:
                index = self.ability_lb.curselection()[0]
            except IndexError:
                messagebox.showerror("No ability selected", "Please select an ability from the list to remove.")
                return
            self.ability_list[self.system_mode.get()].pop(index)
            self.ability_lb.delete(index)
        else:
            try:
                index = self.mods_lb.curselection()[0]
            except IndexError:
                messagebox.showerror("No MOD selected", "Please select a MOD from the list to remove.")
                return
            self.mod_list[self.system_mode.get()].pop(index)
            self.mods_lb.delete(index)

    def edit_ability(self, arg=None) -> None:
        """
        Loads the selected ability into the editing frame, copying its attributes into the corresponding GUI elements.

        :param arg: Second argument is needed for some event binding for some reason.
        """
        try:
            index = self.ability_lb.curselection()[0]
        except IndexError:
            messagebox.showerror("No ability selected", "Please select an ability from the list to edit.")
            return
        ability = self.ability_list[self.system_mode.get()][index]
        self.ability_editor.populate_fields(ability)

    def save_abilities(self, mods_only: bool = False) -> None:
        """
        Save the current list of abilities to a .lst file, one line per ability.  If there are any .MODs stored (from
        previously loading a .lst file), those will also be written to the end of the file.

        If no .pcc file is found in the folder where the .lst file is located, this function will offer to create one
        that allows the .lst file to be loaded.  If a .pcc file does exist, this function will check to make sure it
        will load the newly-saved .lst file, and if not, offer to update it so that it will.

        Calls generate_ability_lst() and generate_pcc_file() to actually write to the respective files.
        """
        if mods_only and len(self.mod_list[self.system_mode.get()]) == 0:
            messagebox.showerror("No MODs defined", "No MODs to save to a .lst file.  " +
                                 "Load and/or add MODs first.")
            return
        elif len(self.ability_list[self.system_mode.get()]) == 0:
            messagebox.showerror("No abilities defined", "No abilities to save to a .lst file.  " +
                                 "Load and/or add abilities first.")
            return
        filename = filedialog.asksaveasfilename(initialdir=self.default_directory,
                                                title="Select a file to save to (will overwrite existing abilities!)",
                                                confirmoverwrite=True,
                                                filetypes=(("PCGen LST Files", "*.lst"), ("All Files", "*.*")))
        if filename is not None and len(filename) > 0:
            if not filename.lower().endswith(".lst"):
                filename = filename + ".lst"
            # Check to see if trying to overwrite a .lst file that wasn't generated by this tool, possibly wrecking it
            if os.path.dirname(filename).count("/data") == 0:
                answer = messagebox.askokcancel("Warning", "It doesn't look like this is a valid subdirectory under " +
                                                "the PCGen 'data' folder.  PCGen will not be able to find/load " +
                                                "sources from other locations.  Continue?")
                if not answer:
                    return
            if os.path.isfile(filename):
                with open(filename, "r") as f:
                    header = f.readline()
                    while header.startswith("#"):
                        header = f.readline()
                if header.upper().count("HOMEBREW") == 0 and header.upper().count("MPC") == 0:
                    answer = messagebox.askokcancel("Warning", "It looks like this .lst file you're about to " +
                                                    "overwrite was not generated by this tool. Overwriting existing " +
                                                    "ability .lsts from other sources may cause them to stop " +
                                                    "functioning properly.  Continue?")
                    if not answer:
                        return
            if mods_only:
                self.generate_ability_lst(filename=filename, abilities=[],
                                          mods=self.mod_list[self.system_mode.get()],
                                          other_entries=[],
                                          mode=self.system_mode.get())
            else:
                self.generate_ability_lst(filename=filename, abilities=self.ability_list[self.system_mode.get()],
                                          mods=self.mod_list[self.system_mode.get()],
                                          other_entries=self.other_entries[self.system_mode.get()],
                                          mode=self.system_mode.get())
            self.default_directory = os.path.dirname(filename)
            messagebox.showinfo("Success", "Saved abilities to file: " + filename)
            self.check_for_pcc_file(filename=filename)

    def check_for_pcc_file(self, filename: str) -> None:
        """
        Checks for existence of a .pcc file that includes a reference to the given filename (an ability .lst file).  If
        a .pcc file is found in the folder of the given filename, this calls 'update_pcc_file()' which checks for an
        'ABILITY=' reference to the given .lst filename. If no reference is found, it prompts the user to add one.

        If no .pcc file is found at all, this will prompt the user to create a new one, by calling
        'generate_pcc_file()', which will create a new .pcc file with a reference to the given ability .lst file.

        :param filename: Filename of the ability .lst file to check for a .pcc that will load it
        """
        contents = os.listdir(os.path.dirname(filename))
        pcc_file = ""
        for entry in contents:
            if entry.endswith(".pcc"):
                pcc_file = os.path.join(os.path.dirname(filename), entry)
        if pcc_file == "":
            answer = messagebox.askyesno("No .pcc file found.", "Would you like to create a new .pcc file for " +
                                         "PCGen to be able to import your .lst as part of a new source?")
            if answer:
                pcc_file = filedialog.asksaveasfilename(initialdir=os.path.dirname(filename),
                                                        title="Select a filename for your new source (e.g., homebrew.pcc)",
                                                        confirmoverwrite=True,
                                                        filetypes=(("PCGen PCC Files", "*.pcc"), ("All Files", "*.*")))
                success = self.generate_pcc_file(pcc_file=pcc_file, ability_lst_file=filename)
                if success:
                    messagebox.showinfo("Success", "Successfully generated new .pcc file. Source should be " +
                                        "available in PCGen under the publisher \'Homebrew\'.")
            else:
                messagebox.showinfo("No .pcc file for PCGen", "PCGen may not be able to load your .lst file " +
                                    "without a valid .pcc file.")
        else:
            self.update_pcc_file(pcc_file=pcc_file, lst_file=filename)

    def save_mods(self) -> None:
        """ Saves all MODs only (not Abilities) to a file by calling save_abilities(mods_only=True). """
        self.save_abilities(mods_only=True)

    def generate_pcc_file(self, pcc_file: str, ability_lst_file: str) -> bool:
        """
        If no .pcc file was found when saving abilities to a .lst, this function is called to create a new .pcc file
        that will load the given ability .lst file.  Asks the user which system they are using between Pathfinder 1e,
        D&D 3.5e, or D&D 5e and configures the .pcc file accordingly.  The newly-created source will be available in
        PCGen under the publisher "Homebrew".

        :param pcc_file: Fully-qualified path of the .pcc file to be created (string).
        :param ability_lst_file: Fully-qualified path of the .lst file containing the abilities just saved (string).
        :return: True if successful, False if not.
        """
        try:
            if not pcc_file.endswith(".pcc"):
                pcc_file = pcc_file.strip() + ".pcc"
            with open(pcc_file, "w") as f:
                pcc_name = os.path.basename(pcc_file).split(".")[0]
                f.write("CAMPAIGN:" + pcc_name.title() + "\n")
                if self.system_mode.get() == "Pathfinder 1e":
                    f.write("GAMEMODE:Pathfinder\n")
                    f.write("TYPE:Homebrew.PathfinderHomebrew\n")
                elif self.system_mode.get() == "D&D 3.5e":
                    f.write("GAMEMODE:35e\n")
                    f.write("TYPE:Homebrew.35Homebrew\n")
                elif self.system_mode.get() == "D&D 5e":
                    f.write("GAMEMODE:5e\n")
                    f.write("TYPE:Homebrew.5eHomebrew\n")

                f.write("BOOKTYPE:Supplement\n")
                f.write("PUBNAMELONG:Homebrew\n")
                f.write("PUBNAMESHORT:Homebrew\n")
                f.write("SOURCELONG:" + pcc_name.title() + "\n")
                f.write("SOURCESHORT:Homebrew\n")
                f.write("RANK:9\n")
                f.write("DESC:Homebrew content generated by PCGen Homebrew Ability LST Generator\n\n")
                f.write("ABILITY:" + os.path.basename(ability_lst_file))
                return True
        except Exception as e:
            messagebox.showerror("Error generating .pcc file.", str(e))
            print(e)
            return False

    @staticmethod
    def update_pcc_file(pcc_file: str, lst_file: str) -> None:
        """
        Checks to see if the given .pcc file includes a reference to the given ability .lst file, and if not, asks
        user if they want to update it.

        :param pcc_file: Fully-qualified path to .pcc file to check
        :param lst_file: Fully-qualified path to .lst file to check .pcc file for a reference to
        """
        with open(pcc_file, "r") as f:
            lines = f.readlines()
        ability_lst_found = False
        for line in lines:
            if line.startswith("ABILITY:"):
                if line.count(os.path.basename(lst_file)) > 0:
                    ability_lst_found = True
        if not ability_lst_found:
            answer = messagebox.askyesno(".lst file not loaded in .pcc", "The .pcc file in this folder does " +
                                         "not appear to load your .lst file.  Add it to the .pcc file?")
            if answer:
                try:
                    with open(pcc_file, "a") as f:
                        f.write("\nABILITY:" + os.path.basename(lst_file))
                except Exception as e:
                    messagebox.showerror("Error updating " + os.path.basename(pcc_file), str(e))
                    print(e)
                    return
                messagebox.showinfo("Success", ".pcc file successfully updated!")

    def load_abilities(self) -> None:
        """
        Load abilities from an existing .lst file, e.g., to edit and add to an existing list of homebrew abilities.

        Calls load_ability_lst() to handle the actual parsing of the .lst file data into Ability objects.
        """
        filename = filedialog.askopenfilename(initialdir=self.default_directory, title="Select a file to open",
                                              filetypes=(("PCGen LST Files", "*.lst"), ("All Files", "*.*")))
        if filename is not None and len(str(filename)) > 0:
            self.ability_list[self.system_mode.get()].clear()
            self.mod_list[self.system_mode.get()].clear()
            (self.header, self.ability_list[self.system_mode.get()], self.mod_list[self.system_mode.get()],
             self.other_entries[self.system_mode.get()]) = self.load_ability_lst(filename=str(filename))
            self.ability_lb.delete(0, 'end')
            self.mods_lb.delete(0, 'end')
            index = 0
            for ability in self.ability_list[self.system_mode.get()]:
                self.ability_lb.insert(index, ability.fields['name'])
                index = index + 1
            for mod in self.mod_list[self.system_mode.get()]:
                self.mods_lb.insert(index, Mod.extract_key(mod))
                index = index + 1
            self.default_directory = os.path.dirname(filename)
            messagebox.showinfo("Success", "Loaded abilities from file: " + filename)

    @staticmethod
    def about_dialog() -> None:
        messagebox.showinfo("PCGen Homebrew Ability .lst Generator " + VERSION, "Build date: " + BUILD_DATE + "\n" +
                            "Written by Sean Butler (Tamdrik#0553 on PCGen Discord)\n\nPlease report any bugs or " +
                            "other feedback on the PCGen Discord, addressed to Tamdrik#0553.")

    @staticmethod
    def mod_help() -> None:
        messagebox.showinfo(title="What is a MOD?",
                            message="A MOD (modification) is a change to an existing ability (or other PCGen entry). " +
                                    "PCGen will load the base ability from its original source, then apply these changes to " +
                                    "it. If you save your modified ability as an entirely new ability with the same " +
                                    "name/key, PCGen will have issues trying to figure out which one to load if both sources " +
                                    "are loaded.\n\nThis tool lets you create a MOD when you 'Edit' a loaded ability and " +
                                    "make changes to it, then select 'Add as Mod' or 'Append as Mod to .lst file'.\n\n" +
                                    "If you want to make a change to an existing ability like Power Attack, for instance " +
                                    "to remove the Strength requirement, you should save your change as a MOD.  If you want " +
                                    "to define a new ability similar to Power Attack, but that coexists with it, you should " +
                                    "make your change, then rename it and change the key (e.g., 'Super Power Attack').")

    def on_exit(self) -> None:
        """
        Called when the user closes the application. Warns user to save their work and updates the config file
        to store the last folder used, so that loads/saves start in that folder the next time the application is run.
        """
        answer = messagebox.askokcancel("Are you sure?", "Any unsaved abilities will be lost on exit\n(use File -> " +
                                        "Save abilities to LST file)")
        if not answer:
            return
        print("Exiting program and updating configuration file...")
        try:
            with open(self.config_file, "w") as f:
                f.write("DEFAULTDIRECTORY=" + self.default_directory + "\n")
                f.write("DEFAULTSYSTEM=" + self.system_mode.get() + "\n")
        except Exception as e:
            print("Could not update config file.")
            print(e)
        self.win.destroy()

    def load_config(self) -> None:
        """
        Load config file for the application.  If not found, tries to find the PCGen directory as a default starting
        directory when loading/saving .lst files.
        """
        try:
            with open(self.config_file, "r") as f:
                lines = f.readlines()
        except FileNotFoundError:
            self.default_directory = self.find_pcgen_directory()
            mode_dialog = Tk()
            mode_dialog.title("Game mode?")
            qlabel = Label(mode_dialog, text="Which system are you using?", font='bold')
            qlabel.pack(side=TOP, padx=10, pady=10)
            choices = ("Pathfinder 1e", "D&D 3.5e", "D&D 5e")
            system = StringVar(mode_dialog)
            system.set(choices[0])
            system_dropdown = OptionMenu(mode_dialog, system, *choices)
            system_dropdown.pack(side=TOP, pady=10)
            select_button = Button(mode_dialog, text="Select", command=mode_dialog.destroy)
            select_button.pack(side=TOP, pady=10)
            mode_dialog.focus_set()
            mode_dialog.wait_window()
            self.system_mode = system
            self.default_system = system.get()
            # mode_dialog.destroy()
            return

        for line in lines:
            line = line.strip()
            if line.startswith("DEFAULTDIRECTORY"):
                self.default_directory = line.split("=", maxsplit=1)[1]
            elif line.startswith("DEFAULTSYSTEM"):
                self.default_system = line.split("=", maxsplit=1)[1]

    @staticmethod
    def find_pcgen_directory() -> str:
        """
        Function to try to find the PCGen directory to set as a default starting folder when there is no config file
        present containing a default folder (normally the last-used folder).
        """
        pcgen_folder_found = False
        path = os.path.expanduser('~')
        try:
            contents = os.listdir(path)
            if contents.count("AppData") > 0:
                path = os.path.join(path, "AppData")
                contents = os.listdir(path)
                if contents.count("Local") > 0:
                    path = os.path.join(path, "Local")
                    contents = os.listdir(path)
                    if contents.count("PCGen") > 0:
                        path = os.path.join(path, "PCGen")
                        contents = os.listdir(path)
                        for entry in contents:
                            candidate = os.path.join(path, entry)
                            if os.path.isdir(candidate) and entry.startswith("6.") and entry.count("Save") == 0:
                                path = os.path.join(candidate, "data")
                                pcgen_folder_found = True
                                break
        except Exception as e:
            print("Could not find PCGen directory.  Returning current working directory.")
            print(e)
            path = "."
        if not pcgen_folder_found:
            reg_path = AbilityGenerator.find_pcgen_directory_registry()
            if reg_path is not None:
                reg_path = os.path.join(reg_path, "data")
                return reg_path

        if not pcgen_folder_found:
            messagebox.showwarning("Could not find PCGen Directory", "Couldn't find PCGen directory in standard " +
                                   "install location.  You will need to save .lst files in a homebrew folder " +
                                   "somewhere under the 'data' folder where PCGen is installed on your system.")
        return path

    @staticmethod
    def find_pcgen_directory_registry() -> str:
        path = winreg.HKEY_LOCAL_MACHINE
        try:
            key = winreg.OpenKeyEx(path, r"SOFTWARE\\WOW6432Node\\PCGen")
            value = winreg.EnumKey(key, 0)
            if key:
                winreg.CloseKey(key)
                key = winreg.OpenKeyEx(path, r"SOFTWARE\\WOW6432Node\\PCGen\\" + value)
                value = winreg.QueryValueEx(key, "")
                if key:
                    winreg.CloseKey(key)
                return value[0]
        except Exception as e:
            print(e)
            return None

    @staticmethod
    def load_ability_lst(filename: str) -> tuple:
        """
        Function that parses a given .lst file's contents into a list of Abilities.  Also returns any header line and
        .MODs found in the file, so they can be preserved and re-written when saved again from this application to a
        .lst file later.

        :param filename: String containing fully-qualified path of .lst file to load and parse
        :returns: A tuple containing (header: str, abilities: list[Ability], mods: list[str])
        """
        with open(filename, "r") as f:
            lines = f.readlines()

        abilities = []
        mods = []
        other_entries = []
        header = ""
        for line in lines:
            line = line.strip()
            if line.strip().startswith("#"):
                pass
            elif line.count("SOURCELONG") > 0:
                header = line
            elif line.count(".MOD") > 0:
                mods.append(line)
            elif len(line) > 0:
                ability = Ability.generate_ability(lst_string=line)
                if ability is not None:
                    abilities.append(ability)
                else:
                    other_entries.append(line)
        return (header, abilities, mods, other_entries)

    @staticmethod
    def generate_ability_lst(filename: str, abilities: list, mods: list = (), other_entries: list = (),
                             header: str = "SOURCELONG:Homebrew\tSOURCESHORT:Homebrew\tSOURCEWEB:None\t#\tSOURCEDATE:" +
                                           str(datetime.datetime.now()).split(" ")[0],
                             mode: str = "Pathfinder 1e") -> None:
        """
        Writes a list of Abilities to a .lst file in PCGen format.

        :param filename: String containing fully-qualified path of .lst file to write to.
        :param abilities: List of Ability objects to convert to .lst format and write to file.
        :param mods: List of strings containing .MODs to write back to file (typically preserved from loading a .lst
                    file previously).
        :param other_entries: List of strings containing other ability entries such as class abilities that aren't
                    supported by this tool (typically preserved from loading a .lst file previously).
        :param header: String containing the initial header line of the .lst file.  Defaults to a generic header
                    specifying source as "Homebrew" with current date.
        :param mode: String defining what game/system mode context to use when writing abilities to a .lst
        """
        with open(filename, "w") as f:
            f.write("# Generated by PCGen Ability LST File Generator " +
                    "(https://github.com/Tamdrik/PCGen-Ability-LST-File-Generator)\n")
            f.write(header + "\n")
            f.write("\n")
            sorted_abilities = sorted(abilities, key=lambda x: x.fields['ability_type'] + x.fields['key'])
            for ability in sorted_abilities:
                ability.mode = mode
                f.write(str(ability) + "\n")
            if len(other_entries) > 0:
                f.write("\n# BEGIN OTHER ENTRIES (e.g., class abilities)\n")
            for entry in other_entries:
                f.write(entry + "\n")
            f.write("\n# BEGIN MODS\n")
            for mod in mods:
                f.write(mod + "\n")


class AbilityEditor(Frame):
    def __init__(self, master, generator: AbilityGenerator, loaded_ability: Ability = None):
        """
        Class to edit/create individual abilities, acting as a Frame with various GUI elements associated with ability
        characteristics.

        :param master: Same as per the Frame class
        :param generator: Instance of AbilityGenerator that maintains the list of abilities to edit/create/save.
        """
        super().__init__(master)
        self.generator = generator
        self.mode = generator.get_system()
        ability_labels = {}
        self.ability_fields = {}
        self.ability_var = {}
        self.ability_buttons = {}
        self.alignment_cb = {}
        self.loaded_ability = loaded_ability
        ability_edit_subframes = []

        # Subframe rows in main ability editing frame to organize various fields/elements of the ability
        rows = 10
        for i in range(0, rows):
            ability_edit_subframes.append(Frame(self))
        for subframe in ability_edit_subframes:
            subframe.pack(side=TOP, fill=BOTH, expand=True, pady=4)

        row = 0
        ability_labels['name'] = Label(ability_edit_subframes[row], text="Ability Name", font='bold')
        ability_labels['name'].pack(side=LEFT)
        self.ability_var['name'] = StringVar(value="")
        self.ability_fields['name'] = Entry(ability_edit_subframes[row], width=35, font='bold',
                                            textvariable=self.ability_var['name'])
        self.ability_fields['name'].pack(side=LEFT, padx=15)
        ToolTip(self.ability_fields['name'],
                msg="Recommend avoiding commas or other special characters besides hyphens,\n" +
                    "underscores, apostrophes, tildes, or parentheses to avoid potential issues (-_'~)")

        ability_labels['type'] = Label(ability_edit_subframes[row], text="Type of Ability")
        ability_labels['type'].pack(side=LEFT)
        self.ability_types = ["Feat", "GM_Award"]
        if self.mode != "D&D 5e":
            self.ability_types.append("Trait")
        self.ability_var['type'] = StringVar(value="")
        self.ability_var['type'].trace_add(mode="write", callback=self.check_delta)
        self.ability_var['type'].set("Feat")
        self.ability_type_dropdown = OptionMenu(ability_edit_subframes[row], self.ability_var['type'],
                                                *self.ability_types, command=self.update_subtype_choices)
        self.ability_type_dropdown.pack(side=LEFT)

        row = row + 1
        ability_labels['key'] = Label(ability_edit_subframes[row], text="Unique Key")
        ability_labels['key'].pack(side=LEFT)
        self.ability_var['key'] = StringVar(value="")
        self.ability_var['key'].trace_add(mode="write", callback=self.check_delta)
        self.ability_fields['key'] = Entry(ability_edit_subframes[row], width=35, textvariable=self.ability_var['key'])
        self.ability_fields['key'].pack(side=LEFT, padx=15, pady=15)
        ToolTip(self.ability_fields['key'],
                msg="Optional unique key used for referencing this ability, e.g., as a prerequisite.\nTypically the " +
                    "same as the ability name (default if blank).\n\nNote that MODs solely reference the key, " +
                    "ignoring the name field.\n\nRecommend avoiding commas or other special characters besides " +
                    "hyphens, \nunderscores, apostrophes, tildes, or parentheses to avoid potential issues (-_'~)")

        ability_labels['level'] = Label(ability_edit_subframes[row], text="Minimum Level")
        ability_labels['level'].pack(side=LEFT, padx=4)
        self.ability_var['level'] = IntVar(value=0)
        self.minimum_level_spinbox = Spinbox(ability_edit_subframes[row], textvariable=self.ability_var['level'],
                                             from_=0, to=20, width=3, command=self.check_delta)
        self.minimum_level_spinbox.pack(side=LEFT)
        ToolTip(self.minimum_level_spinbox, msg="Minimum total character level to qualify for this ability.")
        ToolTip(ability_labels['level'], msg="Minimum total character level to qualify for this ability.")

        row = row + 1
        # Stat requirements
        stats_frame = LabelFrame(ability_edit_subframes[row], text="Stat Prerequisites")
        stats_frame.pack(side=LEFT, padx=15)
        stats_left_subframe = Frame(stats_frame)
        stats_left_subframe.pack(side=LEFT, fill=Y, expand=True)
        self.stats_lb = Listbox(stats_left_subframe, height=4, width=10)
        self.stats_lb.pack(side=LEFT)
        stats_scroll = Scrollbar(stats_left_subframe)
        self.stats_lb.configure(yscrollcommand=stats_scroll.set)
        stats_scroll.config(command=self.stats_lb.yview)
        stats_scroll.pack(side=RIGHT, fill=Y)

        stats_top_subframe = Frame(stats_frame)
        stats_top_subframe.pack(side=TOP, fill=Y, expand=True)
        stats_bottom_subframe = Frame(stats_frame)
        stats_bottom_subframe.pack(side=TOP)
        self.stat_type = {}

        self.stats = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        if self.mode == "Pathfinder 1e" or self.mode == "D&D 3.5e":
            self.stats.append("BAB")

        self.ability_var['stat'] = StringVar(value="STR")
        self.stats_dropdown = OptionMenu(stats_top_subframe, self.ability_var['stat'], *self.stats)
        self.stats_dropdown.pack(side=LEFT)
        ToolTip(self.stats_dropdown, msg="Minimum stat requirement to qualify for this ability.\n")

        self.stat_value_spinbox = Spinbox(stats_top_subframe, from_=0, to=20, width=3)
        self.stat_value_spinbox.pack(side=LEFT)
        ToolTip(self.stat_value_spinbox, msg="Minimum stat requirement to qualify for this ability.")

        self.ability_buttons['remove_stat'] = Button(stats_bottom_subframe, text="Remove", width=10,
                                                     command=self.remove_stat)
        self.ability_buttons['remove_stat'].pack(side=LEFT)
        self.ability_buttons['add_stat'] = Button(stats_bottom_subframe, text="Add", width=10,
                                                  command=self.add_stat)
        self.ability_buttons['add_stat'].pack(side=LEFT)

        # Ability Subtype (e.g., "Combat", "General")
        ability_subtype_frame = LabelFrame(ability_edit_subframes[row], text="Ability Subtypes/Categories")
        self.subtypes_lb = Listbox(ability_subtype_frame, height=4, width=20)
        if self.mode == "Pathfinder 1e":
            ToolTip(ability_subtype_frame, msg="Pathfinder traits generally have a single subtype, and a character\n" +
                                               "typically can only have one trait of a given type.\n\n" +
                                               "Feat types often affect bonus feat eligibility (e.g., Fighters get\n" +
                                               "'Combat'-type bonus feats)\n\n" +
                                               "Note that GM-awarded abilities traits generally do not have " +
                                               "subtypes.")
        elif self.mode == "D&D 3.5e":
            ToolTip(ability_subtype_frame, msg="Feat types often affect bonus feat eligibility (e.g., Fighters get\n" +
                                               "'Fighter'-type bonus feats)\n\n" +
                                               "Note that GM-awarded abilities and traits generally do not have " +
                                               "subtypes.")
        self.selected_subtype = StringVar(self.master)
        self.ability_subtypes = []
        self.set_subtypes()
        if self.mode != "D&D 5e":
            self.subtype_dropdown = OptionMenu(ability_subtype_frame, self.selected_subtype, *self.ability_subtypes)
        self.ability_buttons['remove_subtype'] = Button(ability_subtype_frame, text="Remove", width=10,
                                                        command=self.remove_subtype)
        self.ability_buttons['add_subtype'] = Button(ability_subtype_frame, text="Add", width=10,
                                                     command=self.add_subtype)
        if self.mode == "Pathfinder 1e" or self.mode == "D&D 3.5e":
            ability_subtype_frame.pack(side=RIGHT, padx=15)
            self.subtypes_lb.pack(side=LEFT)

            self.subtype_dropdown.pack(side=TOP, fill=X)
            self.ability_buttons['remove_subtype'].pack(side=LEFT)
            self.ability_buttons['add_subtype'].pack(side=LEFT)

        row = row + 1
        alignment_frame = LabelFrame(ability_edit_subframes[row], text="Alignment req.")
        alignment_frame.pack(side=LEFT, padx=10)
        self.alignment_values = {}
        for alignment in ALIGNMENTS:
            self.alignment_values[alignment] = BooleanVar(self, False)
            self.alignment_values[alignment].trace_add(mode="write", callback=self.check_delta)

        good_frame = Frame(master=alignment_frame)
        good_frame.pack(side=TOP, padx=2, pady=0, expand=TRUE, fill=BOTH)
        neutral_frame = Frame(master=alignment_frame)
        neutral_frame.pack(side=TOP, padx=2, pady=0, expand=TRUE, fill=BOTH)
        evil_frame = Frame(master=alignment_frame)
        evil_frame.pack(side=TOP, padx=2, pady=0, expand=TRUE, fill=BOTH)

        for alignment in self.alignment_values.keys():
            frame = neutral_frame
            if alignment.count("G") > 0:
                frame = good_frame
            elif alignment.count("E") > 0:
                frame = evil_frame
            self.alignment_cb[alignment] = Checkbutton(frame, text=alignment.upper(),
                                                       variable=self.alignment_values[alignment], onvalue=True,
                                                       offvalue=False)
            self.alignment_cb[alignment].pack(side=LEFT, padx=2)

        feat_prerequisites_frame = LabelFrame(ability_edit_subframes[row], text="Feat Prerequisites")
        feat_prerequisites_frame.pack(side=RIGHT, padx=15)
        ToolTip(feat_prerequisites_frame, msg="Use the feat's KEY if it is different from its name.")
        self.feat_prerequisites_lb = Listbox(feat_prerequisites_frame, height=4, width=20)
        self.feat_prerequisites_lb.pack(side=LEFT)
        self.selected_feat_prerequisite = StringVar(self.master)

        ability_labels['required_feat'] = Label(feat_prerequisites_frame, text="Required Feat")
        ability_labels['required_feat'].pack(side=LEFT)
        self.feat_prerequisite_field = Entry(feat_prerequisites_frame)
        self.feat_prerequisite_field.pack(side=TOP, fill=X)
        self.ability_buttons['remove_feat_prerequisite'] = Button(feat_prerequisites_frame, text="Remove", width=10,
                                                                  command=self.remove_feat_prerequisite)
        self.ability_buttons['remove_feat_prerequisite'].pack(side=LEFT)
        self.ability_buttons['add_feat_prerequisite'] = Button(feat_prerequisites_frame, text="Add", width=10,
                                                               command=self.add_feat_prerequisite)
        self.ability_buttons['add_feat_prerequisite'].pack(side=LEFT)

        row = row + 1
        ability_labels['race_prerequisite'] = Label(ability_edit_subframes[row], text="Race Prerequisite")
        ability_labels['race_prerequisite'].pack(side=LEFT)
        if self.mode == "D&D 5e":
            self.races = ("None", "Aarakocra", "Aasimar", "Bugbear", "Bullywug", "Centaur", "Changeling", "Dhampir",
                          "Dragonborn", "Dwarf", "Elf", "Fairy", "Firbolg", "Genasi", "Gith", "Gnome", "Goblin",
                          "Goliath",
                          "Grimlock", "Grung", "Half-elf", "Half-orc", "Halfling", "Harengon", "Hexblood", "Hobgoblin",
                          "Human", "Kalashtar", "Kenku", "Kobold", "Leonin", "Lizardfolk", "Locathah", "Loxodon",
                          "Minotaur", "Orc", "Owlin", "Reborn", "Satyr", "Shifter", "Simic Hybrid", "Skeleton",
                          "Tabaxi", "Tiefling", "Tortle", "Triton", "Troglodyte", "Vedalken", "Verdan", "Warforged",
                          "Yuan-Ti Pureblood", "Zombie")
        elif self.mode == "D&D 3.5e":
            self.races = ("None", "Dwarf", "Elf", "Gnome", "Half-elf", "Half-orc", "Halfling", "Human")
        elif self.mode == "Pathfinder 1e":
            self.races = ("None", "Dwarf", "Elf", "Gnome", "Half-elf", "Half-orc", "Halfling", "Human",
                          "Aasimar", "Catfolk", "Changeling", "Dhampir", "Drow", "Fetchling", "Gathlain", "Ghoran",
                          "Goblin", "Grippli", "Ifrit", "Kitsune", "Kobold", "Merfolk", "Nagaji", "Orc", "Oread",
                          "Ratfolk", "Samsaran", "Skinwalker", "Strix", "Suli", "Svirfneblin", "Sylph", "Tengu",
                          "Tiefling", "Triton", "Undine", "Vanara", "Vine Leshy", "Vishkanya", "Wayang", "Wyrwood",
                          "Wyvaran")

        self.selected_race = StringVar(self.master)
        self.selected_race.trace_add(mode="write", callback=self.check_delta)

        self.race_dropdown = OptionMenu(ability_edit_subframes[row], self.selected_race, *self.races)
        self.selected_race.set("None")
        self.race_dropdown.pack(side=LEFT, fill=X)

        self.mult = BooleanVar()
        self.mult.trace_add(mode="write", callback=self.check_delta)
        self.stack = BooleanVar()
        self.stack.trace_add(mode="write", callback=self.check_delta)
        self.mult_cb = Checkbutton(ability_edit_subframes[row], text="Mult?", variable=self.mult, onvalue=True,
                                   offvalue=False)
        self.mult_cb.pack(side=LEFT, padx=20)
        ToolTip(self.mult_cb, msg="This ability can be taken multiple times if checked.")
        self.stack_cb = Checkbutton(ability_edit_subframes[row], text="Stack?", variable=self.stack, onvalue=True,
                                    offvalue=False)
        self.stack_cb.pack(side=LEFT)
        ToolTip(self.stack_cb, msg="This ability can stack with itself if checked.")

        row = row + 1
        ability_labels['pretext'] = Label(ability_edit_subframes[row], text="Narrative Prerequisites")
        ability_labels['pretext'].pack(side=LEFT)
        self.ability_fields['pretext'] = Entry(ability_edit_subframes[row], width=70)
        self.ability_fields['pretext'].bind("<KeyRelease>", lambda event: self.check_delta())
        self.ability_fields['pretext'].pack(side=LEFT, padx=4)
        ToolTip(ability_edit_subframes[row], msg="Other requirements/prerequisites that are not mechanically enforced" +
                                                 "\nby PCGen, but are displayed in the description.\nE.g.: \"Level 1 " +
                                                 "monk, worshiper of Asmodeus, or member of the Dark Brotherhood.\"")

        row = row + 1
        desc_frame = LabelFrame(ability_edit_subframes[row], text="Description")
        desc_frame.pack(fill=BOTH, expand=True)
        self.ability_fields['desc'] = Text(desc_frame, height=6, wrap=WORD)
        self.ability_fields['desc'].bind("<KeyRelease>", lambda event: self.check_delta())
        desc_scroll = Scrollbar(desc_frame)
        self.ability_fields['desc'].configure(yscrollcommand=desc_scroll.set)
        self.ability_fields['desc'].pack(side=LEFT, fill=BOTH, expand=True)
        desc_scroll.config(command=self.ability_fields['desc'].yview)
        desc_scroll.pack(side=RIGHT, fill=Y)

        row = row + 1
        other_fields_frame = LabelFrame(ability_edit_subframes[row], text="Other")
        other_fields_frame.pack(fill=BOTH, expand=True)
        self.other_fields_lb = Listbox(other_fields_frame, height=4, width=40)
        self.other_fields_lb.pack(side=LEFT)
        self.selected_other_field = StringVar(self.master)

        self.ability_fields['other'] = Entry(other_fields_frame)
        self.ability_fields['other'].pack(side=TOP, fill=X)
        self.ability_buttons['remove_other_field'] = Button(other_fields_frame, text="Remove", width=9,
                                                            command=self.remove_other_field)
        self.ability_buttons['remove_other_field'].pack(side=LEFT)
        self.ability_buttons['add_other_field'] = Button(other_fields_frame, text="Add", width=9,
                                                         command=self.add_other_field)
        self.ability_buttons['add_other_field'].pack(side=LEFT)
        self.ability_buttons['edit_other_field'] = Button(other_fields_frame, text="Edit", width=9,
                                                          command=self.edit_other_field)
        self.ability_buttons['edit_other_field'].pack(side=LEFT)
        self.ability_buttons['create_aspect'] = Button(other_fields_frame, text="Create ASPECT", width=12,
                                                       command=self.spawn_aspect_dialog)
        self.ability_buttons['create_aspect'].pack(side=LEFT)
        ToolTip(self.ability_buttons['create_aspect'], msg="Advanced tool: Open a wizard to create an ASPECT that " +
                                                           "adds narrative\n(typically conditional/situational) bonuses to the front of a character sheet.\n\n" +
                                                           "E.g., \"+2 to saves against charm effects\" can be added to the character's\nsaving throw " +
                                                           "information box.\n\n" +
                                                           "Can also add a resource tracker that shows a number of checkboxes\non the printed character sheet " +
                                                           "to track number of uses for the ability\n(e.g., number of rounds per day of rage).")

        ToolTip(self.ability_fields['other'],
                msg="Other tab-separated tokens not explicitly supported by this tool. Edit with caution.\n" +
                    "Examples:\nSOURCEPAGE:p.50\nBONUS:SKILL|Stealth|2|TYPE=Insight\n\n" +
                    "Note that if any existing 'other fields' are removed or modified, saving as a MOD will not\n" +
                    "work properly.  The ability will need to be saved as a new ability under a different name/key.")
        ToolTip(self.other_fields_lb,
                msg="Other tab-separated tokens not explicitly supported by this tool. Edit with caution.\n" +
                    "Examples:\nSOURCEPAGE:p.50\nBONUS:SKILL|Stealth|2|TYPE=Insight\n\n" +
                    "Note that if any existing 'other fields' are removed or modified, saving as a MOD will not\n" +
                    "work properly.  The ability will need to be saved as a new ability under a different name/key.")

        row = row + 1
        ability_edit_subframes[row].configure(height=10)
        self.ability_buttons['add_ability'] = Button(ability_edit_subframes[row], text="Add Ability",
                                                     command=self.add_ability, font=('bold', 14), width=20)
        self.ability_buttons['add_ability'].pack(side=TOP, pady=10)
        self.ability_buttons['add_mod'] = Button(ability_edit_subframes[row], text="Add as MOD",
                                                 command=self.add_mod, width=20)
        self.ability_buttons['add_mod'].pack(side=TOP, pady=0)
        ToolTip(self.ability_buttons['add_mod'], msg="Save changes to this ability as a .MOD (modification), " +
                                                     "instead of a new ability.\n\nSee 'Help\u2192" +
                                                     "What is a MOD?' for more information.")
        self.ability_buttons['save_mod'] = Button(ability_edit_subframes[row], text="Append as MOD\n to .lst file",
                                                  command=self.save_mod, width=20)
        ToolTip(self.ability_buttons['save_mod'], msg="Save changes to this ability as a .MOD (modification), " +
                                                      "appended directly to the end of an existing .lst file.\n\nSee " +
                                                      "'Help\u2192What is a MOD?' for more information.")
        self.ability_buttons['save_mod'].pack(side=TOP, pady=5)

        if self.loaded_ability is not None and self.check_delta():
            self.ability_buttons['add_mod'].configure(state="normal")
            self.ability_buttons['save_mod'].configure(state="normal")
        else:
            self.ability_buttons['add_mod'].configure(state="disabled")
            self.ability_buttons['save_mod'].configure(state="disabled")

    def check_delta(self, var=None, index=None, mode=None) -> bool:
        """
        Highlights GUI widgets containing values that have been modified when editing an existing ability and
        enables/disables MOD-related buttons as appropriate (if nothing has been modified from currently loaded
        ability, or if KEY field has been changed, cannot save/add as a MOD).

        :var, index, none: Arguments required to use this function as a callback for variable traces
        :return: Returns true if any field has been modified from the ability currently being edited (false if no
            existing ability was loaded for editing or KEY has been modified).
        """
        if self.loaded_ability is None:
            return False

        if self.ability_var['key'].get() != self.loaded_ability.fields['key']:
            self.minimum_level_spinbox.configure(background="white")
            self.stats_lb.configure(background="white")
            self.subtypes_lb.configure(background="white")
            for align in ALIGNMENTS:
                self.alignment_cb[align].configure(selectcolor="white")
            self.feat_prerequisites_lb.configure(background="white")
            self.race_dropdown.configure(background="#f0f0f0")
            self.mult_cb.configure(selectcolor="white")
            self.stack_cb.configure(selectcolor="white")
            self.ability_fields['pretext'].configure(background="white")
            self.ability_fields['desc'].configure(background="white")
            self.other_fields_lb.configure(background="white")
            self.ability_buttons['add_mod'].configure(state="disabled")
            self.ability_buttons['save_mod'].configure(state="disabled")
            return False

        modified = False
        if self.ability_var['level'].get() == self.loaded_ability.prerequisites['level']:
            self.minimum_level_spinbox.configure(background="white")
        else:
            self.minimum_level_spinbox.configure(background="yellow")
            modified = True

        stat_prerequisites = self.get_stat_prerequisites()
        stats_changed = False
        for stat in stat_prerequisites.keys():
            if stat_prerequisites[stat] != self.loaded_ability.prestat[stat]:
                stats_changed = True

        if not stats_changed:
            self.stats_lb.configure(background="white")
        else:
            self.stats_lb.configure(background="yellow")
            modified = True

        subtypes = self.subtypes_lb.get(0, END)
        subtypes_changed = (len(subtypes) != len(self.loaded_ability.fields['ability_subtypes']))
        for subtype in subtypes:
            if subtype not in self.loaded_ability.fields['ability_subtypes']:
                subtypes_changed = True
        if not subtypes_changed:
            self.subtypes_lb.configure(background="white")
        else:
            self.subtypes_lb.configure(background="yellow")
            modified = True

        for align in ALIGNMENTS:
            if self.alignment_values[align].get() == self.loaded_ability.prealign[align]:
                self.alignment_cb[align].configure(selectcolor="white")
            else:
                self.alignment_cb[align].configure(selectcolor="yellow")
                modified = True

        feats = self.feat_prerequisites_lb.get(0, END)
        feats_changed = (len(feats) != len(self.loaded_ability.prerequisites['feats']))
        for feat in feats:
            if feat not in self.loaded_ability.prerequisites['feats']:
                feats_changed = True
        if not feats_changed:
            self.feat_prerequisites_lb.configure(background="white")
        else:
            self.feat_prerequisites_lb.configure(background="yellow")
            modified = True

        if self.selected_race.get() == self.loaded_ability.prerequisites['race']:
            self.race_dropdown.configure(background="#f0f0f0")
        else:
            self.race_dropdown.configure(background="yellow")
            modified = True

        if self.mult.get() == self.loaded_ability.fields['mult']:
            self.mult_cb.configure(selectcolor="white")
        else:
            self.mult_cb.configure(selectcolor="yellow")
            modified = True

        if self.stack.get() == self.loaded_ability.fields['stack']:
            self.stack_cb.configure(selectcolor="white")
        else:
            self.stack_cb.configure(selectcolor="yellow")
            modified = True

        if self.ability_fields['pretext'].get().strip() == self.loaded_ability.fields['pretext'].strip():
            self.ability_fields['pretext'].configure(background="white")
        else:
            self.ability_fields['pretext'].configure(background="yellow")
            modified = True

        if self.ability_fields['desc'].get("1.0", END).strip() == self.loaded_ability.fields['desc'].strip():
            self.ability_fields['desc'].configure(background="white")
        else:
            self.ability_fields['desc'].configure(background="yellow")
            modified = True

        other_fields = self.other_fields_lb.get(0, END)
        other_fields_changed = (len(other_fields) != len(self.loaded_ability.other_fields))
        for field in other_fields:
            if field not in self.loaded_ability.other_fields:
                other_fields_changed = True
        if not other_fields_changed:
            self.other_fields_lb.configure(background="white")
        else:
            self.other_fields_lb.configure(background="yellow")
            modified = True

        if modified:
            if self.ability_var['type'].get() != self.loaded_ability.fields['ability_type']:
                answer = messagebox.askyesno(title="Cannot change ability type", message="Cannot modify the type of " +
                                                                                         "an ability.  Save as new ability and update key?")
                if answer:
                    self.loaded_ability = None
                    self.ability_var['key'].set(self.ability_var['type'].get() + " ~ " + self.ability_var['key'].get())
                    self.check_delta()
                    self.ability_buttons['add_mod'].configure(state="disabled")
                    self.ability_buttons['save_mod'].configure(state="disabled")
                else:
                    self.ability_var['type'].set(self.loaded_ability.fields['ability_type'])
                    self.ability_buttons['add_mod'].configure(state="normal")
                    self.ability_buttons['save_mod'].configure(state="normal")
            else:
                self.ability_buttons['add_mod'].configure(state="normal")
                self.ability_buttons['save_mod'].configure(state="normal")
        else:
            self.ability_buttons['add_mod'].configure(state="disabled")
            self.ability_buttons['save_mod'].configure(state="disabled")

        return modified

    def get_stat_prerequisites(self) -> dict:
        """
        Returns a dict of stat prerequisites applied to the current ability being edited (e.g., {'STR'=13,'DEX'=0...})
        """
        stat_prerequisites = {}
        stats = ["str", "dex", "con", "int", "wis", "cha"]
        if self.mode != "D&D 5e":
            stats.append("bab")
        for stat in stats:
            stat_prerequisites[stat] = 0
        sp_entries = self.stats_lb.get(0, END)
        for entry in sp_entries:
            (stat, value) = entry.split(":")
            stat_prerequisites[stat.lower()] = int(value)
        return stat_prerequisites

    def add_subtype(self, event=None) -> None:
        """ Modifies the current ability being edited by adding the selected subtype. """
        subtype = self.selected_subtype.get()
        if subtype == "Other (input)":
            subtype = simpledialog.askstring("Ability Subtype", "Please enter subtype to add:")
            subtype = subtype.capitalize()
            if len(subtype) < 0:
                return

        subtypes = self.subtypes_lb.get(0, END)
        if subtypes.count(subtype) == 0:
            self.subtypes_lb.insert(0, subtype)
        self.check_delta()

    def remove_subtype(self) -> None:
        """ Modifies the current ability being edited by removing the selected subtype. """
        try:
            index = self.subtypes_lb.curselection()[0]
        except IndexError:
            messagebox.showerror("No subtype selected", "Please select a subtype from the list to remove.")
            return
        self.subtypes_lb.delete(index)
        self.check_delta()

    def set_subtypes(self) -> None:
        """ Updates the subtypes dropdown box based on what ability type is selected. """
        if self.mode == "Pathfinder 1e":
            if self.ability_var['type'].get() == "Trait":
                self.ability_subtypes = ["Combat", "Faith", "Magic", "Social", "Campaign", "Equipment", "Family",
                                         "Mount", "Race", "Regional", "Religion", "Other (input)"]
            elif self.ability_var['type'].get() == "Feat":
                self.ability_subtypes = ["Combat", "General", "Item Creation", "Metamagic", "Teamwork", "Animal",
                                         "Blood Hex", "Channeling", "Conduit", "Critical", "Damnation", "Grit",
                                         "Item Mastery", "Panache", "Performance", "Weapon Mastery", "Achievement",
                                         "Betrayal", "Saga", "Story", "Style", "Stare", "Mythic", "Other (input)"]
            elif self.ability_var['type'].get() == "GM_Award":
                self.ability_subtypes = []
        if self.mode == "D&D 3.5e":
            if self.ability_var['type'].get() == "Trait":
                self.ability_subtypes = []
            elif self.ability_var['type'].get() == "Feat":
                self.ability_subtypes = ["General", "Item Creation", "Metamagic", "Wizard", "Fighter", "Special",
                                         "Ceremonial", "Other (input)"]
            elif self.ability_var['type'].get() == "GM_Award":
                self.ability_subtypes = []

    def add_feat_prerequisite(self, event=None) -> None:
        """ Modifies the current ability being edited by adding the feat prerequisite. """
        feat = self.feat_prerequisite_field.get().title()

        feats = self.feat_prerequisites_lb.get(0, END)
        if len(feat) > 0:
            if (feats.count(feat) == 0):
                self.feat_prerequisites_lb.insert(0, feat)
            else:
                messagebox.showerror("Feat already in list", "This feat is already in the list of prerequisites.")
        else:
            messagebox.showerror("No feat name provided", "Please enter the name of the feat required.")
        self.feat_prerequisite_field.delete(0, END)
        self.check_delta()

    def remove_feat_prerequisite(self) -> None:
        """ Modifies the current ability being edited by removing the selected feat prerequisite. """
        try:
            index = self.feat_prerequisites_lb.curselection()[0]
        except IndexError:
            messagebox.showerror("No feat selected", "Please select a feat from the list to remove.")
            return
        self.feat_prerequisites_lb.delete(index)
        self.check_delta()

    def add_other_field(self, event=None) -> None:
        """ Modifies the current ability being edited by adding the other field. """
        field = self.ability_fields['other'].get()

        fields = self.other_fields_lb.get(0, END)
        if len(field) > 0:
            if fields.count(field) == 0:
                self.other_fields_lb.insert(0, field)
            else:
                messagebox.showerror("Field already in list", "This field is already present.")
        else:
            messagebox.showerror("No field entered", "Please enter the field in the space provided.")
        self.ability_fields['other'].delete(0, END)
        self.check_delta()

    def remove_other_field(self) -> None:
        """ Modifies the current ability being edited by removing the selected field. """
        try:
            index = self.other_fields_lb.curselection()[0]
        except IndexError:
            messagebox.showerror("No field selected", "Please select a field from the list to remove.")
            return
        self.other_fields_lb.delete(index)
        self.check_delta()

    def edit_other_field(self) -> None:
        """ Allow user to edit an existing 'other field', removing it from the list of other fields and copying its
        contents to the text entry field. """
        try:
            index = self.other_fields_lb.curselection()[0]
        except IndexError:
            messagebox.showerror("No field selected", "Please select a field from the list to edit.")
            return
        self.ability_fields['other'].delete(0, END)
        self.ability_fields['other'].insert(END, self.other_fields_lb.get(index))
        self.other_fields_lb.delete(index)
        self.check_delta()

    def add_stat(self) -> None:
        """
        Adds a stat prerequisite to the Ability being edited (e.g., STR=13).
        """
        stat_string = self.ability_var['stat'].get() + ":" + self.stat_value_spinbox.get()
        stats = self.stats_lb.get(0, END)
        stat_already_in_list = False
        for entry in stats:
            if entry.count(self.ability_var['stat'].get()) > 0:
                stat_already_in_list = True
        if not stat_already_in_list:
            self.stats_lb.insert(0, stat_string)
        else:
            messagebox.showerror("Stat prerequisite already exists",
                                 "This ability already has a prerequisite for " + self.ability_var[
                                     'stat'].get() + ".  " +
                                 "To change the required value, remove the stat from the list first.")
        self.check_delta()

    def remove_stat(self) -> None:
        """
        Remove the selected stat prerequisite from the list.
        """
        try:
            index = self.stats_lb.curselection()[0]
        except IndexError:
            messagebox.showerror("No stat prerequisite selected", "Please select a stat prerequisite from the list " +
                                 "to remove.")
            return
        self.stats_lb.delete(index)
        self.check_delta()

    def add_ability(self) -> None:
        """
        Adds a new ability (of type Ability) to the list with characteristics defined by the current values in the
        editing frame's GUI elements.

        If the ability already exists in the list, offers the option of overwriting the old ability (effectively
        editing/modifying it).
        """
        if len(self.ability_fields['name'].get().strip()) == 0:
            messagebox.showerror("Ability has no name", "Ability name is required.")
            return
        if len(self.ability_fields['desc'].get("1.0", END).strip()) == 0:
            messagebox.showerror("Ability has no description", "Ability should have a description.")
            return
        if self.mode == "Pathfinder 1e":
            if self.ability_var['type'].get() == "Trait" and len(self.subtypes_lb.get(0, END)) == 0:
                messagebox.showerror("No trait type specified", "Traits should have a type/category specified.")
                return

        ability = self.build_ability()

        self.generator.add_ability(ability)

    def add_mod(self) -> None:
        """ Adds changes to currently-loaded ability as a new MOD to list of MODs """
        if len(self.ability_fields['name'].get().strip()) == 0:
            messagebox.showerror("Ability has no name", "Ability name is required.")
            return
        if len(self.ability_fields['desc'].get("1.0", END).strip()) == 0:
            messagebox.showerror("Ability has no description", "Ability should have a description.")
            return
        if self.mode == "Pathfinder 1e":
            if self.ability_var['type'].get() == "Trait" and len(self.subtypes_lb.get(0, END)) == 0:
                messagebox.showerror("No trait type specified", "Traits should have a type/category specified.")
                return

        modified_ability = self.build_ability()
        mod = Mod(base_ability=self.loaded_ability, modified_ability=modified_ability)

        self.generator.add_mod(mod)

    def save_mod(self) -> None:
        """
        Saves changes to currently-loaded ability as a new MOD, appended directly to the end of a .lst file.  Will
        prompt user for .lst file to append to.
        """
        filename = filedialog.asksaveasfilename(initialdir=self.generator.default_directory,
                                                title="Select a file to append to (add to any existing abilities)",
                                                confirmoverwrite=False,
                                                filetypes=(("PCGen LST Files", "*.lst"), ("All Files", "*.*")))
        modified_ability = self.build_ability()
        mod = Mod(base_ability=self.loaded_ability, modified_ability=modified_ability)

        if filename is not None and len(filename) > 0:
            if not filename.lower().endswith(".lst"):
                filename = filename + ".lst"
            if not os.path.isfile(filename):
                answer = messagebox.askokcancel("Create new .lst file?", "You entered a new .lst filename.  Do you " +
                                                "want to create a new Abilities .lst file containing only this mod?")
                if answer:
                    AbilityGenerator.generate_ability_lst(filename=filename, abilities=[], mods=[str(mod)],
                                                          other_entries=[])
                    messagebox.showinfo("Success", "Saved MOD to file: " + filename)
                    self.check_for_pcc_file(filename=filename)
                else:
                    return
            else:
                if os.path.dirname(filename).count("/data") == 0:
                    answer = messagebox.askokcancel("Warning",
                                                    "It doesn't look like this is a valid subdirectory under " +
                                                    "the PCGen 'data' folder.  PCGen will not be able to find/load " +
                                                    "sources from other locations.  Continue?")
                    if not answer:
                        return
                if os.path.isfile(filename):
                    with open(filename, "r") as f:
                        header = f.readline()
                        while header.startswith("#"):
                            header = f.readline()
                    if header.upper().count("HOMEBREW") == 0 and header.upper().count("MPC") == 0:
                        answer = messagebox.askokcancel("Warning", "It looks like this .lst file you're about to " +
                                                        "modify was not generated by this tool. Modifications to " +
                                                        "existing ability .lsts from other sources may be lost when " +
                                                        "PCGen data is updated.  Continue?")
                        if not answer:
                            return

                with open(filename, "a") as f:
                    f.write("\n" + str(mod))
                self.generator.default_directory = os.path.dirname(filename)
                messagebox.showinfo("Success", "Saved MOD to file: " + filename)

    def build_ability(self) -> Ability:
        """
        Builds an instance of Ability based on the values currently entered in the AbilityEditor GUI.
        :return: An instance of Ability
        """
        desc = self.ability_fields['desc'].get("1.0", "end")

        # Escape any % symbols that aren't associated with variables
        i = re.search("[^%]%[^0-9%]", desc)
        if i:
            desc = desc[:i.start() + 1] + "%" + desc[i.start() + 1:]

        ability = Ability(name=self.ability_fields['name'].get(), ability_type=self.ability_var['type'].get(),
                          desc=desc)

        if len(self.ability_fields['key'].get().strip()) > 0:
            ability.fields['key'] = self.ability_fields['key'].get().strip()
        if len(self.ability_fields['pretext'].get().strip()) > 0:
            ability.fields['pretext'] = self.ability_fields['pretext'].get().strip()

        ability.prerequisites['level'] = self.ability_var['level'].get()

        if self.mode == "Pathfinder 1e":
            for subtype in self.subtypes_lb.get(first=0, last=END):
                if subtype not in ability.fields['ability_subtypes']:
                    ability.fields['ability_subtypes'].append(subtype)

        ability.prerequisites['race'] = self.selected_race.get()
        ability.prerequisites['feats'] = []
        for feat in self.feat_prerequisites_lb.get(first=0, last=END):
            ability.prerequisites['feats'].append(feat)
        for statline in self.stats_lb.get(first=0, last=END):
            (stat, value) = statline.split(":")
            ability.prestat[stat.lower()] = int(value)
        for alignment in ability.prealign.keys():
            ability.prealign[alignment] = self.alignment_values[alignment].get()

        ability.fields['mult'] = self.mult.get()
        ability.fields['stack'] = self.stack.get()

        other_fields = self.other_fields_lb.get(first=0, last=END)
        if len(other_fields) > 0:
            for field in other_fields:
                if len(field.strip()) > 0:
                    ability.other_fields.append(field.strip())

        return ability

    def populate_fields(self, ability: Ability) -> None:
        """
        Called as part of the 'edit ability' function in AbilityGenerator.  This copies the characteristics of the
        provided Ability into the corresponding GUI elements in the ability editing frame.
        """
        self.loaded_ability = ability
        self.ability_var['type'].set(ability.fields['ability_type'])
        self.ability_fields['name'].delete(first=0, last=END)
        self.ability_fields['name'].insert(0, ability.fields['name'])
        self.ability_fields['key'].delete(first=0, last=END)
        self.ability_fields['key'].insert(0, ability.fields['key'])
        self.ability_fields['pretext'].delete(first=0, last=END)
        self.ability_fields['pretext'].insert(0, ability.fields['pretext'])
        self.ability_fields['desc'].delete("1.0", END)
        self.ability_fields['desc'].insert(END, ability.fields['desc'])
        self.update_subtype_choices()
        self.subtypes_lb.delete(0, END)
        for subtype in ability.fields['ability_subtypes']:
            self.subtypes_lb.insert(END, subtype)
        for alignment in self.alignment_values.keys():
            self.alignment_values[alignment].set(ability.prealign[alignment])
        self.selected_race.set(ability.prerequisites['race'])

        self.ability_var['level'].set(ability.prerequisites['level'])

        self.feat_prerequisites_lb.delete(0, END)
        for feat in ability.prerequisites['feats']:
            self.feat_prerequisites_lb.insert(END, feat)

        self.other_fields_lb.delete(first=0, last=END)
        for field in ability.other_fields:
            self.other_fields_lb.insert(END, field)
        self.ability_fields['other'].delete(0, END)

        self.stats_lb.delete(0, END)
        for stat in ("str", "dex", "con", "int", "wis", "cha", "bab"):
            if ability.prestat[stat] > 0:
                self.stats_lb.insert(END, stat.upper() + ":" + str(ability.prestat[stat]))

        if ability.fields['mult']:
            self.mult_cb.select()
        else:
            self.mult_cb.deselect()
        if ability.fields['stack']:
            self.stack_cb.select()
        else:
            self.stack_cb.deselect()
        self.check_delta()

    def update_subtype_choices(self, ability_type: StringVar = None) -> None:
        """
        Refresh the list of available subtypes to match the currently selected type.  Extra arg required due to how
        Tk events work for some reason.
        """
        if self.mode != "D&D 5e":
            self.set_subtypes()
            menu = self.subtype_dropdown['menu']
            menu.delete(0, END)
            for subtype in self.ability_subtypes:
                menu.add_command(label=subtype, command=lambda value=subtype: self.selected_subtype.set(value))

    def spawn_aspect_dialog(self) -> None:
        """
        Creates a pop-up dialog wizard to help the user create an ASPECT tag, which displays certain bonuses on the
        front page of a character sheet for ease of reference.  This is relatively complex compared to the main
        ability editing GUI, as it allows insertion of some arbitrary .lst code/logic.
        """
        self.aspect_dialog = Toplevel(self.generator.win)
        self.aspect_dialog.title("Ability Aspect Wizard")
        self.aspect_dialog.geometry("550x260")
        self.aspect_dialog.focus_set()
        self.aspect_dialog.grab_set()
        main_aspect_frame = Frame(self.aspect_dialog)
        aspect_variables_frame = Frame(self.aspect_dialog)
        aspect_buttons_frame = Frame(self.aspect_dialog)
        aspect_buttons_frame.pack(side=BOTTOM, expand=True, fill=X)
        main_aspect_frame.pack(side=LEFT, expand=True, fill=BOTH)
        aspect_variables_frame.pack(side=RIGHT, expand=True, fill=Y)
        aspect_dialog_subframes = []
        self.aspect_fields = {}
        self.aspect_label = {}
        rows = 6
        for row in range(0, rows):
            aspect_dialog_subframes.append(Frame(main_aspect_frame))
            aspect_dialog_subframes[row].pack(side=TOP, fill=X, expand=True, pady=1)

        row = 0
        self.aspect_label['type'] = Label(aspect_dialog_subframes[row], text="Type")
        self.aspect_label['type'].pack(side=LEFT)
        self.aspect_types = ["Combat", "Save", "Skill", "Resource Tracker"]
        self.selected_aspect_type = StringVar(self.master)
        self.selected_aspect_type.set("Combat")
        self.aspect_type_dropdown = OptionMenu(aspect_dialog_subframes[row], self.selected_aspect_type,
                                               *self.aspect_types, command=self.update_aspect_dialog)
        self.aspect_type_dropdown.pack(side=LEFT)

        row += 1
        self.aspect_textlabel_var = StringVar(value="Text")
        self.aspect_label['text'] = Label(aspect_dialog_subframes[row], textvariable=self.aspect_textlabel_var,
                                          font='bold')
        self.aspect_label['text'].pack(side=TOP)
        self.aspect_fields['text'] = Entry(aspect_dialog_subframes[row], width=35, font='bold')
        self.aspect_fields['text'].pack(side=LEFT, padx=15)
        ToolTip(aspect_dialog_subframes[row],
                msg="For Resource Tracker ASPECTs, this is the units of the resource tracker (e.g., rounds per day)." +
                    "\n\nFor all other ASPECTs, this is the text of the ASPECT to be displayed on the character " +
                    "sheet. Can define and insert variables (e.g., Charisma bonus) into the text using the buttons " +
                    "and fields below.")

        row += 1
        self.insert_aspect_variable_button = Button(aspect_dialog_subframes[row], text="Insert Variable \u2191",
                                                    command=self.insert_aspect_variable)
        self.insert_aspect_variable_button.pack(side=TOP)
        ToolTip(aspect_dialog_subframes[row],
                msg="For Resource Tracker ASPECTs, this sets the variable that defines how many checkboxes to show " +
                    "on the character sheet based on the value defined below.  For example, if an ability has 3 uses " +
                    "per day, simply enter '3' (without quotes) in the field below.  For 1 plus the character's " +
                    "Charisma modifier, enter '1+CHA' (without quotes) below.\n\nFor all other ASPECTs, this button " +
                    "inserts the variable defined below into the Text above at the current cursor position. For " +
                    "example, your ASPECT could show up on your character sheet as '+[CONSTITUTION BONUS] to saving " +
                    "throws vs. mind-affecting effects', where [CONSTITUTION BONUS] is defined below as 'CON'" +
                    "(without quotes).  The resulting text string will read, '+%1 to saving throws...' after " +
                    "inserting the variable.")

        row += 1
        self.aspect_label['variable'] = Label(aspect_dialog_subframes[row], text="Variable")
        self.aspect_label['variable'].pack(side=TOP)
        self.aspect_fields['variable'] = Entry(aspect_dialog_subframes[row], width=35)
        self.aspect_fields['variable'].pack(side=LEFT, padx=15)
        ToolTip(aspect_dialog_subframes[row],
                msg="Variable definition.  E.g., \"CHA+2\" would represent the value of the character's Charisma " +
                    "bonus + 2.  Note that this tool does not validate variables as being legal expressions, so if " +
                    "you insert Constitution bonus three times, you'll get a variable that reads 'CONCONCON' which " +
                    "PCGen will not understand (or will assume it's some undefined value).")

        row += 1
        self.insert_aspect_predefined_value_button = Button(aspect_dialog_subframes[row], text="Insert Value \u2191",
                                                            command=self.insert_aspect_predefined_value)
        self.insert_aspect_predefined_value_button.pack(side=TOP)
        ToolTip(aspect_dialog_subframes[row],
                msg="Insert predefined value selected below into the Variable above at the current cursor position. " +
                    "\n\nNote that some values are functions that require you to replace some placeholder text. " +
                    "E.g., 'Round down' inserts 'floor(VALUE_TO_BE_ROUNDED)'.  You will need to replace " +
                    "'VALUE_TO_BE_ROUNDED' with, well, the value to be rounded down, e.g., 'TL/2' (half total " +
                    "character level).")

        row += 1
        self.aspect_label['predefined_value'] = Label(aspect_dialog_subframes[row], text="Predefined Value")
        self.aspect_label['predefined_value'].pack(side=LEFT)
        self.predefined_values = {"Strength bonus": "STR", "Dexterity bonus": "DEX", "Constitution bonus": "CON",
                                  "Intelligence bonus": "INT", "Wisdom bonus": "WIS", "Charisma bonus": "CHA",
                                  "Total character level": "TL", "Caster level": "CL",
                                  "Round down": "floor(VALUE_TO_BE_ROUNDED)",
                                  "Greater of two values": "max(VALUE1,VALUE2)",
                                  "Smaller of two values": "min(VALUE1,VALUE2)"}
        if self.mode != "D&D 5e":
            self.predefined_values['Base attack bonus'] = "BAB"
        else:
            self.predefined_values['Proficiency bonus'] = "Proficiency_Bonus"

        self.selected_predefined_value = StringVar(self.master)
        self.selected_predefined_value.set("Strength bonus")
        self.predefined_values_dropdown = OptionMenu(aspect_dialog_subframes[row], self.selected_predefined_value,
                                                     *self.predefined_values.keys())
        self.predefined_values_dropdown.pack(side=LEFT)

        self.aspect_label['variables'] = Label(master=aspect_variables_frame, text="Variables")
        self.aspect_label['variables'].pack(side=TOP)
        self.aspect_variables_lb = Listbox(master=aspect_variables_frame, width=40, height=3)
        self.aspect_variables_lb.pack(side=TOP, fill=Y, expand=True)
        remove_variable_button = Button(aspect_variables_frame, text="Remove Variable",
                                        command=self.remove_aspect_variable)
        remove_variable_button.pack(side=LEFT)

        add_aspect_button = Button(aspect_buttons_frame, text="Add ASPECT", font=('bold', 14), command=self.add_aspect)
        add_aspect_button.pack(side=TOP)

    def insert_aspect_variable(self) -> None:
        """
        For Resource Tracker ASPECTs, this sets the variable that defines how many checkboxes to show on the printed
        character sheet.
        For all other ASPECTs, this inserts the current variable into the ASPECT's text at the current cursor position.
        """
        variable = self.aspect_fields['variable'].get().strip()
        if len(variable) == 0:
            messagebox.showerror("No variable defined", "The variable field is blank")
            self.surface_dialog(self.aspect_dialog)
            return
        if self.selected_aspect_type.get() == "Resource Tracker":
            if len(self.aspect_variables_lb.get(0, END)) > 0:
                messagebox.showerror("Variable already defined", "Resource Tracker ASPECTs only require a single " +
                                     "variable (how many checkboxes to display on the character sheet), and one is " +
                                     "already defined.  Remove it if you need to change it.")
                self.surface_dialog(self.aspect_dialog)
            else:
                self.aspect_variables_lb.insert(0, variable)
        else:
            cursor_pos = self.aspect_fields['text'].index(INSERT)
            variable_number = len(self.aspect_variables_lb.get(0, END)) + 1
            self.aspect_fields['text'].insert(index=cursor_pos, string="%" + str(variable_number))
            self.aspect_variables_lb.insert(variable_number - 1, variable)

    def insert_aspect_predefined_value(self) -> None:
        """
        This inserts a predefined value (e.g., CHA for a character's Charisma bonus) into the Variable field at the
        current cursor position.
        """
        cursor_pos = self.aspect_fields['variable'].index(INSERT)
        predefined_value = self.predefined_values[self.selected_predefined_value.get()]
        self.aspect_fields['variable'].insert(index=cursor_pos, string=predefined_value)

    def remove_aspect_variable(self) -> None:
        """
        Removes selected variable from the list of variables in an ASPECT.  If there are multiple variables defined,
        this will automatically renumber the variables' placeholders in the text as necessary.
        """
        try:
            index = self.aspect_variables_lb.curselection()[0]
        except IndexError:
            messagebox.showerror(parent=self.aspect_dialog, title="No variable selected",
                                 message="Please select a variable from the list to remove.")
            self.surface_dialog(self.aspect_dialog)
            return

        current_text = self.aspect_fields['text'].get()
        current_text = current_text.replace("%" + str(index + 1), "")
        for i in range(index + 1, len(self.aspect_variables_lb.get(0, END))):
            current_text = current_text.replace("%" + str(i + 1), "%" + str(i))
        self.aspect_fields['text'].delete(0, END)
        self.aspect_fields['text'].insert(0, current_text)
        self.aspect_variables_lb.delete(index)

    def update_aspect_dialog(self, arg) -> None:
        """
        Updates the dialog GUI elements to reflect slight differences between Resource Tracker ASPECTs and others
        whenever a new ASPECT type is selected.
        :param arg: Requires a second argument for some reason.
        """
        if self.selected_aspect_type.get() == "Resource Tracker":
            self.aspect_textlabel_var.set("Units")
            self.insert_aspect_variable_button.configure(text="Set Variable \u2192")
        else:
            self.aspect_textlabel_var.set("Text")
            self.insert_aspect_variable_button.configure(text="Insert Variable \u2191")

    def add_aspect(self) -> None:
        """
        Adds the aspect defined in the wizard dialog box to the list of "other fields" in the ability currently being
        edited in the main GUI.
        """
        aspect = ""
        if self.selected_aspect_type.get() == "Resource Tracker":
            if len(self.aspect_variables_lb.get(0, END)) > 0:
                aspect = aspect + "ASPECT:CheckCount|%1|" + self.aspect_variables_lb.get(0)
                self.other_fields_lb.insert(END, aspect)
                if len(self.aspect_fields['text'].get()) > 0:
                    aspect = "ASPECT:CheckType|" + self.aspect_fields['text'].get().strip()
                    self.other_fields_lb.insert(END, aspect)
            else:
                messagebox.showerror(parent=self.aspect_dialog, title="No variable defined",
                                     message="Resource Tracker ASPECTs require a variable to define " +
                                             "how many checkboxes to show on the character sheet.  Please define a " +
                                             "variable and use the \"Set Variable\" button to set it.")
                self.surface_dialog(self.aspect_dialog)
                return
        else:
            if len(self.aspect_fields['text'].get()) > 0:
                tags = {"Combat": "CombatBonus", "Skill": "SkillBonus", "Save": "SaveBonus"}
                aspect = "ASPECT:" + tags[self.selected_aspect_type.get()] + "|" + self.aspect_fields['text'].get()
                variables = self.aspect_variables_lb.get(0, END)
                for var in variables:
                    aspect = aspect + "|" + var
                self.other_fields_lb.insert(END, aspect)
            else:
                messagebox.showerror(parent=self.aspect_dialog, title="No text defined",
                                     message="No text is defined to display on character sheet.")
                self.surface_dialog(self.aspect_dialog)
                return
        self.aspect_dialog.destroy()
        self.check_delta()

    @staticmethod
    def surface_dialog(dialog: Toplevel) -> None:
        """
        Raises the given Toplevel dialog window to the top so that it isn't obscured by the main window, e.g., when
        a messagebox is called from the dialog.
        :param dialog: Toplevel dialog to raise above other windows/dialogs.
        """
        dialog.attributes("-topmost", True)
        dialog.attributes("-topmost", False)


def main():
    """
    ability = Ability(name="Test Feat", ability_type="Feat", subtypes=["Combat", "Critical"], required_str=13,
                      required_dex=15, desc="This is a description of a feat", required_race="Half-Orc",
                      required_bab=11, mult=True,
                      required_feats=["Power Attack", "Weapon Finesse"], other_fields=["SOURCEPAGE:p.50"])
    ability.prealign["LG"] = True
    ability.prealign["LN"] = True
    ability.prealign["LE"] = True
    ability.prerequisites['level'] = 5
    print(ability)

    ability2 = copy.deepcopy(ability)
    ability2.fields['desc'] = "New Desc"
    ability2.prerequisites['race'] = "Human"
    mod = Mod(base_ability=ability, modified_ability=ability2)
    print(mod)

    subtypes = ["Race"]
    ability = Ability(name="Test Trait", ability_type="Trait", subtypes=subtypes, required_race="Half-Orc",
                      desc="This is a description of a trait", key="Trait ~ Test",
                      other_fields=["SOURCEPAGE:p.50"])
    ability.prealign["LG"] = True
    ability.prealign["LN"] = True
    ability.prealign["LE"] = True
    print(ability)

    ability2 = copy.deepcopy(ability)
    ability2.prerequisites['level'] = 6
    ability2.fields['mult'] = True

    mod = Mod(base_ability=ability, modified_ability=ability2)
    print(mod)
    """
    ag = AbilityGenerator()
    ag.run()


if __name__ == '__main__':
    main()
