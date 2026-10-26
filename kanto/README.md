# Kanto: a Pokémon-themed Minecraft Bedrock world

Generated from code: `python -m kanto` writes `output/kanto/Kanto.mcworld` plus two top-down maps
(`map_roofs.png`, `map_floorplan.png`). Built for Bedrock 1.26.5x; no Minecraft or Amulet needed to build.

## What's in it (first slice)

- **Pallet Town**: your house (2 floors), Blue's house, Prof. Oak's Lab (press a button on a Poké Ball to pick
  Bulbasaur, Charmander or Squirtle), a garden, and the sea to the south.
- **Route 1**: winding path, tall grass where wild Pidgey and Rattata "appear" (an on-screen message), and ledges.
  You can hop down a ledge but not climb back up it, the same as in the games. The path climbs them on ramps.
- **Viridian City**: Pokémon Center (button heals you, with a jingle), Poké Mart (buttons give "Poké Balls"
  (snowballs you can throw) and "Potions"), Trainer School, a house, a pond. **Viridian Gym** has the spinner-tile
  maze from FireRed/LeafGreen: arrow tiles slide you until you land on a plain tile. Reach Giovanni and press
  the gold button for the Earth Badge.
- Routes 2, 21 and 22 are fenced with "coming soon" signs.

The world is set to Adventure mode: players can walk, open doors and press buttons but can't break or place
blocks. Peaceful, always daytime, no fall/fire/drowning damage, mobs off, coordinates shown.

## Install and upload to a Realm

1. Get `Kanto.mcworld` onto a Windows PC, iPhone/iPad or Android device that has Minecraft, and open it
   (double-click or "Open in Minecraft"). It imports as a new world called **Kanto**. Consoles can't import
   `.mcworld` files directly.
2. Optionally open it once in single player to look around.
3. Realm → Edit Realm (pencil) → Replace World → pick **Kanto**. This overwrites what is on the Realm, so
   download a backup of the current Realm world first if you want to keep it.
4. In the Realm's settings, check the game mode is Adventure (the Realm's own setting may override the
   world's).

The world contains a small behavior pack (`behavior_packs/KantoScripts`, JavaScript, `@minecraft/server`
2.0.0, no experimental toggles). It runs the buttons, gym tiles, sign text, location titles and wild-grass
messages. Without it the buildings are still all there, but the buttons and arrow tiles do nothing.

## Things to check on the first test

These couldn't be tested without the game:

- [ ] The world opens and you spawn on the path south of your house in Pallet Town.
- [ ] Signs show their text and face the way you approach them (`GROUND_SIGN` / `FACING` in `build.py`).
- [ ] The arrows printed on the gym's magenta tiles point the way they slide you. If they're mirrored, flip
      `ARROW_FACING` in `buildings.py`. The sliding itself follows the maze grid, so it's right either way.
- [ ] Buttons work: Pokémon Center heal, Mart items, Oak's starters, Giovanni's badge. A location title
      appears when you enter a town.
- [ ] The beds in your house look whole, and the stairs to the 2nd floor face up the right way.

## Code

- `world.py`: in-memory world → LevelDB chunk records (sub-chunk format 9, chunk version 40) → `.mcworld`.
- `leveldb.py`: writes the database as a single log, the same layout Mojang ships its own world templates in.
- `nbt.py`: little-endian NBT. `level.py`: level.dat and game rules.
- `blocks.py` + `data/bedrock_blocks.json`: every block and state is checked against Bedrock's block list
  (PyMCTranslate's 26.40 data, cross-checked with Mojang's 1.26.50 `mojang-blocks.json`).
- `build.py`: terrain, trees, walls, roofs, signs, buttons. `buildings.py`: Pokémon Center, Mart, Gym, houses,
  lab, school. `places.py`: the map. `gym_puzzle.py`: the spinner maze and a solver.
- `pack/KantoScripts`: the behavior pack. `scripts/kanto_data.js` (positions) is generated per build.

Tests: `python -m pytest -q tests/test_kanto.py` (format round-trips, maze is winnable, signs/buttons/doors).
With `amulet-core` installed, one more test reads the world back through Mojang's LevelDB.
