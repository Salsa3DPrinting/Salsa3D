// Kanto world logic. Positions come from kanto_data.js, written by `python -m kanto` along with the world.
import { ItemStack, Player, SignSide, system, world } from "@minecraft/server";
import { DATA } from "./kanto_data.js";

const overworld = () => world.getDimension("overworld");
const key = (x, y, z) => `${x},${y},${z}`;
const buttons = new Map((DATA.buttons ?? []).map((b) => [key(...b.p), b]));
const cooldown = new Map(); // `${player.id}:${what}` -> tick when allowed again

function ready(player, what, ticks) {
  const k = `${player.id}:${what}`;
  if ((cooldown.get(k) ?? 0) > system.currentTick) return false;
  cooldown.set(k, system.currentTick + ticks);
  return true;
}

function title(player, text, subtitle) {
  player.onScreenDisplay.setTitle(text, { subtitle, fadeInDuration: 10, stayDuration: 60, fadeOutDuration: 20 });
}

// ---- signs: the world file already holds the text; this re-applies it if a sign ever comes up blank ----
const signsLeft = new Set((DATA.signs ?? []).map((_, i) => i));
system.runInterval(() => {
  const dim = overworld();
  for (const i of [...signsLeft]) {
    const s = DATA.signs[i];
    let block;
    try {
      block = dim.getBlock({ x: s.p[0], y: s.p[1], z: s.p[2] });
    } catch {
      continue;
    }
    if (!block) continue; // chunk not loaded yet
    const sign = block.getComponent("minecraft:sign");
    if (sign) {
      if (sign.getText(SignSide.Front) !== s.t) sign.setText(s.t, SignSide.Front);
      if (!sign.isWaxed) sign.setWaxed(true);
    }
    signsLeft.delete(i);
  }
}, 40);

// ---- location titles, like the place-name pop-up in the games ----
const lastRegion = new Map();
function regionAt(x, z) {
  let best;
  let bestArea = Infinity;
  for (const r of DATA.regions ?? []) {
    const [x0, z0, x1, z1] = r.b;
    if (x >= x0 && x < x1 + 1 && z >= z0 && z < z1 + 1) {
      const area = (x1 - x0 + 1) * (z1 - z0 + 1);
      if (area < bestArea) {
        best = r;
        bestArea = area;
      }
    }
  }
  return best;
}
system.runInterval(() => {
  for (const p of world.getAllPlayers()) {
    const r = regionAt(p.location.x, p.location.z);
    const name = r?.n ?? "";
    if (lastRegion.get(p.id) === name) continue;
    lastRegion.set(p.id, name);
    if (!r) continue;
    if (r.in) p.onScreenDisplay.setActionBar(r.s ? `${r.n} - ${r.s}` : r.n);
    else title(p, r.n, r.s);
  }
}, 10);

// ---- buttons ----
const NOTES = [0.7, 0.8, 0.9, 0.7, 1.05, 1.2]; // a short healing jingle
const ITEMS = {
  poke_ball: { id: "minecraft:snowball", count: 16, name: "Poké Ball", say: "You got 16 POKé BALLS! Try throwing one!" },
  potion: { id: "minecraft:honey_bottle", count: 1, name: "Potion", say: "You got a POTION!" },
};

const ACTIONS = {
  heal(p) {
    if (!ready(p, "heal", 80)) return;
    p.sendMessage("§dNURSE JOY:§r OK, I'll take your POKéMON for a few seconds...");
    NOTES.forEach((pitch, i) => system.runTimeout(() => p.playSound("note.pling", { pitch }), 6 * i + 10));
    system.runTimeout(() => {
      p.getComponent("minecraft:health")?.resetToMaxValue();
      title(p, "§aAll healed!", "Your POKéMON are fighting fit!");
      p.sendMessage("§dNURSE JOY:§r We hope to see you again!");
    }, 6 * NOTES.length + 16);
  },
  give(p, b) {
    const item = ITEMS[b.item];
    if (!item || !ready(p, `give:${b.item}`, 40)) return;
    const stack = new ItemStack(item.id, item.count);
    stack.nameTag = item.name;
    p.getComponent("minecraft:inventory")?.container?.addItem(stack);
    p.playSound("random.pop");
    p.sendMessage(`§bCLERK:§r ${item.say}`);
  },
  starter(p, b) {
    if (!ready(p, "starter", 40)) return;
    const had = p.getDynamicProperty("kanto:starter");
    if (had) {
      p.sendMessage(`§6PROF. OAK:§r You already chose ${had}! Take good care of it.`);
      return;
    }
    p.setDynamicProperty("kanto:starter", b.pokemon);
    p.playSound("random.levelup");
    title(p, `You chose ${b.pokemon}!`, "Your adventure begins!");
    p.sendMessage(`§6PROF. OAK:§r ${b.pokemon} is a great choice! The first GYM is in VIRIDIAN CITY, north of here.`);
  },
  badge(p, b) {
    if (!ready(p, "badge", 60)) return;
    const badges = JSON.parse(p.getDynamicProperty("kanto:badges") ?? "[]");
    if (badges.includes(b.badge)) {
      p.sendMessage(`§c${b.leader}:§r You already have the ${b.badge}. Badges: ${badges.length}/8`);
      return;
    }
    badges.push(b.badge);
    p.setDynamicProperty("kanto:badges", JSON.stringify(badges));
    p.playSound("random.levelup");
    title(p, `You defeated ${b.leader}!`, `You got the ${b.badge}!`);
    p.sendMessage(`§c${b.leader}:§r Impressive! Take the ${b.badge}. Badges: ${badges.length}/8`);
  },
};

world.afterEvents.buttonPush.subscribe((ev) => {
  const { x, y, z } = ev.block.location;
  const b = buttons.get(key(x, y, z));
  if (b && ev.source instanceof Player) ACTIONS[b.a]?.(ev.source, b);
});

// ---- spinner tiles: an arrow under your feet slides you one block per 2 ticks until you reach a plain tile ----
const DIRS = { "^": [0, -1], v: [0, 1], "<": [-1, 0], ">": [1, 0] };
const sliding = new Set();
system.runInterval(() => {
  for (const sp of DATA.spinners ?? []) {
    const rows = sp.g.length;
    const cols = sp.g[0].length;
    for (const p of world.getAllPlayers()) {
      const { x, y, z } = p.location;
      const c = Math.floor(x) - sp.o[0];
      const r = Math.floor(z) - sp.o[1];
      const onFloor = y >= sp.y + 0.9 && y <= sp.y + 1.3; // not mid-jump
      const d = r >= 0 && r < rows && c >= 0 && c < cols && onFloor ? DIRS[sp.g[r][c]] : undefined;
      if (!d) {
        sliding.delete(p.id);
        continue;
      }
      const nc = c + d[0];
      const nr = r + d[1];
      if (nr < 0 || nr >= rows || nc < 0 || nc >= cols || sp.g[nr][nc] === "#") continue; // stuck on a wall
      if (!sliding.has(p.id)) {
        sliding.add(p.id);
        p.playSound("random.click");
      }
      p.teleport({ x: sp.o[0] + nc + 0.5, y: sp.y + 1, z: sp.o[1] + nr + 0.5 }, { keepVelocity: false });
    }
  }
}, 2);

// ---- tall grass: wild POKéMON pop up (just a message, nothing to fight) ----
const lastPos = new Map();
system.runInterval(() => {
  for (const p of world.getAllPlayers()) {
    const { x, y, z } = p.location;
    const prev = lastPos.get(p.id);
    lastPos.set(p.id, { x, z });
    if (!prev || Math.hypot(x - prev.x, z - prev.z) < 0.5) continue;
    const g = (DATA.grass ?? []).find(
      (g) => x >= g.b[0] && x < g.b[2] + 1 && z >= g.b[1] && z < g.b[3] + 1 && Math.abs(y - g.y) < 0.6
    );
    if (!g || Math.random() > 0.06 || !ready(p, "wild", 100)) continue;
    const mon = g.w[Math.floor(Math.random() * g.w.length)];
    p.playSound("random.pop");
    p.onScreenDisplay.setActionBar(`§eA wild ${mon} appeared!`);
    system.runTimeout(() => p.isValid && p.onScreenDisplay.setActionBar(`§7The wild ${mon} ran away...`), 50);
  }
}, 10);

// ---- first visit ----
world.afterEvents.playerSpawn.subscribe((ev) => {
  const p = ev.player;
  if (!ev.initialSpawn || p.getDynamicProperty("kanto:welcomed")) return;
  p.setDynamicProperty("kanto:welcomed", true);
  system.runTimeout(() => {
    if (!p.isValid) return;
    title(p, "Welcome to KANTO!", "Visit PROF. OAK's LAB to pick a POKéMON");
    p.sendMessage("Explore PALLET TOWN, take ROUTE 1 north to VIRIDIAN CITY, and try the GYM!");
  }, 60);
});
