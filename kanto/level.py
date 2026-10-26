"""level.dat for the Kanto world, modeled on a level.dat saved by Bedrock 1.20 (Mojang's minecraft-creator-tools
test world) with game rules set for young kids exploring in Adventure mode.

The version fields are deliberately older than the player's game (26.x), which upgrades the file on first load;
a world claiming a newer version than the game would be refused.
"""

from __future__ import annotations

import time

from kanto.nbt import Byte, List, Long
from kanto.world import flat_layers_json

GAME_VERSION = [1, 21, 60, 0, 0]  # matches the block-state version the chunks are written with
SURVIVAL, CREATIVE, ADVENTURE = 0, 1, 2


def level_dat(name: str, spawn: tuple[int, int, int], flat_layers: list[tuple[str, int]],
              game_type: int = ADVENTURE, time_of_day: int = 6000) -> dict:
    b0, b1 = Byte(0), Byte(1)
    return {
        "abilities": {
            "attackmobs": b1, "attackplayers": b0, "build": b1, "doorsandswitches": b1, "flying": b0,
            "flySpeed": 0.5, "instabuild": b0, "invulnerable": b0, "lightning": b0, "mayfly": b0,
            "mine": b1, "op": b0, "opencontainers": b1, "teleport": b1, "walkSpeed": 0.1,
        },
        "baseGameVersion": "*",
        "BiomeOverride": "",
        "bonusChestEnabled": b0,
        "bonusChestSpawned": b0,
        "CenterMapsToOrigin": b0,
        "cheatsEnabled": b0,
        "commandblockoutput": b0,
        "commandblocksenabled": b0,
        "commandsEnabled": b1,
        "ConfirmedPlatformLockedContent": b0,
        "currentTick": Long(0),
        "daylightCycle": 0,
        "Difficulty": 0,  # peaceful: no hostile mobs
        "dodaylightcycle": b0,
        "doentitydrops": b0,
        "dofiretick": b0,
        "doimmediaterespawn": b1,
        "doinsomnia": b0,
        "domobloot": b0,
        "domobspawning": b0,
        "dotiledrops": b0,
        "doweathercycle": b0,
        "drowningdamage": b0,
        "educationFeaturesEnabled": b0,
        "eduOffer": 0,
        "experiments": {"experiments_ever_used": b0, "saved_with_toggled_experiments": b0},
        "falldamage": b0,
        "firedamage": b0,
        "FlatWorldLayers": flat_layers_json(flat_layers),
        "ForceGameType": b0,
        "freezedamage": b0,
        "functioncommandlimit": 10000,
        "GameType": game_type,
        "Generator": 2,  # flat: anything outside the built area is plain grass
        "hasBeenLoadedInCreative": b0,
        "hasLockedBehaviorPack": b0,
        "hasLockedResourcePack": b0,
        "immutableWorld": b0,
        "InventoryVersion": "1.21.60",
        "isCreatedInEditor": b0,
        "isExportedFromEditor": b0,
        "isFromLockedTemplate": b0,
        "isFromWorldTemplate": b0,
        "isRandomSeedAllowed": b0,
        "isSingleUseWorld": b0,
        "isWorldTemplateOptionLocked": b0,
        "keepinventory": b1,
        "LANBroadcast": b1,
        "LANBroadcastIntent": b1,
        "lastOpenedWithVersion": List(GAME_VERSION),
        "LastPlayed": Long(int(time.time())),
        "LevelName": name,
        "lightningLevel": 0.0,
        "lightningTime": 100000,
        "limitedWorldDepth": 16,
        "LimitedWorldOriginX": 0,
        "LimitedWorldOriginY": 32767,
        "LimitedWorldOriginZ": 0,
        "limitedWorldWidth": 16,
        "maxcommandchainlength": 65535,
        "MinimumCompatibleClientVersion": List(GAME_VERSION),
        "mobgriefing": b0,
        "MultiplayerGame": b1,
        "MultiplayerGameIntent": b1,
        "naturalregeneration": b1,
        "NetherScale": 8,
        "NetworkVersion": 588,  # from the 1.20 template; the game rewrites it
        "permissionsLevel": 0,
        "Platform": 2,
        "PlatformBroadcastIntent": 2,
        "playerPermissionsLevel": 1,
        "prid": "",
        "pvp": b0,
        "rainLevel": 0.0,
        "rainTime": 100000,
        "RandomSeed": Long(1996),
        "randomtickspeed": 0,  # nothing grows, spreads or decays
        "requiresCopiedPackRemovalCheck": b0,
        "respawnblocksexplode": b0,
        "sendcommandfeedback": b1,
        "serverChunkTickRange": 4,
        "showbordereffect": b1,
        "showcoordinates": b1,
        "showdeathmessages": b0,
        "showtags": b1,
        "spawnMobs": b0,
        "spawnradius": 0,
        "SpawnV1Villagers": b0,
        "SpawnX": spawn[0],
        "SpawnY": spawn[1],
        "SpawnZ": spawn[2],
        "startWithMapEnabled": b0,
        "StorageVersion": 10,
        "texturePacksRequired": b0,
        "Time": Long(time_of_day),
        "tntexplodes": b0,
        "useMsaGamertagsOnly": b0,
        "worldStartCount": Long(4294967294),
        "WorldVersion": 1,
        "XBLBroadcastIntent": 2,
    }
