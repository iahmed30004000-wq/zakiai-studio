/* zaki-ui 0.2.0 — components + shell, as one classic script.
 * Hangs everything off window.zk so a page with no bundler can use it:
 *   zk.toast('حُفظ', { tone: 'success' })
 */
(function (global) {
  'use strict';
/* ── components.js ── */
/*
 * zaki-ui components — the behaviour, as plain DOM functions.
 *
 * No framework, no build step, no global state. Every function takes the
 * elements it works on and returns a way to undo itself, so a page can
 * mount a dialog inside another dialog, or tear a panel down, without the
 * library keeping a private list of what exists.
 *
 * Loadable two ways, because the studio has no bundler:
 *   <script type="module">import { toast } from './components.js'</script>
 *   <script src="./zaki-ui.all.js"></script>   →  window.zk.toast(...)
 *
 * ── WHAT IS HERE IS WHAT A KEYBOARD NEEDS ──
 *
 * CSS can paint a dialog. It cannot trap focus inside it, return focus to
 * the button that opened it, close it on Escape, or move a highlight with
 * the arrow keys. That is the whole reason this file exists, and it is
 * why every function below is about focus or keys rather than about looks.
 */

/** Everything a person can tab to, in DOM order. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * VISIBILITY IS ASKED OF THE DOM, NOT OF THE LAYOUT.
 *
 * The obvious test is `offsetParent !== null`, and it is wrong twice: it
 * is null for any `position: fixed` element — which a dialog panel often
 * is — and it is null for EVERYTHING in an environment with no layout
 * engine, which is where this package's own tests run. The first version
 * of this line used it, and the trap silently did nothing.
 *
 * A hidden ancestor is the honest question, and it is one the DOM can
 * answer anywhere.
 */
const focusableIn = (root) =>
  [...root.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest('[hidden]') && !el.disabled);

/**
 * KEEP THE TAB KEY INSIDE THIS ELEMENT.
 *
 * Without it, tabbing out of an open dialog lands on the page behind — a
 * page the person cannot see and whose controls still work. They fill in a
 * form they are not looking at.
 *
 * Returns a release function. It is not optional: a trap left installed
 * after the dialog closes makes the whole page unreachable.
 */
function trapFocus(container) {
  const onKey = (e) => {
    if (e.key !== 'Tab') return;
    const stops = focusableIn(container);
    if (stops.length === 0) {
      e.preventDefault();
      return;
    }
    const first = stops[0];
    const last = stops[stops.length - 1];
    const here = document.activeElement;
    if (!e.shiftKey && (here === last || !container.contains(here))) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && (here === first || !container.contains(here))) {
      e.preventDefault();
      last.focus();
    }
  };
  container.addEventListener('keydown', onKey);
  return () => container.removeEventListener('keydown', onKey);
}

/**
 * OPEN A DIALOG, AND REMEMBER WHERE THE PERSON CAME FROM.
 *
 * On close the focus goes back to the control that opened it — not to the
 * top of the page, which is where a browser puts it otherwise, and which
 * means scrolling back down to find your place every time.
 */
function openModal(root, { onClose, closeOnBackdrop = true } = {}) {
  const opener = document.activeElement;
  const panel = root.querySelector('.zk-modal__panel') || root;

  root.hidden = false;
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');

  // The page behind must not scroll under an open dialog, and its previous
  // value is PUT BACK rather than set to a guess: another layer (a drawer)
  // may have locked it first.
  const heldOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  const release = trapFocus(panel);

  const close = () => {
    root.hidden = true;
    document.body.style.overflow = heldOverflow;
    release();
    document.removeEventListener('keydown', onKey, true);
    root.removeEventListener('mousedown', onBackdrop);
    if (opener && typeof opener.focus === 'function') opener.focus();
    if (onClose) onClose();
  };

  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  };

  // Only a press that STARTS on the backdrop closes it: a drag that began
  // inside the panel and ended outside is a text selection, not a dismissal.
  const onBackdrop = (e) => {
    if (closeOnBackdrop && e.target === root) close();
  };

  document.addEventListener('keydown', onKey, true);
  root.addEventListener('mousedown', onBackdrop);

  (focusableIn(panel)[0] || panel).focus?.();
  return close;
}

function closeModal(close) {
  if (typeof close === 'function') close();
}

/**
 * A MESSAGE THAT ANNOUNCES ITSELF.
 *
 * `role="status"` on a live region is what makes a screen reader read a
 * toast at all; without it the message appears and is never spoken, which
 * is the same as not showing it to a person who cannot see it.
 *
 * An error does NOT dismiss itself. A success can vanish — the work is
 * done either way — but a failure the person did not happen to be looking
 * at is a failure they never learn about.
 */
function toast(message, { tone = 'info', timeout = 4000, mount } = {}) {
  const host = mount || ensureToastHost();
  const el = document.createElement('div');
  el.className = 'zk-toast';
  el.dataset.tone = tone;
  el.setAttribute('role', tone === 'error' ? 'alert' : 'status');
  el.textContent = message;

  const dismiss = () => el.remove();
  host.appendChild(el);
  if (tone !== 'error' && timeout > 0) window.setTimeout(dismiss, timeout);
  return dismiss;
}

function ensureToastHost() {
  let host = document.querySelector('.zk-toasts');
  if (!host) {
    host = document.createElement('div');
    host.className = 'zk-toasts';
    host.setAttribute('aria-live', 'polite');
    document.body.appendChild(host);
  }
  return host;
}

/**
 * TABS THE ARROW KEYS CAN REACH, AND ONE TAB STOP FOR THE SET.
 *
 * Without the roving `tabindex`, nine tabs are nine stops between the top
 * of the page and the content.
 *
 * AND «NEXT» FOLLOWS THE EYE, NOT THE DOM. The page is right-to-left, so
 * the tab visually to the LEFT is the next one. Following DOM order would
 * move the highlight the opposite way from the key that was pressed, which
 * is worse than having no arrow keys at all.
 */
function tabs(strip, { onChange } = {}) {
  const items = () => [...strip.querySelectorAll('[role="tab"]')];

  const select = (tab) => {
    if (!tab) return;
    for (const t of items()) {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      const panelId = t.getAttribute('aria-controls');
      if (panelId) {
        const panel = strip.ownerDocument.getElementById(panelId);
        if (panel) panel.hidden = !on;
      }
    }
    tab.focus();
    if (onChange) onChange(tab.dataset.tab ?? tab.id ?? '');
  };

  const move = (delta) => {
    const all = items();
    const i = all.findIndex((t) => t.getAttribute('aria-selected') === 'true');
    if (i === -1) return;
    select(all[(i + delta + all.length) % all.length]);
  };

  const rtl = () => getComputedStyle(strip).direction === 'rtl';

  const onKey = (e) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      move(rtl() ? 1 : -1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      move(rtl() ? -1 : 1);
    } else if (e.key === 'Home') {
      e.preventDefault();
      select(items()[0]);
    } else if (e.key === 'End') {
      e.preventDefault();
      select(items()[items().length - 1]);
    }
  };

  const onClick = (e) => {
    const tab = e.target.closest('[role="tab"]');
    if (tab && strip.contains(tab)) select(tab);
  };

  strip.addEventListener('keydown', onKey);
  strip.addEventListener('click', onClick);
  return () => {
    strip.removeEventListener('keydown', onKey);
    strip.removeEventListener('click', onClick);
  };
}

/**
 * A MENU THAT CLOSES THE WAY PEOPLE EXPECT.
 *
 * Escape, a click anywhere else, and losing focus all close it — and the
 * focus goes back to the trigger, so the keyboard does not land at the top
 * of the document after choosing something.
 */
function dropdown(root, { onSelect } = {}) {
  const trigger = root.querySelector('[aria-haspopup]');
  const menu = root.querySelector('.zk-dropdown__menu');
  if (!trigger || !menu) return () => {};

  const items = () => [...menu.querySelectorAll('.zk-dropdown__item')];
  let active = -1;

  const paint = () => {
    items().forEach((el, i) => {
      el.dataset.active = String(i === active);
      // Optional on purpose: not every host implements it, and a menu
      // that throws while highlighting a row is worse than one that
      // highlights without scrolling.
      if (i === active) el.scrollIntoView?.({ block: 'nearest' });
    });
  };

  const open = () => {
    menu.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    active = items().findIndex((el) => el.getAttribute('aria-selected') === 'true');
    paint();
  };

  const close = ({ refocus = true } = {}) => {
    menu.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    active = -1;
    paint();
    if (refocus) trigger.focus();
  };

  const choose = (el) => {
    if (!el) return;
    for (const other of items()) other.setAttribute('aria-selected', String(other === el));
    close();
    if (onSelect) onSelect(el.dataset.value ?? el.textContent.trim(), el);
  };

  const onKey = (e) => {
    const open_ = menu.hidden === false;
    if (e.key === 'Escape' && open_) {
      e.preventDefault();
      close();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open_) return open();
      const all = items();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length;
      paint();
    } else if ((e.key === 'Enter' || e.key === ' ') && open_ && active >= 0) {
      e.preventDefault();
      choose(items()[active]);
    }
  };

  const onTrigger = () => (menu.hidden ? open() : close());
  const onItem = (e) => {
    const el = e.target.closest('.zk-dropdown__item');
    if (el) choose(el);
  };
  const onOutside = (e) => {
    if (!menu.hidden && !root.contains(e.target)) close({ refocus: false });
  };

  trigger.setAttribute('aria-expanded', 'false');
  menu.hidden = true;
  trigger.addEventListener('click', onTrigger);
  menu.addEventListener('click', onItem);
  root.addEventListener('keydown', onKey);
  document.addEventListener('mousedown', onOutside);

  return () => {
    trigger.removeEventListener('click', onTrigger);
    menu.removeEventListener('click', onItem);
    root.removeEventListener('keydown', onKey);
    document.removeEventListener('mousedown', onOutside);
  };
}

/** Set a progress bar from a count, and say it out loud for a reader. */
function progress(el, done, total) {
  const bar = el.querySelector('.zk-progress__bar') || el;
  const pct = total > 0 ? Math.max(0, Math.min(100, (done / total) * 100)) : 0;
  bar.style.inlineSize = `${pct}%`;
  el.setAttribute('role', 'progressbar');
  el.setAttribute('aria-valuemin', '0');
  el.setAttribute('aria-valuemax', String(total));
  el.setAttribute('aria-valuenow', String(done));
  return pct;
}

const ZK_COMPONENTS = { trapFocus, openModal, closeModal, toast, tabs, dropdown, progress };


/* ── shell.js ── */
/*
 * zaki-ui shell — two custom elements, in the LIGHT DOM.
 *
 * `<zk-app-shell>` and `<zk-app-switcher>` are custom elements because the
 * brief names them and because «the shell» is a thing a page declares
 * rather than calls. They deliberately use NO shadow root: the package's
 * whole purpose is shared tokens and shared classes, and a shadow root
 * walls both out — every consumer would then have to pipe the tokens back
 * in through a second mechanism.
 *
 * So `slot="header" | "sidebar" | "content"` are plain attributes the CSS
 * grid places. The word is the brief's, the mechanism is the simpler one.
 */



/* ══════════════════════════════════════════════════════════════════════
 * <zk-app-shell>
 * ════════════════════════════════════════════════════════════════════ */

class ZkAppShell extends HTMLElement {
  connectedCallback() {
    this._release = null;
    this._onKey = (e) => {
      if (e.key === 'Escape' && this.dataset.drawer === 'open') {
        e.preventDefault();
        this.closeDrawer();
      }
    };
    this._onClick = (e) => {
      if (e.target.closest('.zk-drawer-toggle')) this.toggleDrawer();
      else if (e.target.closest('.zk-scrim')) this.closeDrawer();
      /*
       * A NAVIGATION CLOSES THE DRAWER.
       *
       * Otherwise the page changes behind a panel covering it, and the
       * person is looking at a menu wondering whether the tap worked.
       */
      else if (e.target.closest('.zk-nav-item') && this.dataset.drawer === 'open') this.closeDrawer();
    };
    this.addEventListener('click', this._onClick);
    this.ownerDocument.addEventListener('keydown', this._onKey, true);
    this._wireGroups();
  }

  disconnectedCallback() {
    this.removeEventListener('click', this._onClick);
    this.ownerDocument.removeEventListener('keydown', this._onKey, true);
    if (this._release) this._release();
  }

  /**
   * COLLAPSIBLE GROUPS — except the one you are standing in.
   *
   * Collapsing the current group hides where you are, and then the sidebar
   * stops answering the question it exists for. The head stays visible and
   * becomes inert rather than disappearing: a control that vanishes is a
   * control people hunt for.
   */
  _wireGroups() {
    for (const group of this.querySelectorAll('.zk-nav-group')) {
      const head = group.querySelector('.zk-nav-group__head');
      const items = group.querySelector('.zk-nav-group__items');
      if (!head || !items) continue;

      const current = !!group.querySelector('[aria-current="page"]');
      group.dataset.current = String(current);
      const open = current || group.getAttribute('aria-expanded') !== 'false';
      group.setAttribute('aria-expanded', String(open));
      items.hidden = !open;
      head.setAttribute('aria-expanded', String(open));
      head.setAttribute('aria-controls', items.id || (items.id = `zk-group-${Math.random().toString(36).slice(2)}`));
      if (current) head.setAttribute('aria-disabled', 'true');

      head.addEventListener('click', () => {
        if (group.dataset.current === 'true') return;
        const next = group.getAttribute('aria-expanded') !== 'true';
        group.setAttribute('aria-expanded', String(next));
        head.setAttribute('aria-expanded', String(next));
        items.hidden = !next;
      });
    }
  }

  openDrawer() {
    this.dataset.drawer = 'open';
    const panel = this.querySelector('[slot="sidebar"]');
    const scrim = this.querySelector('.zk-scrim');
    if (scrim) scrim.hidden = false;
    if (panel) {
      // Same trap as a dialog: a drawer covering the page whose Tab key
      // walks the page behind it is the same defect with a different name.
      this._release = trapFocus(panel);
      panel.querySelector('a, button')?.focus();
    }
  }

  closeDrawer() {
    this.dataset.drawer = 'closed';
    const scrim = this.querySelector('.zk-scrim');
    if (scrim) scrim.hidden = true;
    if (this._release) {
      this._release();
      this._release = null;
    }
    this.querySelector('.zk-drawer-toggle')?.focus();
  }

  toggleDrawer() {
    if (this.dataset.drawer === 'open') this.closeDrawer();
    else this.openDrawer();
  }
}

/* ══════════════════════════════════════════════════════════════════════
 * <zk-app-switcher>
 * ════════════════════════════════════════════════════════════════════ */

/**
 * HOW OFTEN TO ASK WHETHER AN APP IS THERE. Thirty seconds by default, and
 * NOT while the page is hidden: a background tab polling a laptop that is
 * asleep is a request nobody reads and a battery nobody agreed to spend.
 */
const DEFAULT_PROBE_MS = 30000;

/** How long to wait before calling it unavailable. */
const PROBE_TIMEOUT_MS = 2500;

/**
 * ASK, AND ASSUME NOTHING UNTIL SOMETHING ANSWERS.
 *
 * `no-cors` makes the response opaque — we cannot read its status — so the
 * only thing this can honestly report is «something answered» versus «it
 * did not». That is exactly the question being asked, and pretending to
 * know more (a status, a version) would be inventing it.
 */
async function probe(url, { timeout = PROBE_TIMEOUT_MS, fetchImpl } = {}) {
  const f = fetchImpl || (typeof fetch === 'function' ? fetch : null);
  if (!f) return false;
  const controller = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeout) : null;
  try {
    await f(url, { method: 'HEAD', mode: 'no-cors', cache: 'no-store', signal: controller?.signal });
    return true;
  } catch {
    return false;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

class ZkAppSwitcher extends HTMLElement {
  connectedCallback() {
    this._timer = null;
    this._apps = [];
    this._onVisibility = () => {
      if (this.ownerDocument.hidden) this._stop();
      else this._start();
    };
    this.ownerDocument.addEventListener('visibilitychange', this._onVisibility);
    if (this.getAttribute('apps')) {
      try {
        this.apps = JSON.parse(this.getAttribute('apps'));
      } catch {
        /* an attribute that is not JSON is ignored rather than thrown: the
           shell must render even when the page hands it nonsense. */
      }
    }
  }

  disconnectedCallback() {
    this._stop();
    this.ownerDocument.removeEventListener('visibilitychange', this._onVisibility);
  }

  /** [{ id, name, icon, url, active }] */
  set apps(list) {
    this._apps = Array.isArray(list) ? list : [];
    this._render();
    this._start();
  }

  get apps() {
    return this._apps;
  }

  get intervalMs() {
    return Number(this.getAttribute('interval')) || DEFAULT_PROBE_MS;
  }

  _render() {
    const doc = this.ownerDocument;
    const list = doc.createElement('div');
    list.className = 'zk-apps';
    list.setAttribute('role', 'list');

    for (const app of this._apps) {
      const row = doc.createElement(app.active ? 'span' : 'a');
      row.className = 'zk-app';
      row.setAttribute('role', 'listitem');
      row.dataset.app = app.id;
      if (app.active) {
        row.setAttribute('aria-current', 'true');
        row.dataset.state = 'here';
      } else {
        row.href = app.url;
        // UNAVAILABLE UNTIL PROVEN OTHERWISE — the studio is off more
        // often than it is on, and a link that looks live until it is
        // clicked teaches people the menu lies.
        row.dataset.state = 'checking';
      }

      if (app.icon) {
        const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'zk-icon');
        svg.setAttribute('aria-hidden', 'true');
        const use = doc.createElementNS('http://www.w3.org/2000/svg', 'use');
        use.setAttribute('href', `icons.svg#${app.icon}`);
        svg.appendChild(use);
        row.appendChild(svg);
      }

      const name = doc.createElement('span');
      name.textContent = app.name;
      row.appendChild(name);

      const state = doc.createElement('span');
      state.className = 'zk-app__state';
      state.textContent = app.active ? 'أنت هنا' : 'يفحص…';
      row.appendChild(state);

      list.appendChild(row);
    }

    this.replaceChildren(list);
  }

  async _check() {
    for (const app of this._apps) {
      if (app.active) continue;
      const row = this.querySelector(`[data-app="${app.id}"]`);
      if (!row) continue;
      const alive = await probe(app.url);
      row.dataset.state = alive ? 'available' : 'unavailable';
      const state = row.querySelector('.zk-app__state');
      if (state) state.textContent = alive ? '' : 'غير متاح';
      if (!alive) row.setAttribute('aria-disabled', 'true');
      else row.removeAttribute('aria-disabled');
    }
  }

  _start() {
    this._stop();
    if (this.ownerDocument.hidden) return;
    void this._check();
    this._timer = setInterval(() => void this._check(), this.intervalMs);
  }

  _stop() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }
}

if (typeof customElements !== 'undefined') {
  if (!customElements.get('zk-app-shell')) customElements.define('zk-app-shell', ZkAppShell);
  if (!customElements.get('zk-app-switcher')) customElements.define('zk-app-switcher', ZkAppSwitcher);
}


const ZK_SHELL = { ZkAppShell, ZkAppSwitcher, probe, DEFAULT_PROBE_MS, PROBE_TIMEOUT_MS };

  global.zk = Object.assign({}, ZK_COMPONENTS, ZK_SHELL);
})(typeof window !== 'undefined' ? window : globalThis);
