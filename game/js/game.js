// game.js — GSSdle v8

const State = {
  allCards:    [],
  todayCards:  [],
  placed:      [],      // {card, pointsEarned, wrongAttempts}
  wrongMarkers:[],      // {guessedPct, cardIndex}
  currentIndex: 0,
  score:        0,
  attempts:     0,
  results:      [],
  gameOver:     false,
  touchClone:   null,
  touchOffsetX: 0,
  touchOffsetY: 0,
};

// ── LAYOUT CONSTANTS ──────────────────────────────────────────────────────────
const CARD_SIZE = 150;  // square card px
const SPACING   = 180;  // px between card centers
const TRACK_Y   = 260;  // px from canvas top to track line
const STEM_H    = 24;   // stem height px

// ── SEEDED RANDOM (same date = same shuffle for all players) ──────────────────
function seededRandom(seed) {
  let s = seed;
  return function() {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return (s >>> 0) / 0xffffffff;
  };
}

function getDailySeed() {
  // Seed based on Pacific date — resets at midnight Pacific
  const pac = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Los_Angeles' }));
  return pac.getFullYear() * 10000 + (pac.getMonth() + 1) * 100 + pac.getDate();
}

function shuffleWithSeed(arr, seed) {
  const a   = [...arr];
  const rng = seededRandom(seed);
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// ── LAYOUT ────────────────────────────────────────────────────────────────────
// Single source of truth for card positions.
// Newest placed card is always centered in the viewport.
// All other cards are spaced SPACING apart on either side by sorted order.
function layout() {
  const wrap = document.getElementById('timeline-scroll-wrap');
  const vw   = wrap ? wrap.clientWidth : window.innerWidth;

  if (State.placed.length === 0) {
    return { sorted: [], positions: [], canvasWidth: vw, scrollTarget: 0 };
  }

  const sorted    = [...State.placed].sort((a, b) => a.card.pct - b.card.pct);
  const newest    = State.placed[State.placed.length - 1];
  const newestIdx = sorted.findIndex(e => e.card.id === newest.card.id);

  const positions = sorted.map((_, i) => vw / 2 + (i - newestIdx) * SPACING);

  const minX        = Math.min(...positions) - SPACING;
  const maxX        = Math.max(...positions) + SPACING;
  const shift       = minX < SPACING ? SPACING - minX : 0;
  const shifted     = positions.map(p => p + shift);
  const canvasWidth = Math.max(vw, maxX + shift + SPACING);
  const scrollTarget= shift;

  return { sorted, positions: shifted, canvasWidth, scrollTarget };
}

// ── INIT ──────────────────────────────────────────────────────────────────────
async function init() {
  try {
    const res = await fetch('data/cards.json');
    State.allCards = await res.json();
    setupTodayCards();
    renderGame();
  } catch(e) {
    showError('Could not load cards. Please refresh.');
    console.error(e);
  }
}

function setupTodayCards() {
  const schedule = getTodaySchedule();
  if (schedule) {
    const map = Object.fromEntries(State.allCards.map(c => [c.id, c]));
    State.todayCards = schedule.cardIds.map(id => map[id]).filter(Boolean);
  } else {
    State.todayCards = pickRandom(State.allCards, 8, 2.0);
  }

  // Sort by pct — establishes correct ordering for placement logic
  State.todayCards = [...State.todayCards].sort((a, b) => a.pct - b.pct);

  // Shuffle presentation order using daily seed — same for all players each day
  State.todayCards = shuffleWithSeed(State.todayCards, getDailySeed());

  // Pre-place first card (free — no points)
  State.placed.push({ card: State.todayCards[0], pointsEarned: 0, wrongAttempts: 0 });
  State.currentIndex = 1;
}

function pickRandom(cards, n, minGap) {
  const shuffled = [...cards].sort(() => Math.random() - 0.5);
  const picked   = [];
  for (const c of shuffled) {
    if (picked.length >= n) break;
    if (picked.every(p => Math.abs(p.pct - c.pct) >= minGap)) picked.push(c);
  }
  return picked;
}

// ── CONVERT clientX TO RELATIVE PCT ──────────────────────────────────────────
function clientXtoRelativePct(clientX) {
  const inner = document.getElementById('tl-inner');
  if (!inner) return 50;
  const rect    = inner.getBoundingClientRect();
  const canvasX = clientX - rect.left;

  const { sorted, positions } = layout();
  if (sorted.length === 0) return 50;

  if (canvasX < positions[0])                    return sorted[0].card.pct - 1;
  if (canvasX > positions[positions.length - 1]) return sorted[sorted.length - 1].card.pct + 1;

  for (let i = 0; i < positions.length - 1; i++) {
    if (canvasX >= positions[i] && canvasX <= positions[i + 1]) {
      const t = (canvasX - positions[i]) / (positions[i + 1] - positions[i]);
      return sorted[i].card.pct + t * (sorted[i + 1].card.pct - sorted[i].card.pct);
    }
  }
  return 50;
}

// ── RENDER GAME ───────────────────────────────────────────────────────────────
function renderGame() {
  const current = State.todayCards[State.currentIndex];

  document.getElementById('game-root').innerHTML = `
    <div class="game-wrap">

      <header class="game-header">
        <div class="header-brand">
          <span class="logo">GSSdle</span>
          <span class="header-sub">General Social Survey · Daily</span>
        </div>
        <div class="score-box">
          <span class="score-num" id="score-num">${State.score}</span>
          <span class="score-denom">/ 28</span>
        </div>
      </header>

      <div class="progress-strip">
        ${State.todayCards.map((_,i) => `
          <div class="pip ${i < State.currentIndex ? 'pip-done' : i === State.currentIndex ? 'pip-active' : ''}"></div>
        `).join('')}
      </div>

      <div class="timeline-scroll-wrap" id="timeline-scroll-wrap">
        <div class="timeline-canvas" id="timeline-canvas">
          ${renderTimeline()}
        </div>
      </div>

      <div class="incoming-zone">
        ${current ? `
          <div class="incoming-hint">↑ Drag card to its position on the scale above</div>
          <div class="incoming-card-wrap">
            <div class="scard incoming-card" id="incoming-card" draggable="true">
              <div class="scard-decade">${current.decade}</div>
              <div class="scard-question">${current.question}</div>
              ${State.attempts > 0
                ? `<div class="wrong-marks">${'<span class="x-mark">✕</span>'.repeat(Math.min(State.attempts,8))}</div>`
                : ''}
            </div>
          </div>
          <div class="incoming-label">CARD ${State.currentIndex + 1} OF ${State.todayCards.length}</div>
        ` : `<div class="incoming-label">All cards placed!</div>`}
      </div>

    </div>
  `;

  setupInteraction();

  requestAnimationFrame(() => {
    const wrap = document.getElementById('timeline-scroll-wrap');
    if (wrap) { const { scrollTarget } = layout(); wrap.scrollLeft = scrollTarget; }
  });
}

// ── RENDER TIMELINE ───────────────────────────────────────────────────────────
function renderTimeline() {
  const wrap = document.getElementById('timeline-scroll-wrap');
  const vw   = wrap ? wrap.clientWidth : window.innerWidth;

  if (State.placed.length === 0) {
    const canvasH = TRACK_Y + CARD_SIZE + STEM_H + 40;
    return `
      <div class="tl-inner" style="width:${vw}px;height:${canvasH}px" id="tl-inner">
        <div class="tl-track" style="top:${TRACK_Y}px"></div>
        <div class="tl-axis-label" style="top:${TRACK_Y+14}px;left:60px">← LESS COMMON</div>
        <div class="tl-axis-label" style="top:${TRACK_Y+14}px;right:60px;text-align:right">MORE COMMON →</div>
        <div class="drop-overlay" id="drop-overlay"
             style="width:${vw}px;height:${canvasH}px;display:none;cursor:crosshair"></div>
      </div>`;
  }

  const { sorted, positions, canvasWidth } = layout();
  const canvasH = TRACK_Y + CARD_SIZE + STEM_H + 40;

  const wrongHTML = State.wrongMarkers.map(m => {
    const x = interpolateX(m.guessedPct, sorted, positions);
    return `<div class="wrong-marker" style="left:${x}px;top:${TRACK_Y}px"></div>`;
  }).join('');

  const cardsHTML = sorted.map((entry, i) => {
    const x       = positions[i];
    const above   = i % 2 === 0;
    const cardTop = above ? TRACK_Y - CARD_SIZE - STEM_H : TRACK_Y + STEM_H;
    const stemTop = above ? TRACK_Y - STEM_H             : TRACK_Y;

    return `
      <div class="scard placed-scard" style="left:${x}px;top:${cardTop}px">
        <div class="scard-decade">${entry.card.decade}</div>
        <div class="scard-question">${entry.card.question}</div>
        <div class="scard-pct">${entry.card.pct.toFixed(1)}%</div>
        ${entry.wrongAttempts > 0
          ? `<div class="wrong-marks">${'<span class="x-mark">✕</span>'.repeat(Math.min(entry.wrongAttempts,8))}</div>`
          : ''}
      </div>
      <div class="pin-stem"  style="left:${x}px;top:${stemTop}px;height:${STEM_H}px"></div>
      <div class="track-dot" style="left:${x}px;top:${TRACK_Y}px"></div>
    `;
  }).join('');

  return `
    <div class="tl-inner" style="width:${canvasWidth}px;height:${canvasH}px" id="tl-inner">
      <div class="tl-track" style="top:${TRACK_Y}px"></div>
      <div class="tl-axis-label" style="top:${TRACK_Y+14}px;left:60px">← LESS COMMON</div>
      <div class="tl-axis-label" style="top:${TRACK_Y+14}px;right:60px;text-align:right">MORE COMMON →</div>
      ${wrongHTML}
      ${cardsHTML}
      <div class="drop-overlay" id="drop-overlay"
           style="width:${canvasWidth}px;height:${canvasH}px;display:none;cursor:crosshair"></div>
    </div>`;
}

function interpolateX(pct, sorted, positions) {
  const pcts = sorted.map(s => s.card.pct);
  if (pct <= pcts[0])               return positions[0] - SPACING * 0.5;
  if (pct >= pcts[pcts.length - 1]) return positions[positions.length - 1] + SPACING * 0.5;
  for (let i = 0; i < pcts.length - 1; i++) {
    if (pct >= pcts[i] && pct <= pcts[i + 1]) {
      const t = (pct - pcts[i]) / (pcts[i + 1] - pcts[i]);
      return positions[i] + t * (positions[i + 1] - positions[i]);
    }
  }
  return positions[0];
}

// ── INTERACTION ───────────────────────────────────────────────────────────────
function setupInteraction() {
  const incoming = document.getElementById('incoming-card');
  const overlay  = document.getElementById('drop-overlay');
  if (!incoming || !overlay) return;

  incoming.addEventListener('dragstart', e => {
    e.dataTransfer.setData('text/plain', 'card');
    setTimeout(() => incoming.classList.add('dragging'), 0);
    overlay.style.display = 'block';
  });

  incoming.addEventListener('dragend', () => {
    incoming.classList.remove('dragging');
    overlay.style.display = 'none';
    overlay.classList.remove('overlay-hover');
    removeGhost();
  });

  overlay.addEventListener('dragover', e => {
    e.preventDefault();
    overlay.classList.add('overlay-hover');
    updateGhost(e.clientX);
  });

  overlay.addEventListener('dragleave', () => {
    overlay.classList.remove('overlay-hover');
    removeGhost();
  });

  overlay.addEventListener('drop', e => {
    e.preventDefault();
    overlay.style.display = 'none';
    overlay.classList.remove('overlay-hover');
    removeGhost();
    attemptPlace(clientXtoRelativePct(e.clientX));
  });

  incoming.addEventListener('touchstart', onTouchStart, { passive: false });
  incoming.addEventListener('touchmove',  onTouchMove,  { passive: false });
  incoming.addEventListener('touchend',   onTouchEnd,   { passive: false });
}

function updateGhost(clientX) {
  const inner = document.getElementById('tl-inner');
  if (!inner) return;
  let g = document.getElementById('drop-ghost');
  if (!g) {
    g = document.createElement('div');
    g.id = 'drop-ghost';
    g.className = 'drop-ghost';
    g.style.height = (TRACK_Y + 20) + 'px';
    inner.appendChild(g);
  }
  const rect = inner.getBoundingClientRect();
  g.style.left = (clientX - rect.left) + 'px';
}

function removeGhost() {
  const g = document.getElementById('drop-ghost');
  if (g) g.remove();
}

// ── TOUCH ─────────────────────────────────────────────────────────────────────
function onTouchStart(e) {
  e.preventDefault();
  const touch = e.touches[0];
  const el    = e.currentTarget;
  const rect  = el.getBoundingClientRect();
  State.touchOffsetX = touch.clientX - rect.left;
  State.touchOffsetY = touch.clientY - rect.top;
  State.touchClone   = el.cloneNode(true);
  Object.assign(State.touchClone.style, {
    position:'fixed', zIndex:'9999', pointerEvents:'none',
    width: rect.width+'px', opacity:'0.9',
    left: rect.left+'px', top: rect.top+'px',
    transform:'scale(1.04)', transition:'none',
  });
  document.body.appendChild(State.touchClone);
  el.style.opacity = '0.3';
  const ov = document.getElementById('drop-overlay');
  if (ov) ov.style.display = 'block';
}

function onTouchMove(e) {
  e.preventDefault();
  if (!State.touchClone) return;
  const touch = e.touches[0];
  State.touchClone.style.left = (touch.clientX - State.touchOffsetX) + 'px';
  State.touchClone.style.top  = (touch.clientY - State.touchOffsetY) + 'px';
  const inner = document.getElementById('tl-inner');
  if (inner) {
    const rect = inner.getBoundingClientRect();
    const over = touch.clientY >= rect.top - 40 && touch.clientY <= rect.bottom + 60;
    if (over) updateGhost(touch.clientX);
    else removeGhost();
  }
}

function onTouchEnd(e) {
  e.preventDefault();
  const touch = e.changedTouches[0];
  if (State.touchClone) { State.touchClone.remove(); State.touchClone = null; }
  const el = document.getElementById('incoming-card');
  if (el) el.style.opacity = '1';
  const ov = document.getElementById('drop-overlay');
  if (ov) { ov.style.display = 'none'; ov.classList.remove('overlay-hover'); }
  removeGhost();
  const inner = document.getElementById('tl-inner');
  if (!inner) return;
  const rect = inner.getBoundingClientRect();
  const over = touch.clientY >= rect.top - 40 && touch.clientY <= rect.bottom + 60;
  if (over) attemptPlace(clientXtoRelativePct(touch.clientX));
}

// ── PLACEMENT LOGIC ───────────────────────────────────────────────────────────
function attemptPlace(guessedPct) {
  const card = State.todayCards[State.currentIndex];
  State.attempts++;

  const correct = State.placed.every(p =>
    (p.card.pct < card.pct  && p.card.pct <= guessedPct) ||
    (p.card.pct > card.pct  && p.card.pct >= guessedPct) ||
    (p.card.pct === card.pct)
  );

  if (correct) {
    const cardValue    = State.currentIndex;  // card 2 = 1pt ... card 8 = 7pt
    const wrongCount   = State.attempts - 1;
    const pointsEarned = Math.max(0, cardValue - wrongCount);
    State.score       += pointsEarned;

    State.wrongMarkers = State.wrongMarkers.filter(m => m.cardIndex !== State.currentIndex);
    State.placed.push({ card, pointsEarned, wrongAttempts: wrongCount });
    State.results.push({ card, correct: true, pointsEarned, cardValue });
    State.currentIndex++;
    State.attempts = 0;

    showToast(true, pointsEarned, cardValue);
    setTimeout(() => {
      if (State.currentIndex >= State.todayCards.length) endGame();
      else renderGame();
    }, 900);

  } else {
    State.wrongMarkers.push({ guessedPct, cardIndex: State.currentIndex });
    showToast(false, 0, 0);
    const el = document.getElementById('incoming-card');
    if (el) { el.classList.add('shake'); setTimeout(() => el.classList.remove('shake'), 500); }
    const canvas = document.getElementById('timeline-canvas');
    if (canvas) { canvas.innerHTML = renderTimeline(); setupInteraction(); }
  }
}

// ── TOAST ─────────────────────────────────────────────────────────────────────
function showToast(correct, pts, cardVal) {
  const ex = document.getElementById('toast');
  if (ex) ex.remove();
  const t = document.createElement('div');
  t.id = 'toast';
  t.className = `toast ${correct ? 'toast-ok' : 'toast-bad'}`;
  t.innerHTML = correct
    ? `✓ +${pts} pt${pts!==1?'s':''} <span class="toast-sub">(card worth ${cardVal})</span>`
    : `✗ Wrong position — try again`;
  document.body.appendChild(t);
  requestAnimationFrame(() => t.classList.add('toast-show'));
  setTimeout(() => { t.classList.remove('toast-show'); setTimeout(()=>t.remove(),300); }, 1600);
}

// ── END GAME ──────────────────────────────────────────────────────────────────
function endGame() {
  State.gameOver = true;
  renderEndScreen();
}

function renderEndScreen() {
  const totalMax = 28;
  const pct  = Math.round(State.score / totalMax * 100);
  const grid = State.results.map(r =>
    r.pointsEarned === r.cardValue ? '🟩' : r.pointsEarned > 0 ? '🟨' : '🟥'
  ).join('');

  document.getElementById('game-root').innerHTML = `
    <div class="end-screen">
      <div class="end-logo">GSSdle</div>
      <div class="end-date">${todayStr()}</div>
      <div class="end-score-row">
        <span class="end-score">${State.score}</span>
        <span class="end-denom">/ ${totalMax}</span>
      </div>
      <div class="end-grade">${grade(pct)}</div>
      <div class="end-grid">${grid}</div>
      <div class="end-actions">
        <button class="share-btn" onclick="doShare('${grid}',${State.score},${totalMax})">Share Result</button>
        <button class="timeline-btn" onclick="viewTimeline()">View Timeline</button>
      </div>
      <div class="end-results">
        ${State.results.map((r,i) => `
          <div class="res-row">
            <div class="res-n">${i+1}</div>
            <div class="res-info">
              <div class="res-q">${r.card.question}</div>
              <div class="res-meta">${r.card.pct.toFixed(1)}% · ${r.card.decade}</div>
            </div>
            <div class="res-pts ${r.pointsEarned===r.cardValue?'pts-g':r.pointsEarned>0?'pts-y':'pts-x'}">
              +${r.pointsEarned}
            </div>
          </div>
        `).join('')}
      </div>
      <div class="next-label">Next GSSdle: <span id="countdown"></span></div>
    </div>
  `;
  startCountdown();
}

function viewTimeline() {
  document.getElementById('game-root').innerHTML = `
    <div class="game-wrap">
      <header class="game-header">
        <div class="header-brand">
          <span class="logo">GSSdle</span>
          <span class="header-sub">Your Final Timeline</span>
        </div>
        <button class="back-btn" onclick="renderEndScreen()">← Results</button>
      </header>
      <div class="timeline-scroll-wrap" id="timeline-scroll-wrap" style="flex:1">
        <div class="timeline-canvas" id="timeline-canvas">
          ${renderTimeline()}
        </div>
      </div>
    </div>
  `;
  requestAnimationFrame(() => {
    const wrap = document.getElementById('timeline-scroll-wrap');
    if (wrap) { const { scrollTarget } = layout(); wrap.scrollLeft = scrollTarget; }
  });
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
function grade(p) {
  if(p===100) return '🏆 Perfect!'; if(p>=80) return '🌟 Excellent';
  if(p>=60)   return '👍 Good job'; if(p>=40) return '📊 Not bad';
  return '📉 Keep practicing';
}
function todayStr() {
  return new Date().toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'});
}
function doShare(grid, score, max) {
  const text = `GSSdle ${todayStr()}\n${score}/${max}\n\n${grid}\n\ngssdle.com`;
  if (navigator.share) navigator.share({ title:'GSSdle', text });
  else navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('.share-btn');
    if(btn){ btn.textContent='Copied!'; setTimeout(()=>btn.textContent='Share Result',2000); }
  });
}
function startCountdown() {
  function tick() {
    const el = document.getElementById('countdown'); if(!el) return;
    const pac = new Date(new Date().toLocaleString('en-US',{timeZone:'America/Los_Angeles'}));
    const mid = new Date(pac); mid.setDate(pac.getDate()+1); mid.setHours(0,0,0,0);
    const d   = mid - pac;
    el.textContent = `${String(Math.floor(d/3600000)).padStart(2,'0')}:${String(Math.floor(d%3600000/60000)).padStart(2,'0')}:${String(Math.floor(d%60000/1000)).padStart(2,'0')}`;
  }
  tick(); setInterval(tick, 1000);
}
function showError(msg) {
  document.getElementById('game-root').innerHTML = `<div class="error-msg">${msg}</div>`;
}

document.addEventListener('DOMContentLoaded', init);
