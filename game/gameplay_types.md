# Gameplay-relevant types (extracted from sinking_star.exe)

Full dump: `types.txt` / `types.json` (592 structs, 174 enums), regenerate with `python dump_types.py`.

## How to identify an entity in memory
Every entity struct starts with `entity: Entity` (size 0x330). Inside `Entity`:

| offset | field | use |
|---|---|---|
| 0x000 | `undoable_data.position: Vector3` | logical position (floats, grid-aligned) |
| 0x018 | `undoable_data.orientation: Quaternion` | facing |
| 0x028 | `undoable_data.entity_flags` | |
| 0x030 | `undoable_data.entity_name: string` | |
| 0x05c | `undoable_data.status_flags` | |
| 0x0a0 | `undoable_data.visual_position: Vector3` | animated position (== position when settled) |
| 0x0f0 | `entity_manager: *Entity_Manager` | same for all entities in a level |
| 0x100 | `entity_id: Pid` | |
| 0x108 | `entity_type: Type` | **pointer to the kind's Type_Info_Struct in the exe** (rebased by ASLR) |

## Entity kinds we care about
- **Terrain:** `Wall` (blocks; floor = top of a wall column), `Fence` (`blocking`, `is_floor`, `is_solid_wall`), `Stairs`, `Elevator_Platform`, `Roots`, `Tree`
- **Player characters:** `Guy` (`skill_flags: Skill_Flags`, `inventory_flags: Inventory_Flags`, `turn_order`, `dead_t`)
- **Pushables / movers:** `Rock`, `Mirror`, `Rover`, `Lily` (`moving_direction`), `Boat`, `Egg`
- **Creatures:** `Monster`, `Baby_Dragon` (`baby_dragon_state`, `gems_stored`), `Friendly_Dragon`, `Npc`
- **Puzzle state:** `Switch` (`pressed`), `Gate` (`open`, `notted`), `Door` (`open`, `target_level`), `Gem` (`attached_to_entity_id`, `inventory_index`), `Gem_Slot`, `Teleporter` (`target_id`, `discovered`), `Activator`, `Spawner`, `Freezer` (`unfrozen`), `Checkpoint`, `Arrow` (`direction`), `Treasure` (`found`), `Wardrobe` (gives skills/items), `Artifact`
- **Navigation:** `Level_Entry` (`level_name`), `Level_Connector`, `Tower`
- **Hint text:** `Sign` (`line1`, `line2`, `line3`, `look_at_bark`); also `Guy.initial_bark` / `win_bark`
- **Ignore (visual/dev):** `Decal`, `Fog*`, `Light_Probe`, `Point_Light`, `Sky`, `Sun`, `Particle_*`, `Camera_*`, `Audio_Marker`, `Ripples`, `Shadow_Decal`, `Note` (dev notes), `Playtest_Note`, …

## Key enums
- `Direction`: NONE=0, EAST=1, NORTH=2, WEST=3, SOUTH=4, UP=5, DOWN=6
- `Skill_Flags`: MULTIPUSH=1, SINGLE_PUSH=2, PULL=4, TELEPORT=8, PROTECTION=16, TRANSMUTE=32, CHARM=64, TAKE_GEMS=128, QUEEN=256, SAILOR=1024, TRADER=2048
- `Inventory_Flags`: OPEN=1, THROUGH=2, SMASH=4, DOUBLE=8, STRONG=16, ENDPOINT=32, ALTER=128, GEM=256, SQUEEZE=512, WAND=1024, TORC=2048, PRISM=4096, WOOD=8192
- `Baby_Dragon_State`: JUST_FED, EAGER_WAIT, WAITING_FURTHER_AWAY, WANDERING

## Open questions for step 2
- `Entity_Manager` has no field info in the exe, so the entity list must be found by scanning memory for the `entity_type` pointers above.
- How floor vs wall vs water is encoded (Wall height? a separate terrain grid?) — check by looking at live data.
- Which UI struct holds the currently-displayed hint/bark text.
