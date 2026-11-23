"use strict";

const replay = window.doomReplay;
const frames = replay.frames;
const last = frames.length - 1;
const byId = (id) => document.getElementById(id);
const seek = byId("seek");
const player = byId("play");
const image = byId("frame");
const changedFacts = byId("changed-facts");
const allFacts = byId("facts");
const measurements = byId("measurements");
const measurementDetails = measurements.closest("details");
const previousFrame = byId("previous");
const nextFrame = byId("next");
const previousChange = byId("previous-change");
const nextChange = byId("next-change");

const displayFrames = [];
const changeFrames = [];
let lastImage = null;
for (const [index, row] of frames.entries()) {
  if (row.frame) lastImage = row;
  displayFrames.push(lastImage);
  if (Object.keys(row.changes).length) changeFrames.push(index);
}

let selected = 0;
let animation = null;
let playStart = 0;
let playFrom = 0;
let activeChange = null;
let activeFacts = null;

const numbers = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 });
function valueText(value) {
  if (value == null) return "unknown";
  if (typeof value === "number") return numbers.format(value);
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function writeValues(list, entries) {
  const rows = entries.map(([name, value]) => {
    const row = document.createElement("div");
    const key = document.createElement("dt");
    const contents = document.createElement("dd");
    key.textContent = name;
    contents.textContent = value;
    row.append(key, contents);
    return row;
  });
  list.replaceChildren(...rows);
}

function writeMeasurements() {
  const row = frames[selected];
  const action = row.action == null ? "unavailable" :
    Object.entries(row.action).map(([name, value]) => `${name} ${valueText(value)}`).join(", ") || "none";
  writeValues(measurements, [
    ["Native tick", valueText(row.native_tic)],
    ["Engine action", action],
    ...Object.entries(row.variables).map(([name, value]) => [name, valueText(value)]),
  ]);
}

function render(index) {
  selected = Math.min(last, Math.max(0, index));
  const row = frames[selected];
  const display = displayFrames[selected];
  image.hidden = !display;
  if (display && image.getAttribute("src") !== display.frame) {
    image.src = display.frame;
  }
  byId("frame-caption").textContent = row.frame ? "RGB rendered from the recorded player commands" :
    display ? `No RGB at tick ${row.tic}. Showing the last available frame from tick ${display.tic}.` :
    `No RGB available at tick ${row.tic}.`;
  seek.value = selected;
  const timeText = `${(row.tic / replay.ticrate).toFixed(2)} s · tick ${row.tic}`;
  seek.setAttribute("aria-valuetext", timeText);
  byId("time").textContent = timeText;

  const recent = changeFrames.findLast((change) => change <= selected);
  byId("change-caption").textContent = recent == null ? "No changes by this tick." :
    recent === selected ? `Changed at tick ${row.tic}` : `Most recent change · tick ${frames[recent].tic}`;
  if (recent !== activeChange) {
    activeChange = recent;
    writeValues(changedFacts, recent == null ? [] :
      Object.entries(frames[recent].changes).map(([name, { before, after }]) => [
        name, `${valueText(before)} → ${valueText(after)}`,
      ]));
  }
  if (recent !== activeFacts) {
    activeFacts = recent;
    writeValues(allFacts, Object.entries(row.facts).map(([name, value]) => [name, valueText(value)]));
  }
  if (measurementDetails.open) writeMeasurements();
  previousFrame.disabled = selected === 0;
  nextFrame.disabled = selected === last;
  previousChange.disabled = !changeFrames.some((change) => change < selected);
  nextChange.disabled = !changeFrames.some((change) => change > selected);
}

function pause() {
  if (animation !== null) cancelAnimationFrame(animation);
  animation = null;
  player.textContent = "Play";
}

function animate(now) {
  const desired = Math.min(last, playFrom + Math.floor((now - playStart) * replay.ticrate / 1000));
  if (desired !== selected) render(desired);
  if (selected === last) pause();
  else animation = requestAnimationFrame(animate);
}

function move(index) {
  pause();
  render(index);
}

player.addEventListener("click", () => {
  if (animation !== null) {
    pause();
    return;
  }
  if (selected === last) render(0);
  playFrom = selected;
  playStart = performance.now();
  player.textContent = "Pause";
  animation = requestAnimationFrame(animate);
});
seek.addEventListener("input", () => move(Number(seek.value)));
previousFrame.addEventListener("click", () => move(selected - 1));
nextFrame.addEventListener("click", () => move(selected + 1));
previousChange.addEventListener("click", () => move(changeFrames.findLast((change) => change < selected)));
nextChange.addEventListener("click", () => move(changeFrames.find((change) => change > selected)));
measurementDetails.addEventListener("toggle", () => { if (measurementDetails.open) writeMeasurements(); });
document.addEventListener("keydown", (event) => {
  if (event.target === seek || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  move(selected + (event.key === "ArrowLeft" ? -1 : 1));
});

document.title = `${replay.title} · Doom replay`;
byId("title").textContent = replay.title;
byId("outcome").textContent = replay.outcome;
byId("recording").textContent = replay.recording;
seek.max = last;
player.disabled = last === 0;
render(0);
