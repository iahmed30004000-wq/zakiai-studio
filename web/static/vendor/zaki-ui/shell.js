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

import { trapFocus } from './components.js';

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
export const DEFAULT_PROBE_MS = 30000;

/** How long to wait before calling it unavailable. */
export const PROBE_TIMEOUT_MS = 2500;

/**
 * ASK, AND ASSUME NOTHING UNTIL SOMETHING ANSWERS.
 *
 * `no-cors` makes the response opaque — we cannot read its status — so the
 * only thing this can honestly report is «something answered» versus «it
 * did not». That is exactly the question being asked, and pretending to
 * know more (a status, a version) would be inventing it.
 */
export async function probe(url, { timeout = PROBE_TIMEOUT_MS, fetchImpl } = {}) {
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

export { ZkAppShell, ZkAppSwitcher };
export const ZK_SHELL = { ZkAppShell, ZkAppSwitcher, probe, DEFAULT_PROBE_MS, PROBE_TIMEOUT_MS };
