"""
tools/input_bridge/router.py

Universal Input Bridge — Mobile/Desktop Parity Tool
====================================================

This tool provides three core capabilities as injectable JS + CSS that any module
can opt into by including {{ ENV['input_bridge_js'] }} in its template:

1. CONTEXT MENU BRIDGE
   Right-click (desktop) and long-press (mobile) both fire the same
   'contextmenu' event. Modules register context menus declaratively via
   data attributes. No per-module JS needed.

2. DRAG-AND-DROP BRIDGE
   Pointer Events API wrapper that makes drag-and-drop work identically
   across mouse, touch, and stylus. Modules use data-draggable / data-drop-zone
   attributes + a small set of custom events.

3. COMMAND PALETTE
   A floating keyboard shortcut / command palette accessible on all platforms.
   Desktop: Ctrl+K or Cmd+K. Mobile: three-finger tap, or a persistent
   floating trigger button (hideable). Modules register commands with
   ENV['register_command'](key, label, callback).

   This is the mobile answer to keyboard shortcuts: instead of trying to
   intercept Ctrl+S on a touch keyboard, you give users a searchable
   command palette where every action is one tap away.

Architecture:
    The tool serves a single JS file (/input-bridge/bridge.js) that is
    included once in base.html (or optionally per-module). It exposes
    window.InputBridge with the full API. Modules never import it — they
    just use the data attributes and custom events.

Usage in a module template:
    <!-- Context menu: right-click or long-press fires, data-menu names the config -->
    <div data-ctx-menu="file-item" data-ctx-file="{{ file.path }}">{{ file.name }}</div>

    <!-- Draggable element -->
    <div data-draggable data-drag-type="file" data-drag-id="{{ file.id }}">...</div>

    <!-- Drop zone -->
    <div data-drop-zone data-drop-accepts="file">...</div>

    <!-- Register a command in module init -->
    <script>
    InputBridge.registerCommand({
        id: 'save-file',
        label: 'Save current file',
        shortcut: 'ctrl+s',
        category: 'File',
        action: () => saveCurrentFile()
    });
    </script>

The router below serves the JS bundle and a registration endpoint for
server-side command registration (for HTMX-driven modules that don't have
persistent JS state).
"""

from fastapi import APIRouter, Request
from fastapi.responses import Response, HTMLResponse

router = APIRouter()

MODULE_META = {"label": "Input Bridge", "icon": "⌨", "public": False, "pwa": False, "persistence": "none"}

ENV = {}

def init_module(env: dict):
    global ENV
    ENV = env


BRIDGE_JS = r"""
/* ============================================================
   InputBridge — Universal Input Normalization Layer
   Portal Server built-in tool
   
   Exposes: window.InputBridge
   No dependencies. Vanilla JS only.
   ============================================================ */

(function () {
'use strict';

// -- Utilities --
const isTouchPrimary = () => window.matchMedia('(pointer: coarse)').matches;

function $(sel, ctx) { return (ctx || document).querySelector(sel); }
function $$(sel, ctx) { return Array.from((ctx || document).querySelectorAll(sel)); }

function emit(el, name, detail) {
    el.dispatchEvent(new CustomEvent(name, { bubbles: true, cancelable: true, detail }));
}

// -- 1. CONTEXT MENU BRIDGE --
// Menus are registered as: InputBridge.registerMenu('menu-id', [ {label, action, icon?, divider?} ])
// Elements opt in with data-ctx-menu="menu-id"
// data-ctx-* attributes are passed as context to each action

const _menus = {};
let _activeMenu = null;

function registerMenu(id, items) {
    _menus[id] = items;
}

function _showMenu(menuId, x, y, contextEl) {
    _hideMenu();
    const items = _menus[menuId];
    if (!items) return;

    // Collect context from data attributes
    const ctx = {};
    if (contextEl) {
        Object.keys(contextEl.dataset).forEach(k => { ctx[k] = contextEl.dataset[k]; });
    }

    const menu = document.createElement('div');
    menu.id = '_ib-ctx-menu';
    menu.setAttribute('role', 'menu');
    menu.style.cssText = `
        position: fixed; z-index: 9000;
        left: ${x}px; top: ${y}px;
        background: var(--glass-bg, rgba(20,24,32,0.97));
        border: 1px solid var(--border, rgba(255,255,255,0.12));
        border-radius: 0.5rem;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        padding: 0.3rem 0;
        min-width: 12rem;
        backdrop-filter: blur(12px);
        font-family: var(--font-ui, system-ui);
        font-size: 0.85rem;
    `;

    items.forEach(item => {
        if (item.divider) {
            const hr = document.createElement('div');
            hr.style.cssText = 'height:1px; background:var(--border, rgba(255,255,255,0.1)); margin:0.25rem 0;';
            menu.appendChild(hr);
            return;
        }
        const btn = document.createElement('button');
        btn.setAttribute('role', 'menuitem');
        btn.style.cssText = `
            display: flex; align-items: center; gap: 0.5rem;
            width: 100%; padding: 0.45rem 1rem;
            background: none; border: none; cursor: pointer;
            color: var(--text, #e0e8f0); text-align: left;
            transition: background 0.1s;
        `;
        btn.innerHTML = `${item.icon ? `<span style="opacity:0.7;font-size:1em">${item.icon}</span>` : ''}
                         <span>${item.label}</span>
                         ${item.shortcut ? `<span style="margin-left:auto;opacity:0.4;font-size:0.8em">${item.shortcut}</span>` : ''}`;
        btn.onmouseenter = () => btn.style.background = 'var(--hover-bg, rgba(255,255,255,0.07))';
        btn.onmouseleave = () => btn.style.background = 'none';
        btn.onclick = (e) => {
            e.stopPropagation();
            _hideMenu();
            if (item.action) item.action(ctx, contextEl);
        };
        if (item.disabled) { btn.disabled = true; btn.style.opacity = '0.4'; }
        menu.appendChild(btn);
    });

    document.body.appendChild(menu);
    _activeMenu = menu;

    // Clamp to viewport
    requestAnimationFrame(() => {
        const r = menu.getBoundingClientRect();
        if (r.right > window.innerWidth) menu.style.left = (window.innerWidth - r.width - 8) + 'px';
        if (r.bottom > window.innerHeight) menu.style.top = (y - r.height) + 'px';
    });
}

function _hideMenu() {
    if (_activeMenu) { _activeMenu.remove(); _activeMenu = null; }
}

// Right-click
document.addEventListener('contextmenu', e => {
    const el = e.target.closest('[data-ctx-menu]');
    if (!el) return;
    e.preventDefault();
    _showMenu(el.dataset.ctxMenu, e.clientX, e.clientY, el);
});

// Long-press (touch)
let _lpTimer = null;
let _lpTarget = null;
document.addEventListener('touchstart', e => {
    const el = e.target.closest('[data-ctx-menu]');
    if (!el) return;
    _lpTarget = el;
    _lpTimer = setTimeout(() => {
        const t = e.touches[0];
        // Haptic feedback if available
        if (navigator.vibrate) navigator.vibrate(40);
        _showMenu(el.dataset.ctxMenu, t.clientX, t.clientY, el);
    }, 500);
}, { passive: true });

document.addEventListener('touchmove', () => {
    clearTimeout(_lpTimer); _lpTimer = null;
}, { passive: true });

document.addEventListener('touchend', () => {
    clearTimeout(_lpTimer); _lpTimer = null;
}, { passive: true });

// Dismiss on outside click or Escape
document.addEventListener('pointerdown', e => {
    if (_activeMenu && !_activeMenu.contains(e.target)) _hideMenu();
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') _hideMenu();
});


// -- 2. DRAG-AND-DROP BRIDGE --
// Elements with data-draggable become draggable via Pointer Events (mouse + touch)
// Elements with data-drop-zone accept drops from matching data-drag-type
// Custom events emitted:
//   ib:dragstart  — on draggable element and document
//   ib:dragenter  — on drop zone when draggable enters
//   ib:dragleave  — on drop zone when draggable leaves
//   ib:drop       — on drop zone when released over it
//   ib:dragend    — on draggable when drag ends

let _drag = null; // { el, ghost, type, id, startX, startY, currentZone }

function _getDragData(el) {
    return {
        type:  el.dataset.dragType  || 'default',
        id:    el.dataset.dragId    || '',
        label: el.dataset.dragLabel || el.textContent.trim().slice(0, 40),
    };
}

function _createGhost(el, x, y) {
    const r = el.getBoundingClientRect();
    const ghost = el.cloneNode(true);
    ghost.id = '_ib-drag-ghost';
    ghost.style.cssText = `
        position: fixed; pointer-events: none; z-index: 9500;
        left: ${r.left}px; top: ${r.top}px;
        width: ${r.width}px; opacity: 0.75;
        transform: scale(1.04);
        box-shadow: 0 8px 24px rgba(0,0,0,0.35);
        transition: opacity 0.1s;
    `;
    document.body.appendChild(ghost);
    return ghost;
}

function _updateGhost(ghost, dx, dy) {
    const r = ghost.getBoundingClientRect();
    ghost.style.left = (parseFloat(ghost.style.left) + dx) + 'px';
    ghost.style.top  = (parseFloat(ghost.style.top)  + dy) + 'px';
}

function _getZoneAt(x, y, type) {
    // temporarily hide ghost so elementFromPoint works
    const ghost = $('#_ib-drag-ghost');
    if (ghost) ghost.style.display = 'none';
    const el = document.elementFromPoint(x, y);
    if (ghost) ghost.style.display = '';
    if (!el) return null;
    const zone = el.closest('[data-drop-zone]');
    if (!zone) return null;
    const accepts = zone.dataset.dropAccepts;
    if (accepts && accepts !== type && accepts !== '*') return null;
    return zone;
}

document.addEventListener('pointerdown', e => {
    const draggable = e.target.closest('[data-draggable]');
    if (!draggable || e.button === 2) return;

    // Slight delay to distinguish tap from drag
    const startX = e.clientX, startY = e.clientY;
    let started = false;

    function onMove(mv) {
        const dx = mv.clientX - startX, dy = mv.clientY - startY;
        if (!started && Math.sqrt(dx*dx + dy*dy) < 6) return;
        if (!started) {
            started = true;
            draggable.setPointerCapture(e.pointerId);
            const data = _getDragData(draggable);
            const ghost = _createGhost(draggable, startX, startY);
            _drag = { el: draggable, ghost, ...data, lastX: startX, lastY: startY, currentZone: null };
            draggable.classList.add('ib-dragging');
            emit(draggable, 'ib:dragstart', { ..._drag });
        }
        if (_drag) {
            _updateGhost(_drag.ghost, mv.clientX - _drag.lastX, mv.clientY - _drag.lastY);
            _drag.lastX = mv.clientX;
            _drag.lastY = mv.clientY;

            const zone = _getZoneAt(mv.clientX, mv.clientY, _drag.type);
            if (zone !== _drag.currentZone) {
                if (_drag.currentZone) {
                    _drag.currentZone.classList.remove('ib-drop-hover');
                    emit(_drag.currentZone, 'ib:dragleave', { ..._drag });
                }
                _drag.currentZone = zone;
                if (zone) {
                    zone.classList.add('ib-drop-hover');
                    emit(zone, 'ib:dragenter', { ..._drag });
                }
            }
        }
    }

    function onUp(up) {
        draggable.removeEventListener('pointermove', onMove);
        draggable.removeEventListener('pointerup', onUp);
        draggable.removeEventListener('pointercancel', onUp);
        if (!_drag) return;
        _drag.ghost.remove();
        draggable.classList.remove('ib-dragging');
        const zone = _getZoneAt(up.clientX, up.clientY, _drag.type);
        if (zone) {
            zone.classList.remove('ib-drop-hover');
            emit(zone, 'ib:drop', { ..._drag });
        }
        emit(draggable, 'ib:dragend', { dropped: !!zone, zone });
        _drag = null;
    }

    draggable.addEventListener('pointermove', onMove);
    draggable.addEventListener('pointerup', onUp);
    draggable.addEventListener('pointercancel', onUp);
}, { passive: true });


// -- 3. COMMAND PALETTE --
// Searchable command launcher. Desktop: Ctrl+K / Cmd+K. Mobile: trigger button.
// Modules register commands with InputBridge.registerCommand({...})

const _commands = [];
let _paletteOpen = false;

function registerCommand({ id, label, shortcut, category, action, icon, keywords }) {
    // Remove existing entry with same id
    const idx = _commands.findIndex(c => c.id === id);
    if (idx !== -1) _commands.splice(idx, 1);
    _commands.push({ id, label, shortcut: shortcut || '', category: category || 'General',
                     action, icon: icon || '', keywords: keywords || '' });
}

function _buildPalette() {
    if ($('#_ib-palette')) return;

    const overlay = document.createElement('div');
    overlay.id = '_ib-palette-overlay';
    overlay.style.cssText = `
        position: fixed; inset: 0; z-index: 9100;
        background: rgba(0,0,0,0.5); backdrop-filter: blur(4px);
        display: flex; align-items: flex-start; justify-content: center;
        padding-top: clamp(4rem, 15vh, 8rem);
    `;

    overlay.innerHTML = `
        <div id="_ib-palette" role="dialog" aria-label="Command palette" style="
            width: min(92vw, 36rem);
            background: var(--glass-bg, rgba(15,20,28,0.98));
            border: 1px solid var(--border, rgba(255,255,255,0.14));
            border-radius: 0.75rem;
            box-shadow: 0 24px 64px rgba(0,0,0,0.6);
            overflow: hidden;
            font-family: var(--font-ui, system-ui);
        ">
            <div style="display:flex;align-items:center;gap:0.5rem;padding:0.75rem 1rem;border-bottom:1px solid var(--border,rgba(255,255,255,0.1))">
                <span style="opacity:0.5;font-size:0.9em">⌘</span>
                <input id="_ib-palette-input" type="text" placeholder="Search commands…" autocomplete="off"
                    style="flex:1;background:none;border:none;outline:none;color:var(--text,#e0e8f0);font-size:0.95rem;"/>
                <kbd style="font-size:0.7rem;opacity:0.4;border:1px solid currentColor;border-radius:0.2rem;padding:0.1rem 0.35rem">Esc</kbd>
            </div>
            <div id="_ib-palette-results" role="listbox" style="max-height:min(60vh,20rem);overflow-y:auto;padding:0.3rem 0;"></div>
        </div>
    `;

    document.body.appendChild(overlay);
    _paletteOpen = true;

    const input = $('#_ib-palette-input');
    const results = $('#_ib-palette-results');
    let activeIdx = 0;

    function renderResults(query) {
        const q = query.toLowerCase();
        const filtered = q
            ? _commands.filter(c =>
                c.label.toLowerCase().includes(q) ||
                c.category.toLowerCase().includes(q) ||
                c.keywords.toLowerCase().includes(q))
            : _commands;

        results.innerHTML = '';
        if (!filtered.length) {
            results.innerHTML = `<div style="padding:1rem;text-align:center;opacity:0.4;font-size:0.85rem">No commands found</div>`;
            return;
        }

        // Group by category
        const groups = {};
        filtered.forEach(c => { (groups[c.category] = groups[c.category] || []).push(c); });

        Object.entries(groups).forEach(([cat, cmds]) => {
            const heading = document.createElement('div');
            heading.style.cssText = 'padding:0.3rem 1rem 0.1rem;font-size:0.7rem;opacity:0.4;text-transform:uppercase;letter-spacing:0.08em;color:var(--text,#e0e8f0)';
            heading.textContent = cat;
            results.appendChild(heading);

            cmds.forEach((cmd, i) => {
                const item = document.createElement('div');
                item.setAttribute('role', 'option');
                item.dataset.cmdId = cmd.id;
                item.style.cssText = `
                    display:flex;align-items:center;gap:0.6rem;
                    padding:0.5rem 1rem;cursor:pointer;
                    color:var(--text,#e0e8f0);font-size:0.9rem;
                    transition:background 0.08s;
                `;
                item.innerHTML = `
                    ${cmd.icon ? `<span style="font-size:1em;opacity:0.7;width:1.2em;text-align:center">${cmd.icon}</span>` : '<span style="width:1.2em"></span>'}
                    <span style="flex:1">${cmd.label}</span>
                    ${cmd.shortcut ? `<kbd style="font-size:0.72rem;opacity:0.4;border:1px solid currentColor;border-radius:0.2rem;padding:0.1rem 0.35rem;white-space:nowrap">${_formatShortcut(cmd.shortcut)}</kbd>` : ''}
                `;
                item.onmouseenter = () => {
                    $$('[role=option]', results).forEach(el => el.style.background = 'none');
                    item.style.background = 'var(--hover-bg, rgba(255,255,255,0.07))';
                    activeIdx = Array.from(results.querySelectorAll('[role=option]')).indexOf(item);
                };
                item.onclick = () => { _closePalette(); cmd.action(); };
                results.appendChild(item);
            });
        });
    }

    function _highlightAt(n) {
        const items = $$('[role=option]', results);
        items.forEach(el => el.style.background = 'none');
        if (items[n]) {
            items[n].style.background = 'var(--hover-bg, rgba(255,255,255,0.07))';
            items[n].scrollIntoView({ block: 'nearest' });
        }
    }

    input.addEventListener('input', () => { activeIdx = 0; renderResults(input.value); _highlightAt(0); });
    input.addEventListener('keydown', e => {
        const items = $$('[role=option]', results);
        if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); _highlightAt(activeIdx); }
        if (e.key === 'ArrowUp')   { e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); _highlightAt(activeIdx); }
        if (e.key === 'Enter' && items[activeIdx]) { _closePalette(); _commands.find(c => c.id === items[activeIdx].dataset.cmdId)?.action(); }
        if (e.key === 'Escape') _closePalette();
    });

    overlay.addEventListener('pointerdown', e => { if (e.target === overlay) _closePalette(); });

    renderResults('');
    _highlightAt(0);
    requestAnimationFrame(() => input.focus());
}

function _closePalette() {
    const overlay = $('#_ib-palette-overlay');
    if (overlay) overlay.remove();
    _paletteOpen = false;
}

function _formatShortcut(s) {
    return s.replace('ctrl', '⌃').replace('cmd', '⌘').replace('alt', '⌥')
            .replace('shift', '⇧').replace('meta', '⌘').split('+').join('');
}

// Desktop shortcut: Ctrl+K or Cmd+K
document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        _paletteOpen ? _closePalette() : _buildPalette();
    }
    if (e.key === 'Escape' && _paletteOpen) _closePalette();
    // Dispatch registered shortcuts
    if (!_paletteOpen) {
        const key = [e.ctrlKey||e.metaKey?'ctrl':'', e.shiftKey?'shift':'', e.altKey?'alt':'', e.key.toLowerCase()]
            .filter(Boolean).join('+');
        _commands.forEach(c => {
            if (c.shortcut && _normalizeShortcut(c.shortcut) === key) {
                e.preventDefault(); c.action();
            }
        });
    }
});

function _normalizeShortcut(s) {
    return s.toLowerCase().replace('cmd', 'ctrl').replace('meta', 'ctrl');
}

// Mobile trigger button — floating, unobtrusive
function _createMobileTrigger() {
    if (!isTouchPrimary()) return;
    const btn = document.createElement('button');
    btn.id = '_ib-cmd-trigger';
    btn.innerHTML = '⌘';
    btn.title = 'Command palette';
    btn.style.cssText = `
        position: fixed; z-index: 8900;
        bottom: 5rem; right: 1rem;
        width: 2.8rem; height: 2.8rem;
        border-radius: 50%;
        background: var(--glass-bg, rgba(15,20,28,0.9));
        border: 1px solid var(--border, rgba(255,255,255,0.18));
        color: var(--text, #e0e8f0);
        font-size: 1.1rem; cursor: pointer;
        box-shadow: 0 4px 16px rgba(0,0,0,0.35);
        backdrop-filter: blur(8px);
        opacity: 0.7;
        transition: opacity 0.2s, transform 0.1s;
    `;
    btn.onpointerdown  = () => btn.style.transform = 'scale(0.9)';
    btn.onpointerup    = () => { btn.style.transform = ''; _buildPalette(); };
    btn.onpointerenter = () => btn.style.opacity = '1';
    btn.onpointerleave = () => btn.style.opacity = '0.7';
    document.body.appendChild(btn);
}

// Three-finger tap for command palette on mobile
let _touchCount = 0;
document.addEventListener('touchstart', e => {
    if (e.touches.length === 3) {
        e.preventDefault();
        if (!_paletteOpen) _buildPalette();
    }
}, { passive: false });


// -- 4. DRAG-AND-DROP CSS --
const style = document.createElement('style');
style.textContent = `
    [data-draggable] { cursor: grab; user-select: none; touch-action: none; }
    [data-draggable]:active { cursor: grabbing; }
    .ib-dragging { opacity: 0.4 !important; }
    [data-drop-zone] { transition: outline 0.1s; }
    .ib-drop-hover {
        outline: 2px solid var(--accent, #0a8fc4) !important;
        outline-offset: 2px;
        background: color-mix(in srgb, var(--accent, #0a8fc4) 8%, transparent) !important;
    }
`;
document.head.appendChild(style);

// -- Public API --
window.InputBridge = {
    registerMenu,
    registerCommand,
    openPalette: _buildPalette,
    closePalette: _closePalette,
    // Utility: programmatically show a context menu at a position
    showMenu: (menuId, x, y, ctx) => _showMenu(menuId, x, y, ctx),
};

// Init mobile trigger after DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _createMobileTrigger);
} else {
    _createMobileTrigger();
}

})();
"""

@router.get("/bridge.js")
async def serve_bridge_js():
    """Serve the InputBridge JS bundle."""
    return Response(content=BRIDGE_JS, media_type="application/javascript", headers={"Cache-Control": "public, max-age=3600"})

@router.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    """Demo page showing all three InputBridge capabilities. Access at /input-bridge/demo"""
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>InputBridge Demo</title>
    <style>
        body { font-family: system-ui; padding: 2rem; background: #0d1117; color: #e0e8f0; }
        h1 { color: #0a8fc4; }
        .demo-box { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
                    border-radius: 0.5rem; padding: 1.5rem; margin: 1.5rem 0; }
        .item { display: inline-block; padding: 0.5rem 1rem; background: rgba(255,255,255,0.08);
                border-radius: 0.3rem; margin: 0.3rem; cursor: pointer; }
        .zone  { min-height: 4rem; border: 2px dashed rgba(255,255,255,0.2); border-radius: 0.5rem;
                 display: flex; align-items: center; justify-content: center; padding: 1rem;
                 color: rgba(255,255,255,0.3); }
        kbd { background: rgba(255,255,255,0.1); padding: 0.15rem 0.4rem; border-radius: 0.25rem;
              font-family: monospace; font-size: 0.85em; }
    </style>
</head>
<body>
    <h1>InputBridge Demo</h1>

    <div class="demo-box">
        <h3>1. Context Menu (Right-click or Long-press)</h3>
        <div class="item" data-ctx-menu="file-menu" data-file-name="document.txt">document.txt</div>
        <div class="item" data-ctx-menu="file-menu" data-file-name="image.png">image.png</div>
    </div>

    <div class="demo-box">
        <h3>2. Drag and Drop (Mouse or Touch)</h3>
        <div style="display:flex;gap:1rem;align-items:flex-start;flex-wrap:wrap">
            <div>
                <p style="opacity:0.6;font-size:0.85rem">Drag from here</p>
                <div class="item" data-draggable data-drag-type="file" data-drag-id="1" data-drag-label="file_one.txt">file_one.txt</div>
                <div class="item" data-draggable data-drag-type="file" data-drag-id="2" data-drag-label="file_two.txt">file_two.txt</div>
            </div>
            <div style="flex:1;min-width:12rem">
                <p style="opacity:0.6;font-size:0.85rem">Drop here</p>
                <div class="zone" data-drop-zone data-drop-accepts="file" id="drop-target">
                    Drop files here
                </div>
            </div>
        </div>
    </div>

    <div class="demo-box">
        <h3>3. Command Palette</h3>
        <p>Desktop: <kbd>Ctrl+K</kbd> / <kbd>⌘K</kbd> &nbsp; Mobile: <kbd>⌘</kbd> button or three-finger tap</p>
        <p style="opacity:0.6;font-size:0.85rem">Commands registered below via InputBridge.registerCommand()</p>
    </div>

    <script src="/input-bridge/bridge.js"></script>
    <script>
    // Register context menu
    InputBridge.registerMenu('file-menu', [
        { label: 'Open',        icon: '📄', action: ctx => alert('Open: ' + ctx.fileName) },
        { label: 'Rename',      icon: '✏️',  action: ctx => alert('Rename: ' + ctx.fileName) },
        { divider: true },
        { label: 'Download',    icon: '⬇',  action: ctx => alert('Download: ' + ctx.fileName) },
        { label: 'Delete',      icon: '🗑',  action: ctx => alert('Delete: ' + ctx.fileName) },
    ]);

    // Drop zone feedback
    document.getElementById('drop-target').addEventListener('ib:drop', e => {
        e.target.textContent = 'Dropped: ' + e.detail.label + ' (id:' + e.detail.id + ')';
        e.target.style.color = 'var(--text)';
        setTimeout(() => { e.target.textContent = 'Drop files here'; e.target.style.color = ''; }, 2000);
    });

    // Register commands
    InputBridge.registerCommand({ id: 'new-file',    label: 'New File',         icon: '📄', shortcut: 'ctrl+n',     category: 'File',   action: () => alert('New file!') });
    InputBridge.registerCommand({ id: 'open-file',   label: 'Open File…',       icon: '📂', shortcut: 'ctrl+o',     category: 'File',   action: () => alert('Open file!') });
    InputBridge.registerCommand({ id: 'save-file',   label: 'Save',             icon: '💾', shortcut: 'ctrl+s',     category: 'File',   action: () => alert('Save!') });
    InputBridge.registerCommand({ id: 'find',        label: 'Find in Page',     icon: '🔍', shortcut: 'ctrl+f',     category: 'Edit',   action: () => alert('Find!') });
    InputBridge.registerCommand({ id: 'theme-dark',  label: 'Switch to Dark',   icon: '🌙', category: 'Appearance', action: () => alert('Dark mode!') });
    InputBridge.registerCommand({ id: 'theme-light', label: 'Switch to Light',  icon: '☀', category: 'Appearance', action: () => alert('Light mode!') });
    InputBridge.registerCommand({ id: 'help',        label: 'Open Help',        icon: '❓', shortcut: 'ctrl+shift+h', category: 'Help', action: () => alert('Help!') });
    </script>
</body>
</html>
"""
    return HTMLResponse(html)
