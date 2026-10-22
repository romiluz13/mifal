const form = document.querySelector('#goal-form');
const goal = document.querySelector('#goal');
const start = document.querySelector('#start-shift');
const order = document.querySelector('#order-goal');
const status = document.querySelector('#shift-status');
const state = document.querySelector('#shift-state');
const pause = document.querySelector('#pause-shift');
const replay = document.querySelector('#replay-shift');
const steps = [...document.querySelectorAll('[data-step]')];
const floors = [...document.querySelectorAll('[data-floor]:not([data-floor="record"])')];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const film = document.querySelector('#inspection-film');
const filmStatus = document.querySelector('#film-status');
const watch = document.querySelector('#watch-hold');
const hero = document.querySelector('#hero-workshop');
const filmPanel = document.querySelector('.hero-film');
const names = ['Goal', 'Brief', 'Hold', 'Repair', 'Recheck', 'Ship'];
const messages = ['A goal goes in.', 'A brief goes out.', 'The line stops.', 'A new attempt.', 'Check the correction.', 'Reviewed work ships.'];
const duration = 18000;
const capable = typeof Animation === 'function' && typeof KeyframeEffect === 'function';
let effects = [];
let frame;
let position = 0;
let elapsed = 0;
let playing = false;
let started = false;
let introUsed = false;
let introActive = false;

function setFloor(floor, index) {
  floor.dataset.stage = String(index);
  floor.querySelector('.floor-state').textContent = names[index];
  floor.querySelector('.floor-message').textContent = messages[index];
}

function show(index) {
  position = index;
  steps.forEach((step, i) => step.setAttribute('aria-pressed', String(i === index)));
  state.textContent = names[index];
  status.textContent = steps[index].nextElementSibling.textContent;
  floors.forEach(floor => setFloor(floor, index));
}

function stop() {
  if (effects.length) elapsed = Number(effects[0].currentTime) || 0;
  effects.forEach(effect => effect.pause());
  cancelAnimationFrame(frame);
  playing = false;
  introActive = false;
  pause.textContent = 'Resume';
}

function clearEffects() {
  effects.forEach(effect => effect.cancel());
  effects = [];
}

function prepare() {
  clearEffects();
  if (!capable || reduced.matches) return;
  const tracks = [
    ['.floor-ticket', [
      {transform:'translateX(0%)',offset:0}, {transform:'translateX(25%)',offset:1/6},
      {transform:'translateX(50%)',offset:2/6}, {transform:'translateX(50%)',offset:3/6},
      {transform:'translateX(50%)',offset:4/6}, {transform:'translateX(200%)',offset:5/6},
      {transform:'translateX(200%)',offset:1}
    ]],
    ['.floor-gate', [
      {transform:'rotate(-90deg)',offset:0}, {transform:'rotate(-90deg)',offset:.29},
      {transform:'rotate(0deg)',offset:2/6}, {transform:'rotate(0deg)',offset:.63},
      {transform:'rotate(-90deg)',offset:4/6}, {transform:'rotate(-90deg)',offset:1}
    ]],
    ['.floor-part', [
      {opacity:0,transform:'translateY(-25px)',offset:0}, {opacity:0,transform:'translateY(-25px)',offset:.46},
      {opacity:1,transform:'translateY(0)',offset:3/6}, {opacity:1,transform:'translateY(0)',offset:.76},
      {opacity:0,transform:'translateY(0)',offset:5/6}, {opacity:0,transform:'translateY(0)',offset:1}
    ]],
    ['.ticket-check', [
      {opacity:0,offset:0}, {opacity:0,offset:.64}, {opacity:1,offset:4/6}, {opacity:1,offset:1}
    ]],
    ['.floor-belt', [
      {transform:'translateX(0)',offset:0}, {transform:'translateX(-44px)',offset:2/6},
      {transform:'translateX(-44px)',offset:.64}, {transform:'translateX(-88px)',offset:5/6},
      {transform:'translateX(-88px)',offset:1}
    ]]
  ];
  floors.forEach(floor => tracks.forEach(([selector, keyframes]) => {
    const effect = new Animation(new KeyframeEffect(floor.querySelector(selector), keyframes, {duration,fill:'both'}), document.timeline);
    effect.currentTime = elapsed;
    effects.push(effect);
  }));
}

function tick() {
  if (!playing) return;
  elapsed = Number(effects[0].currentTime) || 0;
  const index = Math.min(5, Math.floor(elapsed / 3000));
  if (index !== position) show(index);
  if (elapsed >= duration) {
    stop();
    pause.disabled = true;
    return;
  }
  frame = requestAnimationFrame(tick);
}

function play() {
  if (reduced.matches || !capable || document.hidden) return;
  if (!effects.length) prepare();
  const startTime = document.timeline.currentTime - elapsed;
  effects.forEach(effect => {
    effect.play();
    effect.startTime = startTime;
  });
  playing = true;
  pause.textContent = 'Pause';
  pause.disabled = false;
  frame = requestAnimationFrame(tick);
}

function begin() {
  stop();
  introUsed = true;
  introActive = false;
  started = true;
  elapsed = 0;
  order.textContent = goal.value.trim() || goal.placeholder;
  floors.forEach(floor => {floor.querySelector('.ticket-goal').textContent = order.textContent;});
  show(0);
  clearEffects();
  replay.disabled = false;
  pause.disabled = reduced.matches || !capable;
  closeFilm();
  play();
}

function select(index) {
  stop();
  introActive = false;
  elapsed = index * 3000;
  effects.forEach(effect => {effect.currentTime = elapsed;});
  show(index);
  pause.disabled = !started || reduced.matches || !capable || index === 5;
}

form.addEventListener('submit', event => {event.preventDefault(); begin();});
replay.addEventListener('click', begin);
pause.addEventListener('click', () => {if (playing) stop(); else play();});
steps.forEach((step, index) => {
  step.disabled = false;
  step.addEventListener('click', () => select(index));
});

function applyMotionPreference() {
  stop();
  clearEffects();
  film.pause();
  show(position);
  pause.disabled = !started || reduced.matches || !capable || position === 5;
  watch.disabled = reduced.matches;
  document.querySelector('#mode-note').textContent = reduced.matches
    ? 'Reduced motion: choose each step to see its still state.'
    : 'Choose a step to pause the illustration at that moment.';
  filmStatus.textContent = reduced.matches ? 'Reduced motion: the film is paused. The still story remains available.' : 'Illustration. A generated inspection shot, played only when you choose.';
}
reduced.addEventListener('change', applyMotionPreference);
applyMotionPreference();

function closeFilm() {
  film.pause();
  filmPanel.hidden = true;
  watch.setAttribute('aria-expanded', 'false');
}
watch.addEventListener('click', () => {
  if (reduced.matches) return;
  stop();
  introUsed = true;
  filmPanel.hidden = false;
  watch.setAttribute('aria-expanded', 'true');
  if (!film.getAttribute('src')) film.src = 'media/workshop.mp4';
  filmStatus.textContent = 'Illustration: one generated inspection shot. It ends with the line on HOLD.';
  film.play().catch(() => {
    if (filmPanel.hidden) return;
    filmStatus.textContent = 'Use the film controls to play. The written shift remains available.';
  });
});
document.querySelector('#close-film').addEventListener('click', () => {closeFilm(); watch.focus();});
film.addEventListener('error', () => {
  closeFilm();
  filmStatus.textContent = 'The inspection film could not load. The still and written steps remain available.';
});
film.addEventListener('play', () => {if (reduced.matches || document.hidden) film.pause();});

const visibleFloors = new Set();
const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) visibleFloors.add(entry.target);
    else visibleFloors.delete(entry.target);
  });
  const heroVisible = visibleFloors.has(hero);
  if (introActive && !heroVisible) {
    stop();
    introActive = false;
  } else if (playing && !visibleFloors.size) {
    stop();
  }
  if (!heroVisible) film.pause();
  if (!introUsed && heroVisible && !reduced.matches && capable && !document.hidden) {
    introUsed = true;
    introActive = true;
    started = true;
    replay.disabled = false;
    play();
  }
});
observer.observe(hero);
observer.observe(document.querySelector('.work-order'));
document.addEventListener('visibilitychange', () => {
  document.documentElement.classList.toggle('document-hidden', document.hidden);
  if (document.hidden) {introUsed = true; stop(); film.pause();}
});
addEventListener('pagehide', () => {introUsed = true; stop(); film.pause();});

const articles = [...document.querySelectorAll('[data-beat]')];
const recordFloor = document.querySelector('[data-floor="record"]');
const links = [...document.querySelectorAll('.record-rail a')];
recordFloor.querySelector('.ticket-goal').textContent = 'Ship Mifal as a product.';
const recordStages = [0,1,1,1,2,3,2,5,5];
const rail = document.querySelector('.record-rail');
const strip = rail.querySelector('ol');
let recordIndex = -1;
let scrollFrame;
function readRecord() {
  scrollFrame = undefined;
  const compact = innerWidth <= 700;
  const railHeight = rail.offsetHeight;
  const line = compact ? railHeight + 20 : innerHeight * .4;
  const padding = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
  document.documentElement.style.setProperty('--record-offset', `${Math.max(0, railHeight + 10 - padding)}px`);
  let index = 0;
  articles.forEach((article, i) => {if (article.getBoundingClientRect().top <= line) index = i;});
  let recordStage = recordStages[index];
  if (index === 5 && articles[index].getBoundingClientRect().top < line - articles[index].offsetHeight * .35) recordStage = 4;
  setFloor(recordFloor, recordStage);
  document.querySelector('.record-theatre').dataset.event = articles[index].dataset.beat;
  document.querySelector('#record-state').textContent = articles[index].querySelector('h2').textContent;
  links.forEach((link, i) => {
    if (i === index) link.setAttribute('aria-current', 'step');
    else link.removeAttribute('aria-current');
  });
  if (index !== recordIndex && compact) {
    const item = links[index].parentElement.getBoundingClientRect();
    const bounds = strip.getBoundingClientRect();
    if (item.left < bounds.left) strip.scrollLeft += item.left - bounds.left;
    else if (item.right > bounds.right) strip.scrollLeft += item.right - bounds.right;
  }
  recordIndex = index;
}
function scheduleRecord() {if (scrollFrame === undefined) scrollFrame = requestAnimationFrame(readRecord);}
const recordObserver = new IntersectionObserver(scheduleRecord);
articles.forEach(article => recordObserver.observe(article));
addEventListener('scroll', scheduleRecord, {passive:true});
addEventListener('resize', scheduleRecord);
addEventListener('pageshow', scheduleRecord);
addEventListener('hashchange', scheduleRecord);
readRecord();

document.querySelectorAll('img').forEach(image => {
  function unavailable() {
    image.hidden = true;
    if (image.id === 'workshop-poster') {
      filmStatus.textContent = 'The workshop illustration could not load. Explore the written shift below.';
    }
  }
  image.addEventListener('error', unavailable);
  if (image.complete && !image.naturalWidth) unavailable();
});
const copy = document.querySelector('#copy');
copy.disabled = false;
copy.addEventListener('click', async () => {
  const text = document.querySelector('#install-cmd').innerText.replace(/^\$ /gm, '');
  try {await navigator.clipboard.writeText(text); copy.textContent = 'Copied';}
  catch {copy.textContent = 'Select commands above to copy';}
});
start.disabled = false;
goal.disabled = false;
watch.disabled = reduced.matches;
