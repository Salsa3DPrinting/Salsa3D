import * as THREE from "three";
import { OrbitControls } from "/static/vendor/OrbitControls.js";
import { STLLoader } from "/static/vendor/STLLoader.js";

const $ = (s) => document.querySelector(s);
let CAT = null;
let lastJob = null;

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw Object.assign(new Error(data.error || (data.errors || []).join(" ")), { data });
  return data;
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k);
  return e;
}

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${b.dataset.tab}`));
}));

// ---------- fitting picker ----------
function fittingPicker(container, id) {
  container.innerHTML = "";
  const type = el("select", { id: `${id}-type` });
  for (const [k, v] of Object.entries(CAT.fittings)) type.append(el("option", { value: k }, v.label));
  const size = el("select", { id: `${id}-size` });
  const text = el("input", { id: `${id}-text`, placeholder: "e.g. 4in sch40 pvc spigot, 2\" fnpt, 1.5 tri-clamp" });
  const fill = () => {
    const keep = size.value;
    size.innerHTML = "";
    for (const s of CAT.fittings[type.value].sizes) size.append(el("option", { value: s.spec }, `${s.size} in`));
    if ([...size.options].some((o) => o.value === keep)) size.value = keep;
  };
  type.addEventListener("change", fill);
  fill();
  container.append(el("label", {}, "Type", type), el("label", {}, "Size", size),
    el("label", {}, "…or type it (overrides the lists)", text));
  return () => text.value.trim() || size.value;
}

let getA = null, getB = null;

function fillFanSelect() {
  const sel = $("#side-a");
  const keep = sel.value;
  sel.innerHTML = "";
  for (const f of CAT.fans) sel.append(el("option", { value: f.id }, f.name + (f.verified ? "" : "  (unverified)")));
  sel.append(el("option", { value: "__fitting__" }, "— a fitting instead of a fan —"));
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
  showFanSummary();
}

function showFanSummary() {
  const id = $("#side-a").value;
  $("#side-a-fitting").classList.toggle("hidden", id !== "__fitting__");
  const f = CAT.fans.find((x) => x.id === id);
  $("#fan-summary").textContent = f ? `${f.frame} mm frame, ${f.hole_d} mm holes on a ${f.bolt_circle_d.toFixed(1)} mm` +
    ` bolt circle, ${f.bore_d} mm opening${f.notes ? ". " + f.notes : ""}` : "";
}
$("#side-a").addEventListener("change", showFanSummary);

// ---------- generate ----------
$("#make-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("#make-error").textContent = "";
  const a = $("#side-a").value === "__fitting__" ? getA() : $("#side-a").value;
  const options = {};
  for (const k of Object.keys(CAT.defaults)) options[k] = $(`#opt-${k}`).value;
  $("#go").disabled = true;
  $("#busy").classList.remove("hidden");
  $("#result").classList.add("hidden");
  try {
    showResult(await api("/api/generate", { a, b: getB(), options }));
  } catch (e) {
    $("#make-error").textContent = e.message;
  } finally {
    $("#go").disabled = false;
    $("#busy").classList.add("hidden");
  }
});

const LABELS = {
  name: "Name", bore_d: "Air opening Ø", flange_t: "Flange thickness", frame: "Frame", bolt_circle_d: "Bolt circle Ø",
  hole_d: "Hole Ø", holes: "Holes", pipe_od: "Pipe OD", spigot_od: "Spigot OD", spigot_id: "Spigot ID",
  spigot_length: "Spigot length", fitting_socket_depth: "Fitting socket depth", socket_id: "Socket ID",
  socket_depth: "Socket depth", stop_ledge_id: "Pipe stop ID", flange_od: "Ferrule flange OD", tube_od: "Tube OD",
  bore: "Bore", gasket_bead_d: "Gasket groove Ø", groove_w: "Groove width", groove_depth: "Groove depth",
  bevel_deg: "Bevel angle (deg)", tpi: "Threads per inch", major_d_at_tip: "Thread OD at tip",
  major_d_at_thread_end: "Thread OD at end", thread_length: "Thread length", radial_clearance: "Clearance per side",
  major_d_at_mouth: "Thread major Ø at mouth", tapped_depth: "Threaded depth", outer_d: "Outside Ø",
  bore_below_thread: "Bore below thread",
};

function showResult(r) {
  lastJob = r.job;
  $("#r-title").textContent = r.title;
  const w = $("#r-warnings");
  w.innerHTML = "";
  for (const msg of r.warnings) w.append(el("div", { class: "warn" }, msg));
  const t = $("#r-table");
  t.innerHTML = "";
  const row = (k, v) => t.append(el("tr", {}, el("th", {}, k), el("td", {}, String(v))));
  row("Overall length", `${r.overall_length_mm} mm (${r.overall_length_in} in)`);
  row("Size (X × Y × Z)", r.extents_mm.join(" × ") + " mm");
  row("Fits", Object.entries(r.fits_bed).map(([p, ok]) => `${p}: ${ok ? "yes" : "NO"}`).join(", "));
  row("Transition", `ID ${r.transition.from_id} → ${r.transition.to_id} mm over ${r.transition.taper_length} mm`);
  for (const [side, info] of Object.entries(r.fittings)) {
    const parts = Object.entries(info).filter(([k]) => k !== "name" && k !== "fan_id")
      .map(([k, v]) => `${LABELS[k] || k}: ${v}`);
    row(`${side}: ${info.name}`, parts.join(" · "));
  }
  if (r.bolt_access) row("Bolt access", r.bolt_access.ok ? "clear" : "BLOCKED, see warning");
  const base = `/api/jobs/${encodeURIComponent(r.job)}/`;
  const files = $("#r-files");
  files.innerHTML = "";
  const describe = (n) => n.endsWith(".3mf") ? "adapter, 3MF (open in Bambu Studio)" : n.startsWith("fit-") ?
    "fit-test print" : n.endsWith(".stl") ? "adapter, STL" : n.endsWith("section.png") ? "section image" :
    n.endsWith(".png") ? "preview image" : "report";
  for (const n of [...r.files, "report.json"]) {
    files.append(el("li", {}, el("a", { href: base + encodeURIComponent(n) + "?download=1" }, n), ` — ${describe(n)}`));
  }
  $("#r-folder").textContent = r.folder;
  $("#r-section").src = base + encodeURIComponent(`${r.stem}-section.png`);
  $("#result").classList.remove("hidden");
  showModel(base + encodeURIComponent(`${r.stem}.stl`));
}

$("#open-folder").addEventListener("click", () => lastJob && api("/api/open-folder", { job: lastJob }).catch(() => {}));

// ---------- 3D viewer ----------
let viewer = null;
function showModel(url) {
  const box = $("#viewer");
  if (!viewer) {
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    box.append(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 1, 10000);
    camera.up.set(0, 0, 1);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    scene.add(sun);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    viewer = { renderer, scene, camera, controls, sun, mesh: null };
    const resize = () => {
      const w = box.clientWidth, h = box.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    new ResizeObserver(resize).observe(box);
    resize();
    const loop = () => {
      controls.update();
      sun.position.copy(camera.position);
      renderer.render(scene, camera);
      requestAnimationFrame(loop);
    };
    loop();
  }
  new STLLoader().load(url, (geom) => {
    if (viewer.mesh) { viewer.scene.remove(viewer.mesh); viewer.mesh.geometry.dispose(); }
    geom.computeVertexNormals();
    const color = getComputedStyle(document.documentElement).getPropertyValue("--part").trim() || "#4a7ab5";
    viewer.mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color, metalness: 0.05, roughness: 0.6 }));
    viewer.scene.add(viewer.mesh);
    geom.computeBoundingSphere();
    const { center, radius } = geom.boundingSphere;
    viewer.controls.target.copy(center);
    viewer.camera.position.set(center.x + radius * 2.2, center.y - radius * 2.6, center.z + radius * 1.6);
    viewer.camera.near = radius / 50;
    viewer.camera.far = radius * 50;
    viewer.camera.updateProjectionMatrix();
  });
}

// ---------- fans ----------
function fillFanTable() {
  const t = $("#fan-table");
  t.innerHTML = "";
  t.append(el("tr", {}, ...["Name", "Frame", "Bolt circle", "Holes", "Opening", "Status", ""].map((h) => el("th", {}, h))));
  for (const f of CAT.fans) {
    const actions = el("td");
    if (!f.builtin) {
      actions.append(el("button", { class: "link", onclick: () => editFan(f) }, "Edit"), " ",
        el("button", { class: "link", onclick: () => deleteFan(f) }, "Delete"));
    } else actions.append(el("span", { class: "muted small" }, "built-in"));
    const status = el("span", { class: "badge" + (f.verified ? " ok" : "") }, f.verified ? "verified" : "unverified");
    t.append(el("tr", { title: f.notes || "" }, el("td", {}, f.name, el("div", { class: "muted small" },
      [f.added_by, f.added_on].filter(Boolean).join(", "))),
      el("td", {}, `${f.frame} mm`), el("td", {}, `Ø${f.bolt_circle_d.toFixed(1)}`), el("td", {}, `4 × Ø${f.hole_d}`),
      el("td", {}, `Ø${f.bore_d}`), el("td", {}, status), actions));
  }
  $("#fan-error").textContent = CAT.fan_error || "";
}

function buildFanForm() {
  const box = $("#fan-fields");
  box.innerHTML = "";
  for (const [k, f] of Object.entries(CAT.fan_fields)) {
    const input = el("input", { name: k, type: "number", step: "any", min: f.min, max: f.max });
    const lab = el("label", { id: `row-${k}` }, `${f.label} (mm)`, input, el("span", { class: "small" }, f.help));
    box.append(lab);
  }
}

let editing = null;
function openFanEditor(f) {
  editing = f;
  const form = $("#fan-form");
  form.reset();
  $("#fan-form-errors").innerHTML = "";
  $("#fan-editor-title").textContent = f ? `Edit ${f.name}` : "Add a fan";
  if (f) {
    for (const k of ["name", "added_by", "notes", ...Object.keys(CAT.fan_fields)]) form.elements[k].value = f[k] ?? "";
    form.elements.verified.checked = !!f.verified;
    form.elements.name.readOnly = true;
  } else form.elements.name.readOnly = false;
  setPattern("circle");
  $("#fan-editor").classList.remove("hidden");
  $("#fan-editor").scrollIntoView({ behavior: "smooth" });
}
const editFan = (f) => openFanEditor(f);
$("#new-fan").addEventListener("click", () => openFanEditor(null));
$("#fan-cancel").addEventListener("click", () => $("#fan-editor").classList.add("hidden"));

function setPattern(p) {
  const form = $("#fan-form");
  form.elements.pattern.value = p;
  $("#spacing-row").classList.toggle("hidden", p !== "spacing");
  $("#row-bolt_circle_d").classList.toggle("hidden", p === "spacing");
}
document.querySelectorAll("input[name=pattern]").forEach((r) => r.addEventListener("change", () => setPattern(r.value)));

$("#fan-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const fan = { name: form.elements.name.value, added_by: form.elements.added_by.value, notes: form.elements.notes.value,
    verified: form.elements.verified.checked };
  if (editing) { fan.id = editing.id; fan.added_on = editing.added_on; }
  for (const k of Object.keys(CAT.fan_fields)) fan[k] = form.elements[k].value;
  if (form.elements.pattern.value === "spacing") { fan.bolt_circle_d = ""; fan.hole_spacing = form.elements.hole_spacing.value; }
  const errs = $("#fan-form-errors");
  errs.innerHTML = "";
  try {
    await api("/api/fans", { fan, overwrite: !!editing });
    $("#fan-editor").classList.add("hidden");
    await refresh();
  } catch (e) {
    for (const m of e.data?.errors || [e.message]) errs.append(el("li", {}, m));
  }
});

async function deleteFan(f) {
  if (!confirm(`Delete ${f.name} from the library? Everyone using this library will lose it.`)) return;
  try { await api("/api/fans/delete", { id: f.id }); await refresh(); } catch (e) { alert(e.message); }
}

// ---------- settings ----------
$("#settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  try {
    await api("/api/settings", { fan_library: form.elements.fan_library.value, output_dir: form.elements.output_dir.value });
    $("#settings-msg").textContent = "Saved.";
    await refresh();
  } catch (e) { $("#settings-msg").textContent = e.message; }
});
$("#quit").addEventListener("click", async () => {
  await api("/api/quit", {}).catch(() => {});
  document.body.innerHTML = "<main><div class='card'>The app has stopped. You can close this tab.</div></main>";
});

// ---------- init ----------
async function refresh() {
  CAT = await api("/api/catalog");
  fillFanSelect();
  fillFanTable();
  const s = $("#settings-form").elements;
  s.fan_library.value = CAT.settings.fan_library;
  s.output_dir.value = CAT.settings.output_dir;
  $("#version").textContent = CAT.version;
}

(async () => {
  await refresh();
  getA = fittingPicker($("#side-a-fitting"), "a");
  getB = fittingPicker($("#side-b-fitting"), "b");
  for (const [k, v] of Object.entries(CAT.defaults)) $(`#opt-${k}`).value = v;
  buildFanForm();
})();
