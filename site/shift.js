const form = document.querySelector('#goal-form');
const goal = document.querySelector('#goal');
const start = document.querySelector('#start-shift');
const order = document.querySelector('#order-goal');
const status = document.querySelector('#shift-status');
const state = document.querySelector('#shift-state');
const pause = document.querySelector('#pause-shift');
const replay = document.querySelector('#replay-shift');
const steps = [...document.querySelectorAll('[data-step]')];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const film = document.querySelector('#inspection-film');
const filmStatus = document.querySelector('#film-status');
const inspection = document.querySelector('.inspection');
let timer;
let position = 0;
let playing = false;
let started = false;

function stop() {
  clearTimeout(timer);
  playing = false;
  pause.textContent = 'Resume';
}

function show(index) {
  position = index;
  steps.forEach((step, i) => step.setAttribute('aria-pressed', String(i === index)));
  state.textContent = steps[index].textContent.trim().replace(/^\d+/, '').trim();
  status.textContent = steps[index].nextElementSibling.textContent;
}

function schedule() {
  clearTimeout(timer);
  if (!playing || reduced.matches) return;
  timer = setTimeout(() => {
    show(position + 1);
    if (position === steps.length - 1) {
      stop();
      pause.disabled = true;
    } else {
      schedule();
    }
  }, 3000);
}

function begin() {
  stop();
  started = true;
  order.textContent = goal.value.trim() || goal.placeholder;
  show(0);
  replay.disabled = false;
  pause.disabled = reduced.matches;
  if (!reduced.matches) {
    playing = true;
    pause.textContent = 'Pause';
    schedule();
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  begin();
});
replay.addEventListener('click', begin);
pause.addEventListener('click', () => {
  if (playing) stop();
  else {
    playing = true;
    pause.textContent = 'Pause';
    schedule();
  }
});
steps.forEach((step, index) => {
  step.disabled = false;
  step.addEventListener('click', () => {
    stop();
    show(index);
    pause.disabled = !started || reduced.matches || index === steps.length - 1;
  });
});

function applyMotionPreference() {
  stop();
  film.pause();
  pause.disabled = !started || reduced.matches || position === steps.length - 1;
  document.querySelector('#mode-note').textContent = reduced.matches
    ? 'Reduced motion: choose each step. The film plays only when you ask.'
    : 'Choose a step to pause the illustration at that moment.';
}
reduced.addEventListener('change', applyMotionPreference);
applyMotionPreference();
film.addEventListener('error', () => {
  filmStatus.textContent = 'The inspection film could not load. The still and written steps remain available.';
});
film.querySelector('source').addEventListener('error', () => {
  filmStatus.textContent = 'The inspection film could not load. The still and written steps remain available.';
});
inspection.addEventListener('toggle', () => {
  if (!inspection.open) film.pause();
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stop();
    film.pause();
  }
});
addEventListener('pagehide', () => {
  stop();
  film.pause();
});

document.querySelectorAll('img').forEach(image => {
  function unavailable() {
    image.hidden = true;
    if (image.id === 'workshop-poster') {
      image.parentElement.querySelector('figcaption').textContent = 'The workshop illustration could not load. Explore the written shift below.';
    }
  }
  image.addEventListener('error', unavailable);
  if (image.complete && !image.naturalWidth) unavailable();
});
const copy = document.querySelector('#copy');
copy.disabled = false;
copy.addEventListener('click', async () => {
  const text = document.querySelector('#install-cmd').innerText.replace(/^\$ /gm, '');
  try {
    await navigator.clipboard.writeText(text);
    copy.textContent = 'Copied';
  } catch {
    copy.textContent = 'Select commands above to copy';
  }
});
start.disabled = false;
goal.disabled = false;
