window.__ModuleLoader__.load({
	id: "dsh-task-board",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		'use strict'
		
		// Platform modules come from the loader module table.
		const React = require('react')
		
		function apply(ctx) {
		  const slots = ctx.get('slots')
		  const timer = ctx.get('timer')
		    const workspacesSvc = ctx.get('workspaces')
		    const sessionsSvc = ctx.get('sessions')
		    const el = React.createElement
		
		    // ---------------- shared open store ----------------
		    const store = { open: false, listeners: new Set(), selectedWsId: null, workspaces: [], defaultWsId: null }
		    function emit() { for (const fn of [...store.listeners]) { try { fn() } catch (e) {} } }
		    function setOpen(v) { store.open = !!v; emit() }
		    function useOpen() {
		      const [open, set] = React.useState(store.open)
		      React.useEffect(() => {
		        const fn = () => set(store.open)
		        store.listeners.add(fn)
		        return () => store.listeners.delete(fn)
		      }, [])
		      return open
		    }
		    // ---------------- connection tracking (RPC offline banner) ----------------
		    const conn = { offline: false, failures: 0, listeners: new Set() }
		    function emitConn() { for (const fn of [...conn.listeners]) { try { fn() } catch (e) {} } }
		    function useConnOffline() {
		      const [offline, setOffline] = React.useState(conn.offline)
		      React.useEffect(() => {
		        const fn = () => setOffline(conn.offline)
		        conn.listeners.add(fn)
		        return () => conn.listeners.delete(fn)
		      }, [])
		      return offline
		    }
		    async function call(method, args) {
		      try {
		        const res = await fetch('/dsh-task-board', {
		          method: 'POST',
		          headers: { 'Content-Type': 'application/json', 'X-Kanban-Client': 'board' },
		          body: JSON.stringify({ method: 'kanban.' + method, args: args === undefined ? null : args }),
		        })
		        const r = await res.json()
		        // a successful round-trip clears the offline state
		        if (conn.offline || conn.failures > 0) {
		          conn.offline = false
		          conn.failures = 0
		          emitConn()
		        }
		        return r
		      } catch (e) {
		        conn.failures += 1
		        if (!conn.offline && conn.failures >= 2) {
		          conn.offline = true
		          emitConn()
		        }
		        throw e
		      }
		    }
		
		    const CSS = [
		      ':root {',
		      '  --kb-bg: #f4f6f9;',
		      '  --kb-surface: #ffffff;',
		      '  --kb-surface2: #fafbfc;',
		      '  --kb-border: #e4e7ec;',
		      '  --kb-border2: #d5dae1;',
		      '  --kb-text: #1d222b;',
		      '  --kb-text2: #5a6472;',
		      '  --kb-text3: #98a1ad;',
		      '  --kb-accent: #ff7236;',
		      '  --kb-accent-hover: #e9642a;',
		      '  --kb-accent-soft: #fff0e8;',
		      '  --kb-backlog: #6f7ce8;',
		      '  --kb-todo: #1687f8;',
		      '  --kb-progress: #f0bf00;',
		      '  --kb-review: #22b889;',
		      '  --kb-done: #00a558;',
		      '  --kb-blocked: #f34e52;',
		      '  --kb-canceled: #9aa4b2;',
		      '  --kb-danger: #f34e52;',
		      '  --kb-mono: "SF Mono", ui-monospace, Menlo, monospace;',
		      '  --kb-shadow: 0 1px 2px rgba(16,24,40,.06), 0 8px 24px -12px rgba(16,24,40,.18);',
		      '  --kb-mask: #2b2f36;',
		      '  --kb-board-border: #3a3f47;',
		      '  --kb-overlay-shadow: 0 24px 80px -20px rgba(0,0,0,.55);',
		      '  --kb-track: #d9dee6;',
		      '  --kb-thumb: #ffffff;',
		      '  --kb-track-surface: #eef1f5;',
		      '  --kb-track-surface2: #e8ebf0;',
		      '  --kb-warn-bg: #fff8e6;',
		      '  --kb-warn-border: #f3e0a8;',
		      '  --kb-warn-text: #8a6d1a;',
		      '  --kb-danger-soft: #fdecec;',
		      '  --kb-danger-border: #f0c4c5;',
		      '  --kb-orange-soft: #fdf0e8;',
		      '  --kb-orange-text: #d96a1f;',
		      '  --kb-yellow-soft: #fdf3d7;',
		      '  --kb-yellow-text: #a97e0a;',
		      '  --kb-blue-soft: #e8f2fd;',
		      '  --kb-blue-text: #2d7cc7;',
		      '  --kb-green-soft: #e2f5ec;',
		      '  --kb-on-accent: #ffffff;',
		      '  --kb-on-done: #ffffff;',
		      '}',
		      // 跟随 DSH 主题：中性色全部走 --dsw-alias-* token（浅/深由 ui-theme 在 body 上切换）
		      'body {',
		      '  --kb-bg: var(--dsw-alias-bg-base, #f4f6f9);',
		      '  --kb-surface: var(--dsw-alias-bg-layer-1, #ffffff);',
		      '  --kb-surface2: var(--dsw-alias-bg-layer-2, #fafbfc);',
		      '  --kb-border: var(--dsw-alias-border-l1, #e4e7ec);',
		      '  --kb-border2: var(--dsw-alias-border-l2, #d5dae1);',
		      '  --kb-text: var(--dsw-alias-label-primary, #1d222b);',
		      '  --kb-text2: var(--dsw-alias-label-secondary, #5a6472);',
		      '  --kb-text3: var(--dsw-alias-label-tertiary, #98a1ad);',
		      '  --kb-mask: var(--dsw-alias-bg-mask-1, #2b2f36);',
		      '  --kb-board-border: var(--dsw-alias-border-l3, #3a3f47);',
		      '  --kb-track: var(--dsw-alias-border-l2, #d9dee6);',
		      '  --kb-thumb: var(--dsw-alias-bg-layer-1, #ffffff);',
		      '  --kb-track-surface: #eef1f5;',
		      '  --kb-track-surface2: #e8ebf0;',
		      '}',
		      // 深色模式覆盖：状态色与强调色同步提亮，避免深底上的低对比
		      'body[data-ds-dark-theme] {',
		      '  --kb-accent: #ff8a52;',
		      '  --kb-accent-hover: #ffa273;',
		      '  --kb-accent-soft: rgba(255,138,82,.16);',
		      '  --kb-backlog: #8b96f0;',
		      '  --kb-todo: #4da3ff;',
		      '  --kb-progress: #f0c93a;',
		      '  --kb-review: #35c79b;',
		      '  --kb-done: #3bd47f;',
		      '  --kb-blocked: #ff7a7d;',
		      '  --kb-canceled: #9aa4b2;',
		      '  --kb-danger: #ff7a7d;',
		      '  --kb-mask: var(--dsw-alias-bg-mask-1, #00000080);',
		      '  --kb-overlay-shadow: 0 24px 80px -20px rgba(0,0,0,.7);',
		      '  --kb-track: var(--dsw-static-neutral-bluish-700, #61666b);',
		      '  --kb-thumb: var(--dsw-static-neutral-bluish-300, #cfd3d6);',
		      '  --kb-track-surface: rgba(255,255,255,.08);',
		      '  --kb-track-surface2: rgba(255,255,255,.12);',
		      '  --kb-shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.5);',
		      '  --kb-warn-bg: rgba(247,173,49,.16);',
		      '  --kb-warn-border: rgba(247,173,49,.34);',
		      '  --kb-warn-text: #f7c56a;',
		      '  --kb-danger-soft: rgba(255,122,125,.16);',
		      '  --kb-danger-border: rgba(255,122,125,.34);',
		      '  --kb-orange-soft: rgba(255,138,82,.16);',
		      '  --kb-orange-text: #ff9a63;',
		      '  --kb-yellow-soft: rgba(240,191,0,.16);',
		      '  --kb-yellow-text: #f0cd5a;',
		      '  --kb-blue-soft: rgba(77,163,255,.16);',
		      '  --kb-blue-text: #7ab8ff;',
		      '  --kb-green-soft: rgba(59,212,127,.16);',
		      '  --kb-on-accent: #1d222b;',
		      '  --kb-on-done: #102015;',
		      '}',
		      '.kb-toggle { display: inline-flex; align-items: center; justify-content: center; min-width: 96px; height: 32px; padding: 6px 12px; gap: 4px; border: 1px solid var(--dsw-alias-border-l2, #d5dae1); border-radius: 18px; color: var(--dsw-alias-label-primary, #1d222b); background: transparent; font-family: var(--dsw-font-family, inherit); font-size: 13px; font-weight: 400; line-height: 20px; cursor: pointer; white-space: nowrap; }',
		      '.kb-toggle:hover:not(:disabled) { background: var(--dsw-alias-interactive-bg-hover, #eef1f5); }',
		      '.kb-overlay { position: fixed; top: var(--kb-top, 0px); right: 0; bottom: 0; left: 0; z-index: 1000; background: var(--kb-mask); display: flex; align-items: center; justify-content: center; padding: 20px; }',
		      '.kb-board { position: relative; width: 100%; max-width: 1600px; height: calc(100vh - var(--kb-top, 0px) - 40px); min-height: 600px; background: var(--kb-bg); border: 1px solid var(--kb-board-border); border-radius: 18px; box-shadow: var(--kb-overlay-shadow); display: flex; flex-direction: column; overflow: hidden; }',
		      '.kb-topbar { flex: none; display: flex; align-items: center; gap: 10px; padding: 11px 16px; border-bottom: 1px solid var(--kb-border); background: var(--kb-surface); }',
		      '.kb-brand { display: flex; align-items: center; gap: 9px; }',
		      '.kb-brand-mark { width: 30px; height: 30px; border-radius: 9px; background: var(--kb-accent); color: var(--kb-on-accent); display: flex; align-items: center; justify-content: center; font-size: 15px; }',
		      '.kb-brand-name { font-size: 14px; font-weight: 800; color: var(--kb-text); line-height: 1.2; }',
		      '.kb-brand-sub { font-size: 10px; color: var(--kb-text3); }',
		      '.kb-chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; border: 1px solid var(--kb-border2); border-radius: 999px; background: var(--kb-surface2); font-size: 12px; color: var(--kb-text2); cursor: pointer; font: inherit; max-width: 250px; }',
		      '.kb-chip select { border: none; outline: none; background: transparent; font: inherit; color: var(--kb-text2); cursor: pointer; max-width: 220px; }',
		      '.kb-spacer { flex: 1; }',
		      '.kb-switch { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; color: var(--kb-text2); cursor: pointer; user-select: none; }',
		      '.kb-switch input { display: none; }',
		      '.kb-switch .track { width: 34px; height: 19px; border-radius: 999px; background: var(--kb-track); position: relative; transition: background .15s; flex: none; }',
		      '.kb-switch .track::after { content: ""; position: absolute; top: 2px; left: 2px; width: 15px; height: 15px; border-radius: 50%; background: var(--kb-thumb); box-shadow: 0 1px 3px rgba(0,0,0,.25); transition: left .15s; }',
		      '.kb-switch input:checked + .track { background: var(--kb-done); }',
		      '.kb-switch input:checked + .track::after { left: 17px; }',
		      '.kb-search { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border: 1px solid var(--kb-border2); border-radius: 9px; background: var(--kb-surface2); width: 180px; }',
		      '.kb-search input { border: none; outline: none; background: transparent; font: inherit; font-size: 12px; color: var(--kb-text); width: 100%; }',
		      '.kb-search .ico { color: var(--kb-text3); font-size: 12px; }',
		      '.kb-btn { display: inline-flex; align-items: center; gap: 7px; padding: 8px 13px; border-radius: 9px; border: 1px solid transparent; font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; transition: background .12s, transform .06s; }',
		      '.kb-btn:active { transform: translateY(1px); }',
		      '.kb-btn-primary { background: var(--kb-accent); color: var(--kb-on-accent); box-shadow: 0 4px 12px -3px rgba(255,114,54,.55); }',
		      '.kb-btn-primary:hover { background: var(--kb-accent-hover); }',
		      '.kb-btn-primary:disabled { opacity: .5; cursor: not-allowed; box-shadow: none; }',
		      '.kb-btn-ghost { background: var(--kb-surface); color: var(--kb-text2); border-color: var(--kb-border2); }',
		      '.kb-btn-ghost:hover { background: var(--kb-surface2); }',
		      '.kb-btn-close:hover { background: var(--kb-danger-soft); color: var(--kb-danger); border-color: var(--kb-danger-border); }',
		      '.kb-body { flex: 1; min-height: 0; display: flex; }',
		      '.kb-wscol { flex: none; width: 190px; border-right: 1px solid var(--kb-border); background: var(--kb-surface); display: flex; flex-direction: column; min-height: 0; }',
		      '.kb-wscol-head { padding: 10px 12px 8px; font-size: 11px; font-weight: 800; color: var(--kb-text3); text-transform: uppercase; letter-spacing: .06em; display: flex; align-items: center; justify-content: space-between; }',
		      '.kb-ws-list { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 8px 8px; display: flex; flex-direction: column; gap: 3px; }',
		      '.kb-ws-item { display: flex; flex-direction: column; gap: 1px; padding: 7px 10px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }',
		      '.kb-ws-item:hover { background: var(--kb-surface2); }',
		      '.kb-ws-item.active { background: var(--kb-accent-soft); border-color: rgba(255,114,54,.35); }',
		      '.kb-ws-item .t { font-size: 12.5px; font-weight: 700; color: var(--kb-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
		      '.kb-ws-item .p { font-size: 10px; color: var(--kb-text3); font-family: var(--kb-mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
		      '.kb-ws-item.active .t { color: var(--kb-accent-hover); }',
		      '.kb-ws-actions { display: flex; gap: 6px; padding: 8px; border-top: 1px solid var(--kb-border); }',
		      '.kb-ws-btn { flex: 1; font: inherit; font-size: 11.5px; font-weight: 600; padding: 5px 8px; border-radius: 7px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); cursor: pointer; }',
		      '.kb-ws-btn:hover { border-color: var(--kb-text3); }',
		      '.kb-ws-btn.danger:hover { color: var(--kb-danger); border-color: var(--kb-danger-border); background: var(--kb-danger-soft); }',
		      '.kb-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }',
		      '.kb-banner { flex: none; margin: 10px 16px 0; padding: 10px 14px; border-radius: 10px; background: var(--kb-warn-bg); border: 1px solid var(--kb-warn-border); color: var(--kb-warn-text); font-size: 12.5px; display: flex; align-items: center; gap: 8px; }',
		      '.kb-banner-conn { background: var(--kb-danger-soft); border-color: var(--kb-danger-border); color: var(--kb-danger); animation: kb-pulse 1.6s infinite; }',
		      '.kb-retrybtn { border: none; cursor: pointer; }',
		      '.kb-retrybtn:hover { background: var(--kb-blocked); color: var(--kb-on-accent); }',
		      '.kb-toolbar { flex: none; display: flex; align-items: center; gap: 8px; padding: 9px 16px 0; flex-wrap: wrap; }',
		      '.kb-viewtab { font: inherit; font-size: 12px; font-weight: 600; padding: 5px 11px; border-radius: 8px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); cursor: pointer; }',
		      '.kb-viewtab.active { background: var(--kb-accent-soft); border-color: var(--kb-accent); color: var(--kb-accent-hover); }',
		      '.kb-viewtab:disabled { opacity: .55; cursor: not-allowed; }',
		      '.kb-filterrow { flex: none; display: flex; gap: 8px; align-items: center; padding: 8px 16px 0; flex-wrap: wrap; font-size: 12px; color: var(--kb-text2); }',
		      '.kb-filterrow select { font: inherit; font-size: 12px; padding: 4px 8px; border-radius: 7px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); }',
		      '.kb-cols { flex: 1; min-height: 0; display: flex; gap: 12px; padding: 12px 16px; overflow-x: auto; overflow-y: hidden; }',
		      '.kb-col { flex: 1 1 0; min-width: 220px; display: flex; flex-direction: column; min-height: 0; background: var(--kb-surface); border: 1px solid var(--kb-border); border-radius: 10px; overflow: hidden; }',
		      '.kb-col-drop { outline: 2px dashed var(--kb-accent); outline-offset: -2px; }',
		      '.kb-col-head { flex: none; display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--kb-border); background: var(--kb-surface2); }',
		      '.kb-col-head .dot { width: 9px; height: 9px; border-radius: 50%; }',
		      '.kb-col-head h3 { margin: 0; font-size: 13px; font-weight: 700; }',
		      '.kb-count { font-family: var(--kb-mono); font-size: 11px; color: var(--kb-text3); background: var(--kb-track-surface); border-radius: 999px; padding: 1px 8px; }',
		      '.kb-addcol { margin-left: auto; width: 24px; height: 24px; border-radius: 7px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); cursor: pointer; font-size: 14px; line-height: 1; }',
		      '.kb-addcol:hover { background: var(--kb-accent-soft); border-color: var(--kb-accent); color: var(--kb-accent); }',
		      '.kb-col-body { flex: 1; min-height: 0; overflow-y: auto; padding: 9px; display: flex; flex-direction: column; gap: 8px; }',
		      '.kb-card { position: relative; background: var(--kb-surface); border: 1px solid var(--kb-border); border-radius: 9px; padding: 9px 11px 9px 13px; cursor: pointer; transition: box-shadow .12s, border-color .12s, transform .12s; }',
		      '.kb-card::before { content: ""; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; border-radius: 3px; background: var(--kb-card-c, var(--kb-text3)); }',
		      '.kb-card:hover { box-shadow: var(--kb-shadow); border-color: var(--kb-border2); transform: translateY(-1px); }',
		      '.kb-card.dragging { opacity: .5; }',
		      '.kb-card-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }',
		      '.kb-card-id { font-family: var(--kb-mono); font-size: 10px; color: var(--kb-text3); flex: none; }',
		      '.kb-unread { width: 7px; height: 7px; border-radius: 50%; background: var(--kb-accent); flex: none; }',
		      '.kb-donebtn { margin-left: auto; font: inherit; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 6px; border: none; background: var(--kb-done); color: var(--kb-on-done); cursor: pointer; }',
		      '.kb-card-title { font-size: 12.5px; font-weight: 600; line-height: 1.35; }',
		      '.kb-card-meta { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }',
		      '.kb-chip2 { font-size: 10px; font-weight: 600; padding: 1.5px 6px; border-radius: 5px; display: inline-flex; align-items: center; gap: 3px; }',
		      '.kb-pri-none { background: var(--kb-track-surface); color: var(--kb-text3); }',
		      '.kb-pri-urgent { background: var(--kb-danger-soft); color: var(--kb-blocked); }',
		      '.kb-pri-high { background: var(--kb-orange-soft); color: var(--kb-orange-text); }',
		      '.kb-pri-medium { background: var(--kb-yellow-soft); color: var(--kb-yellow-text); }',
		      '.kb-pri-low { background: var(--kb-blue-soft); color: var(--kb-blue-text); }',
		      '.kb-lbl { background: var(--kb-track-surface); color: var(--kb-text2); }',
		      '.kb-lbl-s { background: var(--kb-yellow-soft); color: var(--kb-yellow-text); animation: kb-pulse 2.4s infinite; }',
		      '.kb-lbl-ok { background: var(--kb-green-soft); color: var(--kb-done); }',
		      '.kb-lbl-fail { background: var(--kb-danger-soft); color: var(--kb-blocked); }',
		      '@keyframes kb-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }',
		      '.kb-progress { display: flex; gap: 2px; margin-top: 6px; height: 4px; }',
		      '.kb-progress .seg { flex: 1; border-radius: 2px; background: var(--kb-track-surface2); }',
		      '.kb-progress .seg.on { background: var(--kb-accent); }',
		      '.kb-progress .seg.cur { background: var(--kb-accent); animation: kb-pulse 1.2s infinite; }',
		      '.kb-subprogress { margin-top: 6px; }',
		      '.kb-subprogress .bar { height: 4px; border-radius: 2px; background: var(--kb-track-surface2); overflow: hidden; }',
		      '.kb-subprogress .fill { height: 100%; background: var(--kb-done); border-radius: 2px; }',
		      '.kb-empty { border: 1.5px dashed var(--kb-border2); border-radius: 9px; padding: 18px 10px; text-align: center; color: var(--kb-text3); font-size: 11.5px; line-height: 1.6; }',
		      '.kb-empty b { color: var(--kb-text2); font-weight: 600; }',
		      '.kb-other { flex: none; width: 250px; border-left: 1px solid var(--kb-border); background: var(--kb-surface); display: flex; flex-direction: column; min-height: 0; }',
		      '.kb-other-tabs { display: flex; gap: 4px; padding: 8px 8px 0; }',
		      '.kb-other-tab { flex: 1; font: inherit; font-size: 11.5px; font-weight: 700; padding: 6px 4px; border-radius: 7px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); cursor: pointer; }',
		      '.kb-other-tab.active { background: var(--kb-track-surface); border-color: var(--kb-border2); color: var(--kb-text); }',
		      '.kb-other-body { flex: 1; min-height: 0; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 6px; }',
		      '.kb-other-item { border: 1px solid var(--kb-border); border-radius: 8px; padding: 7px 9px; font-size: 12px; background: var(--kb-surface); }',
		      '.kb-other-item .row { display: flex; align-items: center; gap: 6px; }',
		      '.kb-other-item .row .t { flex: 1; font-weight: 600; color: var(--kb-text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }',
		      '.kb-other-item .act { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }',
		      '.kb-mini { font: inherit; font-size: 10.5px; font-weight: 600; padding: 2.5px 8px; border-radius: 6px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); cursor: pointer; }',
		      '.kb-mini:hover { border-color: var(--kb-text3); }',
		      '.kb-mini.ok { background: var(--kb-done); border-color: var(--kb-done); color: var(--kb-on-done); }',
		      '.kb-mini.danger { color: var(--kb-danger); border-color: var(--kb-danger-border); }',
		      '.kb-mini.danger:hover { background: var(--kb-danger-soft); }',
		      '.kb-mini.primary { background: var(--kb-accent); border-color: var(--kb-accent); color: var(--kb-on-accent); }',
		      '.kb-statusbar { flex: none; display: flex; align-items: center; gap: 14px; padding: 8px 16px; border-top: 1px solid var(--kb-border); background: var(--kb-surface); font-size: 11px; color: var(--kb-text3); }',
		      '.kb-statusbar .path { font-family: var(--kb-mono); max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }',
		      '.kb-statusbar .sum { display: flex; gap: 12px; margin-left: auto; }',
		      '.kb-statusbar .sum b { color: var(--kb-text2); }',
		      '.kb-addform { flex: none; display: flex; gap: 8px; padding: 10px 16px 0; flex-wrap: wrap; align-items: flex-start; }',
		      '.kb-input { background: var(--kb-surface); color: var(--kb-text); border: 1px solid var(--kb-border2); border-radius: 8px; padding: 6px 10px; font: inherit; font-size: 12.5px; }',
		      '.kb-input-wide { min-width: 200px; flex: 1 1 200px; }',
		      '.kb-req-input { width: 100%; min-height: 42px; resize: vertical; }',
		      '.kb-msg { padding: 0 16px; font-size: 12px; color: var(--kb-text3); min-height: 16px; }',
		      '.kb-detail { position: absolute; top: 0; right: 0; bottom: 0; width: 430px; background: var(--kb-surface); border-left: 1px solid var(--kb-border); box-shadow: -12px 0 32px -18px rgba(0,0,0,.3); display: flex; flex-direction: column; z-index: 5; }',
		      '.kb-detail-head { display: flex; align-items: center; gap: 8px; padding: 11px 14px; border-bottom: 1px solid var(--kb-border); }',
		      '.kb-detail-body { flex: 1; min-height: 0; overflow-y: auto; padding: 13px 14px; display: flex; flex-direction: column; gap: 12px; }',
		      '.kb-detail h4 { margin: 0; font-size: 11px; font-weight: 800; color: var(--kb-text3); text-transform: uppercase; letter-spacing: .05em; }',
		      '.kb-field { display: flex; flex-direction: column; gap: 4px; }',
		      '.kb-field label { font-size: 11px; color: var(--kb-text3); font-weight: 600; }',
		      '.kb-field input, .kb-field textarea, .kb-field select { font: inherit; font-size: 12.5px; padding: 6px 9px; border-radius: 8px; border: 1px solid var(--kb-border2); background: var(--kb-surface2); color: var(--kb-text); }',
		      '.kb-field textarea { resize: vertical; min-height: 64px; line-height: 1.5; }',
		      '.kb-comment { border: 1px solid var(--kb-border); border-radius: 8px; padding: 7px 9px; font-size: 12px; line-height: 1.5; background: var(--kb-surface2); }',
		      '.kb-comment .who { font-weight: 700; color: var(--kb-text); }',
		      '.kb-comment .when { color: var(--kb-text3); font-size: 10px; margin-left: 6px; }',
		      '.kb-activity { display: flex; flex-direction: column; gap: 4px; }',
		      '.kb-act { font-size: 11.5px; color: var(--kb-text2); line-height: 1.45; }',
		      '.kb-act .at { color: var(--kb-text3); font-size: 10px; margin-left: 5px; }',
		      '.kb-tagrow { display: flex; flex-wrap: wrap; gap: 5px; }',
		      '.kb-tagpick { font: inherit; font-size: 11px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); cursor: pointer; }',
		      '.kb-tagpick.on { background: var(--kb-accent-soft); border-color: var(--kb-accent); color: var(--kb-accent-hover); font-weight: 700; }',
		      '.kb-tagdel { font: inherit; font-size: 9px; line-height: 1; padding: 2px 4px; border-radius: 4px; border: none; background: transparent; color: var(--kb-text3); cursor: pointer; }',
		      '.kb-tagdel:hover { color: var(--kb-danger); }',
		      '.kb-chip-x { font: inherit; font-size: 9px; line-height: 1; padding: 1px 3px; border-radius: 4px; border: none; background: transparent; color: var(--kb-text3); cursor: pointer; }',
		      '.kb-chip-x:hover { color: var(--kb-danger); }',
		      '.kb-tagwrap { display: inline-flex; align-items: center; gap: 2px; background: var(--kb-track-surface); border-radius: 999px; padding: 1px 3px 1px 0; }',
		      '.kb-tagwrap .kb-tagpick { border: none; background: transparent; padding: 2px 6px; }',
		      '.kb-ctxmenu { position: fixed; z-index: 1300; min-width: 190px; background: var(--kb-surface); border: 1px solid var(--kb-border2); border-radius: 10px; box-shadow: 0 10px 34px -10px rgba(0,0,0,.35); padding: 5px; font-size: 12.5px; }',
		      '.kb-ctxmenu .item { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 7px; cursor: pointer; color: var(--kb-text); }',
		      '.kb-ctxmenu .item:hover { background: var(--kb-accent-soft); }',
		      '.kb-ctxmenu .item.danger { color: var(--kb-danger); }',
		      '.kb-ctxmenu .item.danger:hover { background: var(--kb-danger-soft); }',
		      '.kb-ctxmenu .item .k { margin-left: auto; font-size: 10px; color: var(--kb-text3); font-family: var(--kb-mono); }',
		      '.kb-ctxmenu .sep { height: 1px; background: var(--kb-border); margin: 4px 6px; }',
		      '.kb-ctxsub { position: relative; }',
		      '.kb-ctxsub .fly { position: absolute; left: calc(100% - 4px); top: -6px; background: var(--kb-surface); border: 1px solid var(--kb-border2); border-radius: 10px; box-shadow: 0 10px 34px -10px rgba(0,0,0,.35); padding: 5px; min-width: 150px; z-index: 1301; }',
		      '.kb-modal { position: absolute; inset: 0; z-index: 1200; background: var(--kb-mask); display: flex; align-items: center; justify-content: center; }',
		      '.kb-modal-box { width: 380px; background: var(--kb-surface); border: 1px solid var(--kb-border); border-radius: 14px; box-shadow: 0 24px 70px -18px rgba(0,0,0,.5); padding: 20px; }',
		      '.kb-modal-box h3 { margin: 0 0 8px; font-size: 15px; }',
		      '.kb-modal-box p { margin: 0 0 16px; font-size: 12.5px; color: var(--kb-text2); line-height: 1.55; }',
		      '.kb-modal-actions { display: flex; justify-content: flex-end; gap: 8px; }',
		      '.kb-overlay ::-webkit-scrollbar { width: 8px; height: 8px; }',
		      '.kb-overlay ::-webkit-scrollbar-thumb { background: var(--kb-border2); border-radius: 4px; }',
		      '.kb-startpanel { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--kb-border); border-radius: 10px; background: var(--kb-surface); }',
		      '.kb-modal-wide { width: 520px; max-width: 92vw; }',
		      '.kb-crumbs { display: flex; flex-wrap: wrap; gap: 4px; margin: 10px 0 8px; font-size: 12px; }',
		      '.kb-crumb { padding: 3px 9px; border-radius: 999px; background: var(--kb-track-surface); color: var(--kb-text2); cursor: pointer; font-weight: 600; }',
		      '.kb-crumb:hover { background: var(--kb-accent-soft); color: var(--kb-accent-hover); }',
		      '.kb-crumb.cur { background: var(--kb-accent-soft); color: var(--kb-accent-hover); }',
		      '.kb-crumb-sep { color: var(--kb-text3); }',
		      '.kb-dir-list { flex: none; max-height: 260px; overflow-y: auto; border: 1px solid var(--kb-border); border-radius: 10px; padding: 6px; display: flex; flex-direction: column; gap: 2px; background: var(--kb-surface2); }',
		      '.kb-dir-row { display: flex; align-items: center; gap: 8px; padding: 6px 9px; border-radius: 7px; cursor: pointer; font-size: 12.5px; color: var(--kb-text); }',
		      '.kb-dir-row:hover { background: var(--kb-accent-soft); color: var(--kb-accent-hover); }',
		      '.kb-dir-ico { flex: none; }',
		      '.kb-dir-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }',
		      '.kb-dir-err { margin-top: 8px; font-size: 12px; color: var(--kb-danger); line-height: 1.5; }',
		      '.kb-modal-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }',
		      '.kb-modal-head h3 { margin: 0; font-size: 15px; }',
		      '.kb-edit-box { width: 600px; max-width: 94vw; }',
		      '.kb-edit-body { max-height: 62vh; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-right: 4px; }',
		      '.kb-auto-wrap { position: relative; }',
		      '.kb-auto-btn.on { background: var(--kb-accent-soft); border-color: var(--kb-accent); color: var(--kb-accent-hover); }',
		      '.kb-auto-pop { position: absolute; top: calc(100% + 8px); right: 0; z-index: 1250; width: 330px; background: var(--kb-surface); border: 1px solid var(--kb-border2); border-radius: 12px; box-shadow: 0 16px 48px -12px rgba(0,0,0,.35); padding: 14px; display: flex; flex-direction: column; gap: 10px; }',
		      '.kb-auto-title { font-size: 12.5px; font-weight: 800; color: var(--kb-text); }',
		      '.kb-auto-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12px; color: var(--kb-text2); }',
		      '.kb-auto-row select { font: inherit; font-size: 12px; padding: 4px 8px; border-radius: 7px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); max-width: 200px; }',
		      '.kb-auto-hint { font-size: 10.5px; color: var(--kb-text3); line-height: 1.55; }',
		      '.kb-dash { flex: 1; min-height: 0; overflow-y: auto; padding: 14px 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 12px; align-content: start; }',
		      '.kb-dash-card { background: var(--kb-surface); border: 1px solid var(--kb-border); border-radius: 10px; padding: 12px 14px; min-width: 0; display: flex; flex-direction: column; gap: 8px; }',
		      '.kb-dash-card-title { font-size: 11px; font-weight: 800; color: var(--kb-text3); text-transform: uppercase; letter-spacing: .05em; }',
		      '.kb-dash-hero { grid-column: 1 / -1; flex-direction: row; align-items: center; gap: 26px; }',
		      '.kb-dash-hero-left { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }',
		      '.kb-dash-hero-right { flex: none; min-width: 220px; display: flex; flex-direction: column; gap: 4px; border-left: 1px solid var(--kb-border); padding-left: 22px; }',
		      '.kb-dash-hero-num { font-size: 34px; font-weight: 800; color: var(--kb-accent); line-height: 1; }',
		      '.kb-dash-hero-sub { font-size: 12px; color: var(--kb-text2); }',
		      '.kb-dash-hero-sub2 { font-size: 11.5px; color: var(--kb-text3); }',
		      '.kb-dash-hero-bar { margin-top: 2px; }',
		      '.kb-dash-hero-stat { font-size: 12px; color: var(--kb-text2); }',
		      '.kb-dash-hero-stat b { color: var(--kb-accent); font-weight: 800; }',
		      '.kb-dash-refresh { align-self: flex-start; margin-top: 4px; }',
		      '.kb-dash-bar { height: 6px; border-radius: 3px; background: var(--kb-track-surface); overflow: hidden; }',
		      '.kb-dash-bar-fill { height: 100%; border-radius: 3px; background: var(--kb-accent); transition: width .25s; }',
		      '.kb-dash-bar-row { display: flex; align-items: center; gap: 8px; font-size: 11.5px; }',
		      '.kb-dash-bar-label { flex: none; width: 62px; color: var(--kb-text2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }',
		      '.kb-dash-bar-track { flex: 1; height: 8px; border-radius: 4px; background: var(--kb-track-surface); overflow: hidden; }',
		      '.kb-dash-bar-num { flex: none; width: 26px; text-align: right; font-family: var(--kb-mono); color: var(--kb-text2); }',
		      '.kb-dash-sec-title { font-size: 11.5px; font-weight: 700; color: var(--kb-text2); display: flex; align-items: center; gap: 6px; margin-top: 2px; }',
		      '.kb-dash-sec-count { font-family: var(--kb-mono); font-size: 10px; color: var(--kb-text3); background: var(--kb-track-surface); border-radius: 999px; padding: 1px 7px; }',
		      '.kb-dash-list { display: flex; flex-direction: column; gap: 5px; }',
		      '.kb-dash-item { display: flex; align-items: center; gap: 7px; padding: 6px 9px; border: 1px solid var(--kb-border); border-radius: 8px; background: var(--kb-surface2); font: inherit; font-size: 12px; color: var(--kb-text); cursor: pointer; text-align: left; width: 100%; min-width: 0; }',
		      '.kb-dash-item:hover { border-color: var(--kb-accent); background: var(--kb-accent-soft); }',
		      '.kb-dash-item-id { flex: none; font-family: var(--kb-mono); font-size: 10px; color: var(--kb-text3); }',
		      '.kb-dash-item-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }',
		      '.kb-dash-item-tag { flex: none; font-size: 10.5px; font-weight: 600; padding: 1.5px 7px; border-radius: 999px; background: var(--kb-track-surface); color: var(--kb-text3); }',
		      '.kb-dash-tag-run { background: var(--kb-yellow-soft); color: var(--kb-yellow-text); animation: kb-pulse 2.4s infinite; }',
		      '.kb-dash-tag-block { background: var(--kb-danger-soft); color: var(--kb-blocked); }',
		      '.kb-dash-tag-due { background: var(--kb-orange-soft); color: var(--kb-orange-text); }',
		      '.kb-dash-item-pct { flex: none; font-family: var(--kb-mono); font-size: 10.5px; color: var(--kb-text2); }',
		      '.kb-dash-item-prog { flex-wrap: wrap; }',
		      '.kb-dash-subbar { flex: 1 1 100%; height: 4px; border-radius: 2px; background: var(--kb-track-surface2); overflow: hidden; }',
		      '.kb-dash-subbar-fill { height: 100%; background: var(--kb-done); border-radius: 2px; }',
		      '.kb-dash-chart { height: 118px; display: flex; align-items: flex-end; gap: 4px; padding-top: 6px; }',
		      '.kb-dash-col { flex: 1; min-width: 0; height: 100%; display: flex; flex-direction: column; align-items: center; gap: 4px; }',
		      '.kb-dash-col-bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; justify-content: center; }',
		      '.kb-dash-col-bar { width: 70%; max-width: 16px; min-height: 2px; border-radius: 3px 3px 1px 1px; background: var(--kb-accent); transition: height .25s; }',
		      '.kb-dash-col-bar-wrap:hover .kb-dash-col-bar { background: var(--kb-accent-hover); }',
		      '.kb-dash-col-day { font-size: 9px; color: var(--kb-text3); font-family: var(--kb-mono); }',
		      '.kb-dash-empty { border: 1.5px dashed var(--kb-border2); border-radius: 8px; padding: 12px 8px; text-align: center; color: var(--kb-text3); font-size: 11px; }',
		      '.kb-dash-span2 { grid-column: span 2; }',
		      '.kb-dash-summary { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--kb-text2); line-height: 1.6; }',
		      '.kb-dash-sum-line { word-break: break-all; }',
		      '.kb-gantt { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 12px 16px; }',
		      '.kb-gantt-bar { flex: none; display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--kb-text2); padding: 0 2px 8px; }',
		      '.kb-gantt-bar-title { font-size: 13px; font-weight: 800; color: var(--kb-text); }',
		      '.kb-gantt-bar select { font: inherit; font-size: 12px; padding: 4px 8px; border-radius: 7px; border: 1px solid var(--kb-border2); background: var(--kb-surface); color: var(--kb-text2); }',
		      '.kb-gantt-range { margin-left: auto; font-family: var(--kb-mono); font-size: 11px; color: var(--kb-text3); }',
		      '.kb-gantt-scroll { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--kb-border); border-radius: 10px; background: var(--kb-surface); }',
		      '.kb-gantt-grid { position: relative; min-width: 100%; }',
		      '.kb-gantt-ticks { position: relative; height: 26px; border-bottom: 1px solid var(--kb-border); background: var(--kb-surface2); }',
		      '.kb-gantt-tick { position: absolute; top: 7px; transform: translateX(-50%); font-size: 10px; color: var(--kb-text3); font-family: var(--kb-mono); white-space: nowrap; }',
		      '.kb-gantt-today { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--kb-accent); opacity: .55; z-index: 2; pointer-events: none; }',
		      '.kb-gantt-row { display: flex; align-items: center; border-bottom: 1px solid var(--kb-border); cursor: pointer; }',
		      '.kb-gantt-row:hover { background: var(--kb-accent-soft); }',
		      '.kb-gantt-row:last-child { border-bottom: none; }',
		      '.kb-gantt-label { flex: none; width: 250px; display: flex; align-items: center; gap: 6px; padding: 7px 10px; font-size: 12px; min-width: 0; box-sizing: border-box; }',
		      '.kb-gantt-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--kb-text); font-weight: 600; }',
		      '.kb-gantt-track { flex: 1; position: relative; height: 34px; }',
		      '.kb-gantt-bar2 { position: absolute; top: 8px; height: 18px; border-radius: 4px; min-width: 2px; }',
		      '.kb-gantt-backlog { background: var(--kb-backlog); }',
		      '.kb-gantt-todo { background: var(--kb-todo); }',
		      '.kb-gantt-in_progress { background: var(--kb-progress); }',
		      '.kb-gantt-in_review { background: var(--kb-review); }',
		      '.kb-gantt-blocked { background: var(--kb-blocked); }',
		      '.kb-gantt-done { background: var(--kb-done); }',
		      '.kb-gantt-canceled { background: var(--kb-canceled); }',
		      '.kb-nodes { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 12px 16px; }',
		      '.kb-nodes-bar { flex: none; display: flex; align-items: baseline; gap: 10px; padding: 0 2px 10px; }',
		      '.kb-nodes-bar-title { font-size: 13px; font-weight: 800; color: var(--kb-text); }',
		      '.kb-nodes-bar-sub { font-size: 11.5px; color: var(--kb-text3); }',
		      '.kb-nodes-flow { flex: 1; min-height: 0; display: flex; gap: 10px; overflow-x: auto; align-items: stretch; }',
		      '.kb-node { flex: 1 1 0; min-width: 190px; display: flex; flex-direction: column; background: var(--kb-surface); border: 1px solid var(--kb-border); border-radius: 10px; overflow: hidden; }',
		      '.kb-node-head { display: flex; align-items: center; gap: 7px; padding: 10px 12px; border-bottom: 1px solid var(--kb-border); background: var(--kb-surface2); }',
		      '.kb-node-icon { font-size: 14px; }',
		      '.kb-node-label { font-size: 12.5px; font-weight: 700; color: var(--kb-text); }',
		      '.kb-node-desc { flex: none; padding: 6px 12px 0; font-size: 10.5px; color: var(--kb-text3); }',
		      '.kb-node-body { flex: 1; min-height: 0; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 6px; }',
		      '.kb-node-item { border: 1px solid var(--kb-border); border-radius: 8px; padding: 7px 9px; cursor: pointer; background: var(--kb-surface); }',
		      '.kb-node-item:hover { border-color: var(--kb-accent); background: var(--kb-accent-soft); }',
		      '.kb-node-item-top { display: flex; align-items: center; gap: 6px; }',
		      '.kb-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }',
		      '.kb-node-item-title { margin-top: 3px; font-size: 12px; font-weight: 600; color: var(--kb-text); line-height: 1.35; }',
		      '.kb-node-item-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; }',
		      '.kb-list { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 12px 16px; overflow: hidden; }',
		      '.kb-list-bar { flex: none; display: flex; align-items: center; gap: 8px; padding: 0 2px 8px; font-size: 11.5px; color: var(--kb-text3); }',
		      '.kb-list-bar b { color: var(--kb-accent-hover); font-family: var(--kb-mono); font-weight: 700; }',
		      '.kb-list-scroll { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--kb-border); border-radius: 10px; background: var(--kb-surface); }',
		      '.kb-list-table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 900px; }',
		      '.kb-list-table th { position: sticky; top: 0; z-index: 2; background: var(--kb-surface2); text-align: left; font-size: 11px; font-weight: 800; color: var(--kb-text3); letter-spacing: .04em; padding: 9px 10px; border-bottom: 1px solid var(--kb-border); white-space: nowrap; }',
		      '.kb-list-th.sortable { cursor: pointer; user-select: none; }',
		      '.kb-list-th.sortable:hover { color: var(--kb-accent-hover); background: var(--kb-accent-soft); }',
		      '.kb-list-th.sort-asc, .kb-list-th.sort-desc { color: var(--kb-accent-hover); }',
		      '.kb-list-th.sort-asc::after { content: " ▲"; color: var(--kb-accent); }',
		      '.kb-list-th.sort-desc::after { content: " ▼"; color: var(--kb-accent); }',
		      '.kb-list-table td { padding: 8px 10px; border-bottom: 1px solid var(--kb-border); vertical-align: middle; color: var(--kb-text2); }',
		      '.kb-list-row { cursor: pointer; transition: background .1s; }',
		      '.kb-list-row:hover { background: var(--kb-accent-soft); }',
		      '.kb-list-row:last-child td { border-bottom: none; }',
		      '.kb-list-id { font-family: var(--kb-mono); font-size: 10.5px; color: var(--kb-text3); white-space: nowrap; }',
		      '.kb-list-title { font-weight: 600; color: var(--kb-text); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }',
		      '.kb-list-tags { display: inline-flex; gap: 4px; flex-wrap: wrap; max-width: 240px; }',
		      '.kb-list-mono { font-family: var(--kb-mono); font-size: 11px; white-space: nowrap; }',
		      '.kb-list-due.overdue { color: var(--kb-blocked); font-weight: 700; }',
		      '.kb-list-empty { padding: 26px 10px; text-align: center; color: var(--kb-text3); font-size: 12px; }',
		      '.kb-lblmgr { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 10px; }',
		      '.kb-lblmgr-head { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 800; color: var(--kb-text); }',
		      '.kb-lblmgr-head .kb-count { margin-left: auto; }',
		      '.kb-lblmgr-addrow { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: var(--kb-surface); border: 1px dashed var(--kb-border2); border-radius: 10px; }',
		      '.kb-lblmgr-addrow .kb-input { flex: 1; min-width: 0; }',
		      '.kb-lblmgr-color { width: 34px; height: 30px; padding: 0; border: 1px solid var(--kb-border2); border-radius: 8px; background: var(--kb-surface2); cursor: pointer; flex: none; }',
		      '.kb-lblmgr-list { display: flex; flex-direction: column; gap: 6px; }',
		      '.kb-lblmgr-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--kb-surface); border: 1px solid var(--kb-border); border-radius: 10px; }',
		      '.kb-lblmgr-row:hover { border-color: var(--kb-border2); }',
		      '.kb-lblmgr-dot { width: 14px; height: 14px; border-radius: 50%; flex: none; border: 2px solid var(--kb-track-surface); box-shadow: 0 0 0 1px var(--kb-border); }',
		      '.kb-lblmgr-name { flex: 1; min-width: 0; font-size: 12.5px; font-weight: 600; color: var(--kb-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
		      '.kb-lblmgr-name input { width: 100%; }',
		      '.kb-lblmgr-count { font-family: var(--kb-mono); font-size: 11px; color: var(--kb-text3); background: var(--kb-track-surface); border-radius: 999px; padding: 1px 8px; flex: none; }',
		      '.kb-lblmgr-ops { display: flex; align-items: center; gap: 6px; flex: none; }',
		      '.kb-lblmgr-armed { background: var(--kb-danger) !important; border-color: var(--kb-danger) !important; color: var(--kb-on-accent) !important; }',
		    ].join('\n')
		
		    if (typeof document !== 'undefined') {
		      ctx.effect(() => {
		        const styleId = 'dsh-task-board-css'
		        let style = document.getElementById(styleId)
		        if (style === null) {
		          style = document.createElement('style')
		          style.id = styleId
		          style.textContent = CSS
		          document.head.appendChild(style)
		        }
		        return () => { try { style.remove() } catch (e) {} }
		      })
		    }
		    if (!slots) return
		
		    // 九级候选：所有选项写入整数，旧枚举只在显示读取时保序兼容。
        const LEGACY_PRI = {none:1,low:3,medium:5,high:7,urgent:9}
        const priorityLevel = (value) => {
          if (Number.isInteger(value) && value >= 1 && value <= 9) return value
          return Object.prototype.hasOwnProperty.call(LEGACY_PRI,value) ? LEGACY_PRI[value] : 1
        }
        const PRIORITIES = Array.from({length:9},(_,i)=>{
          const key=9-i
          return {key,label:key+'级'+(key===9?'（最高）':key===1?'（最低）':''),cls:key>=8?'kb-pri-urgent':key>=6?'kb-pri-high':key>=4?'kb-pri-medium':'kb-pri-low'}
        })
        const STATUSES = [
		      { key: 'backlog', label: '待立项', color: 'var(--kb-backlog)' },
		      { key: 'todo', label: '等待认领', color: 'var(--kb-todo)' },
		      { key: 'in_progress', label: '处理中', color: 'var(--kb-progress)' },
		      { key: 'in_review', label: '待验收', color: 'var(--kb-review)' },
		      { key: 'blocked', label: '遇到阻碍', color: 'var(--kb-blocked)' },
		      { key: 'done', label: '完成', color: 'var(--kb-done)' },
		      { key: 'canceled', label: '取消', color: 'var(--kb-canceled)' },
		    ]
		    const MAIN_COLS = ['backlog', 'todo', 'in_progress', 'in_review', 'done']
		    const statusMeta = (key) => STATUSES.find(s => s.key === key) || STATUSES[0]
		
		    // ============ stable view components (defined outside Board so re-renders never remount them) ============
		
		    function CardView({ issue, state, issues, selWs, openDetail, act, openMenu }) {
		      const st = statusMeta(issue.status)
		      const labels = issue.labels || []
		      const tags = []
		      if (issue.priority !== undefined && issue.priority !== null) {
		        const p = PRIORITIES.find(x => x.key === priorityLevel(issue.priority))
		        tags.push(el('span', { className: 'kb-chip2 ' + (p ? p.cls : 'kb-pri-none') }, (p ? p.label : issue.priority)))
		      }
		      labels.slice(0, 2).forEach(l => {
		        const lb = (state.labels || []).find(x => x.name === l)
		        tags.push(el('span', { className: 'kb-chip2 kb-lbl', style: lb ? { color: lb.color, background: lb.color + '1a' } : null }, l))
		      })
		      if (labels.length > 2) tags.push(el('span', { className: 'kb-chip2 kb-lbl' }, '+' + (labels.length - 2)))
		      if (issue.dueDate) tags.push(el('span', { className: 'kb-chip2 kb-pri-low' }, '📅 ' + issue.dueDate))
		      // 执行中 / 验收中 / 已完结（完成、取消）都不显示重试标记
		      const hidingRetry = (issue.run && issue.run.status === 'running') || !!issue.acceptanceSubagentId || issue.status === 'done' || issue.status === 'canceled'
		      if (!hidingRetry && issue.retries > 0) tags.push(el('span', { className: 'kb-chip2 kb-lbl-fail' }, '重试×' + issue.retries))
		      if (!hidingRetry && issue.lastFailure) tags.push(el('button', {
		        className: 'kb-chip2 kb-lbl-fail kb-retrybtn',
		        title: '失败原因: ' + (issue.lastFailure.reason || '') + ' — 点击重新派发执行',
		        onClick: (e) => { e.stopPropagation(); void act(() => call('retryIssue', { workspaceId: selWs.id, id: issue.id })) },
		      }, '↻ 重试'))
		      if ((issue.blockedBy || []).length) tags.push(el('span', { className: 'kb-chip2 kb-lbl-fail' }, '被阻塞'))
		      if (issue.parentId) tags.push(el('span', { className: 'kb-chip2 kb-lbl' }, '子议题'))
		      if ((issue.children || []).length) tags.push(el('span', { className: 'kb-chip2 kb-lbl' }, '子议题×' + issue.children.length))
		      if (issue.run && issue.run.status === 'running') tags.push(el('span', { className: 'kb-chip2 kb-lbl-s' }, '● 运行中'))
		      if (issue.acceptanceSubagentId) tags.push(el('span', { className: 'kb-chip2 kb-lbl-s' }, '● 验收中'))
		      if (issue.acceptedAt) tags.push(el('span', { className: 'kb-chip2 kb-lbl-ok' }, '✓ 验收完成'))
		
		      const batch = state.batches.find(b => b.id === (issue.run && issue.run.batchId))
		      const total = batch ? batch.issueIds.length : 0
		      const idx = batch ? batch.issueIds.indexOf(issue.id) : -1
		
		      return el('div', {
		        className: 'kb-card' + (issue.run && issue.run.status === 'running' ? ' dragging' : ''),
		        style: { '--kb-card-c': st.color },
		        draggable: true,
		        onDragStart: (e) => { e.dataTransfer.setData('text/kanban-id', issue.id); e.dataTransfer.effectAllowed = 'move' },
		        onClick: () => openDetail(issue.id),
		        onContextMenu: (e) => {
		          e.preventDefault(); e.stopPropagation()
		          openMenu({ id: issue.id, x: Math.min(e.clientX, window.innerWidth - 210), y: Math.min(e.clientY, window.innerHeight - 320), sub: null })
		        },
		      },
		        el('div', { className: 'kb-card-top' },
		          el('span', { className: 'kb-card-id' }, issue.id),
		          issue.unread ? el('span', { className: 'kb-unread', title: '有新的活动' }) : null,
		          issue.status === 'in_review'
		            ? el('button', { className: 'kb-donebtn', onClick: (e) => { e.stopPropagation(); void act(() => call('accept', { workspaceId: selWs.id, id: issue.id, pass: true, report: '' })) } }, '✓ 完成')
		            : null,
		        ),
		        el('div', { className: 'kb-card-title' }, issue.title),
		        el('div', { className: 'kb-card-meta' }, tags),
		        total > 0 ? el('div', { className: 'kb-progress', title: '批次 ' + (issue.run.batchId) },
		          Array.from({ length: total }, (_, i) => el('span', { key: i, className: 'seg' + (i === idx ? ' cur' : i < idx ? ' on' : '') }))
		        ) : null,
		        (issue.children || []).length > 0 ? (() => {
		          const kids = issues.filter(c => (issue.children || []).includes(c.id))
		          const doneN = kids.filter(c => c.status === 'done').length
		          return el('div', { className: 'kb-subprogress' },
		            el('div', { className: 'bar' }, el('div', { className: 'fill', style: { width: (doneN / kids.length * 100) + '%' } })),
		          )
		        })() : null,
		      )
		    }
		
		    function ContextMenuView({ ctxMenu, issueById, state, selWs, moveIssue, act, closeMenu, setSub, openDetail, sessionsSvc, workspacesSvc, closeBoard }) {
		      // 右键菜单键盘快捷键：S/P/L 切换子菜单；状态子菜单打开时数字 1-7 直接移动；Esc 关闭
		      React.useEffect(() => {
		        if (!ctxMenu) return
		        const onKey = (e) => {
		          const t = e.target
		          if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return
		          if (e.key.toLowerCase() === 's') { e.preventDefault(); setSub('status') }
		          else if (e.key.toLowerCase() === 'p') { e.preventDefault(); setSub('priority') }
		          else if (e.key.toLowerCase() === 'l') { e.preventDefault(); setSub('labels') }
		          else if (/^[1-7]$/.test(e.key)) {
		            const s = STATUSES[Number(e.key) - 1]
		            if (s) { e.preventDefault(); moveIssue(ctxMenu.id, s.key); closeMenu() }
		          } else if (e.key === 'Escape') { closeMenu() }
		        }
		        window.addEventListener('keydown', onKey)
		        return () => window.removeEventListener('keydown', onKey)
		        // eslint-disable-next-line react-hooks/exhaustive-deps
		      }, [ctxMenu])
		      if (!ctxMenu) return null
		      const issue = issueById(ctxMenu.id)
		      if (!issue) return null
		      const sub = ctxMenu.sub
		      const menu = (children) => el('div', { className: 'kb-ctxmenu', style: { left: ctxMenu.x, top: ctxMenu.y }, onClick: (e) => e.stopPropagation(), onContextMenu: (e) => { e.preventDefault(); e.stopPropagation() } }, children)
		      if (sub === 'status') {
		        return menu(STATUSES.map(s => el('div', { key: s.key, className: 'item' + (issue.status === s.key ? ' active' : ''), onClick: () => { moveIssue(issue.id, s.key); closeMenu() } },
		          el('span', { style: { width: 9, height: 9, borderRadius: 3, background: s.color } }),
		          s.label,
		          s.key === issue.status ? el('span', { className: 'k' }, '✓') : null,
		        )))
		      }
		      if (sub === 'priority') {
		        return menu(PRIORITIES.map(p => el('div', { key: p.key, className: 'item' + (priorityLevel(issue.priority) === p.key ? ' active' : ''), onClick: () => { void act(() => call('updateIssue', { workspaceId: selWs.id, id: issue.id, version: issue.version, patch: { priority: p.key } })); closeMenu() } }, p.label)))
		      }
		      if (sub === 'labels') {
		        const cur = issue.labels || []
		        return menu((state.labels || []).map(l => el('div', { key: l.name, className: 'item' + (cur.includes(l.name) ? ' active' : ''), onClick: () => {
		          const next = cur.includes(l.name) ? cur.filter(x => x !== l.name) : [...cur, l.name]
		          void act(() => call('updateIssue', { workspaceId: selWs.id, id: issue.id, version: issue.version, patch: { labels: next } }))
		          closeMenu()
		        } }, el('span', { style: { width: 9, height: 9, borderRadius: 3, background: l.color } }), l.name)))
		      }
		      const items = [
		        el('div', { key: 'status', className: 'kb-ctxsub' },
		          el('div', { className: 'item', onClick: () => setSub('status') }, '状态', el('span', { className: 'k' }, 'S')),
		          ctxMenu.sub === 'status' ? el('div', { className: 'fly' }, STATUSES.map(s => el('div', { key: s.key, className: 'item', onClick: () => { moveIssue(issue.id, s.key); closeMenu() } }, s.label))) : null,
		        ),
		        el('div', { key: 'pri', className: 'item', onClick: () => setSub('priority') }, '优先级', el('span', { className: 'k' }, 'P')),
		        el('div', { key: 'lbl', className: 'item', onClick: () => setSub('labels') }, '标签', el('span', { className: 'k' }, 'L')),
		        el('div', { key: 'sep1', className: 'sep' }),
		        el('div', { key: 'edit', className: 'item', onClick: () => { openDetail(issue.id); closeMenu() } }, '编辑议题', el('span', { className: 'k' }, '↵')),
		        el('div', { key: 'dup', className: 'item', onClick: () => { void act(() => call('createIssue', { workspaceId: selWs.id, title: issue.title + '（副本）', description: issue.description, priority: priorityLevel(issue.priority), labels: issue.labels })); closeMenu() } }, '创建副本'),
		        el('div', { key: 'sep2', className: 'sep' }),
		        el('div', { key: 'copyid', className: 'item', onClick: () => { try { window.navigator.clipboard.writeText(issue.id) } catch (e) {} closeMenu() } }, '复制议题 ID'),
		        el('div', { key: 'copyt', className: 'item', onClick: () => { try { window.navigator.clipboard.writeText(issue.title) } catch (e) {} closeMenu() } }, '复制标题'),
		        el('div', { key: 'copymd', className: 'item', onClick: () => { try { window.navigator.clipboard.writeText('[' + issue.id + '] ' + issue.title + '\n' + (issue.description || '')) } catch (e) {} closeMenu() } }, '复制 Markdown'),
		        el('div', { key: 'sep3', className: 'sep' }),
		        el('div', { key: 'open', className: 'item', onClick: () => {
		          if (issue.run && issue.run.subagentId && sessionsSvc) { try { sessionsSvc.open(issue.run.subagentId) } catch (e) {} }
		          else if (workspacesSvc && selWs) { try { void workspacesSvc.connectWorkspace(selWs.id) } catch (e) {} }
		          closeMenu(); closeBoard()
		        } }, '在对话中打开'),
		        el('div', { key: 'arch', className: 'item danger', onClick: () => { void act(() => call('archiveIssue', { workspaceId: selWs.id, id: issue.id, version: issue.version, archived: true })); closeMenu() } }, '归档议题', el('span', { className: 'k' }, '⌘⌫')),
		      ]
		      return menu(items)
		    }
		
		    // 本地时间（东八区）显示：评论/活动流的时间戳存 UTC ISO，直接 slice 会显示 UTC
		    const fmtWhen = (iso) => {
		      if (!iso) return ''
		      const d = new Date(iso)
		      if (isNaN(d.getTime())) return String(iso).slice(5, 16)
		      const p = (n) => String(n).padStart(2, '0')
		      return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
		    }
		
		    function DiagnosticRecoveryView({detail,selWs,act}) {
          const [evidence,setEvidence]=React.useState('')
          const [evidenceKey,setEvidenceKey]=React.useState('')
          const [message,setMessage]=React.useState('')
          const [submitting,setSubmitting]=React.useState(false)
          const control=detail.failureControl
          if (!control) return null
          const canResolve=detail.status==='blocked' && !(detail.blockedBy||[]).length
            && ['diagnose','hold'].includes(control.action)
            && !['authorization','configuration','repair'].includes(control.category)
            && control.holdReason!=='repair-budget-exhausted'
          const submit=async()=>{
            if(submitting)return
            setSubmitting(true);setMessage('正在核对当前失败记录…')
            try {
              let result
              await act(async()=>{result=await call('resolveFailure',{workspaceId:selWs.id,id:detail.id,version:detail.version,
                failureToken:control.fingerprint||control.holdReason,evidence,evidenceKey});return result})
              setMessage(result && result.ok ? '诊断证据已保存，任务仅恢复一次。' : (result && result.message)||'提交未确认成功，请刷新核对。')
            }catch(error){setMessage('提交失败：'+String(error))}finally{setSubmitting(false)}
          }
          return el('div',{className:'kb-field'},
            el('h4',null,'失败处理与恢复'),
            el('p',null,canResolve?'提交新的可复核证据后，仅允许恢复一次。':(control.category==='authorization'?'这是授权类挂起：只能由本人在下方「授权确认」中确认后放回队列，诊断证据不能代替授权。':'任务仍受阻，请先完成修复前置或取得所需授权。')),
            canResolve?el('div',null,
              el('label',null,'新证据标识'),el('input',{value:evidenceKey,onChange:e=>setEvidenceKey(e.target.value),placeholder:'日志或验证记录的唯一标识'}),
              el('label',null,'诊断依据'),el('textarea',{value:evidence,onChange:e=>setEvidence(e.target.value),placeholder:'填写新验证结果与可复核位置，不得以旧证据重复重试'}),
              el('button',{className:'kb-btn',disabled:submitting||evidence.trim().length<10||evidenceKey.trim().length<8,onClick:submit},submitting?'正在提交…':'记录证据并恢复一次')
            ):null,
            message?el('p',{role:'status'},message):null
          )
        }
		    // ---- 授权类挂起的用户确认通道（k-mvae3o8m-29）----
	    // 事故：授权类挂起（action='hold' + category='authorization'）此前没有任何解锁入口 ——
	    // moveIssue→todo 被 retryGuard 拦下、resolveFailure 又显式拒绝授权类，只能靠“取消 + 另立承接卡”绕过。
	    // 这里补的就是“用户本人在界面上点确认”这条路径：勾选 + 写明人工动作，才发 grantAuthorization。
	    const AUTH_NOTE_DEFAULT = '我已完成所需的人工动作/批准'
	    function AuthorizationGrantView({ detail, selWs, act }) {
	      const control = detail.failureControl
	      const token = control ? (control.fingerprint || control.holdReason || '') : ''
	      const isAuthHold = detail.status === 'blocked' && !(detail.blockedBy || []).length && !!control && control.action === 'hold' && control.category === 'authorization'
	      const [checked, setChecked] = React.useState(false)
	      const [note, setNote] = React.useState(AUTH_NOTE_DEFAULT)
	      const [message, setMessage] = React.useState('')
	      const [submitting, setSubmitting] = React.useState(false)
	      if (!isAuthHold) return null
	      const granted = (detail.authorizationGrants || []).some(g => g.failureToken === token)
	      const submit = async () => {
	        if (submitting || !checked || note.trim().length < 4) return
	        setSubmitting(true)
	        setMessage('正在记录授权…')
	        try {
	          const args = { workspaceId: selWs.id, id: detail.id, version: detail.version, failureToken: token, note: note.trim(), evidenceKey: 'ui-grant-' + Date.now().toString(36), confirmed: true }
	          let result
	          await act(async () => { result = await call('grantAuthorization', args); return result })
	          setMessage(result && result.ok ? '授权已确认，任务回到待执行队列（同一失败只放行一次）。' : ((result && result.message) || '提交未确认成功，请刷新核对。'))
	        } catch (error) {
	          setMessage('提交失败：' + String(error))
	        } finally {
	          setSubmitting(false)
	        }
	      }
	      return el('div', { className: 'kb-field', style: { flexBasis: '100%' } },
	        el('h4', null, '授权确认（仅本人可点）'),
	        granted ? el('p', null, '该失败已授权过一次；若再次因同一失败受阻，需要新的授权，不能重复放行。')
	          : el('p', null, '这条任务因授权问题挂起（需要人工动作或批准）。诊断证据不能代替授权，请完成所需动作后由本人在此确认。'),
	        granted ? null : el('div', null,
	          el('label', null, el('input', { type: 'checkbox', checked: checked, onChange: (e) => setChecked(e.target.checked) }), ' 我已完成所需的人工动作/批准'),
	          el('label', null, '授权说明'),
	          el('input', { value: note, onChange: (e) => setNote(e.target.value), placeholder: AUTH_NOTE_DEFAULT }),
	          el('button', { className: 'kb-btn', disabled: submitting || !checked || note.trim().length < 4, onClick: submit }, submitting ? '正在提交…' : '确认授权并放回队列'),
	        ),
	        message ? el('p', { role: 'status' }, message) : null,
	      )
	    }

        function DetailView({ detail, state, issues, issueById, statusLabel, selWs, act, closeDetail, openDetail, addLabel, deleteLabel }) {
		      const [newLabel, setNewLabel] = React.useState('')
		      const [title, setTitle] = React.useState(detail.title)
		      const [desc, setDesc] = React.useState(detail.description || '')
		      const [pri, setPri] = React.useState(priorityLevel(detail.priority))
		      const [labels, setLabels] = React.useState(detail.labels || [])
		      const [due, setDue] = React.useState(detail.dueDate || '')
		      const [relQuery, setRelQuery] = React.useState('')
		      const [comment, setComment] = React.useState('')
		      const [childTitle, setChildTitle] = React.useState('')
		      const [recurrence, setRecurrence] = React.useState((detail.recurrence && detail.recurrence.freq) || '')
		      const savePatch = (patch) => {
		        void act(() => call('updateIssue', { workspaceId: selWs.id, id: detail.id, version: detail.version, patch })).then(() => {
		          void call('updateIssue', { workspaceId: selWs.id, id: detail.id, patch: { unread: false } }).catch(() => {})
		        })
		      }
		      const addChild = () => {
		        const t = childTitle.trim()
		        if (!t) return
		        void act(() => call('createIssue', { workspaceId: selWs.id, title: t, parentId: detail.id }))
		        setChildTitle('')
		      }
		      return el('div', { className: 'kb-modal' },
		        el('div', { className: 'kb-modal-box kb-edit-box', onClick: (e) => e.stopPropagation() },
		          el('div', { className: 'kb-modal-head' },
		            el('h3', null, '编辑议题'),
		            el('span', { className: 'kb-card-id' }, detail.id),
		            el('span', { className: 'kb-chip2 kb-lbl' }, statusLabel(detail.status)),
		            el('div', { className: 'kb-spacer' }),
		            detail.archivedAt ? null : el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => { void act(() => call('archiveIssue', { workspaceId: selWs.id, id: detail.id, version: detail.version, archived: true })); closeDetail() } }, '归档'),
		            el('button', { className: 'kb-btn kb-btn-ghost kb-btn-close', onClick: () => closeDetail() }, '✕'),
		          ),
		          el('div', { className: 'kb-edit-body' },
		            detail.acceptanceSubagentId ? el('div', { className: 'kb-banner' }, '⏳ 验收 agent 正在独立验收中…') : null,
                    el('p', null, '基础优先级：' + priorityLevel(detail.basePriority ?? detail.priority) + '级；当前调度级：' + priorityLevel(detail.effectivePriority ?? detail.priority) + '级' + ((detail.blockedBy || []).length || detail.status === 'blocked' ? '（受阻，不参与调度）' : '')),
                    el(DiagnosticRecoveryView, { detail, selWs, act }),
                    el(AuthorizationGrantView, { detail, selWs, act }),
		            el('div', { className: 'kb-field' },
		              el('label', null, '标题'),
		              el('input', { value: title, onChange: (e) => setTitle(e.target.value), onBlur: () => { if (title.trim() && title.trim() !== detail.title) savePatch({ title }) } }),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '描述'),
		              el('textarea', { value: desc, onChange: (e) => setDesc(e.target.value), onBlur: () => { if (desc !== (detail.description || '')) savePatch({ description: desc }) } }),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '优先级'),
		              el('select', { value: pri, onChange: (e) => { setPri(Number(e.target.value)); savePatch({ priority: Number(e.target.value) }) } },
		                PRIORITIES.map(p => el('option', { key: p.key, value: p.key }, p.label)),
		              ),
		            ),
		            el('div', null,
		              el('h4', null, '标签'),
		              el('div', { className: 'kb-tagrow' },
		                (state.labels || []).map(l => el('span', { key: l.name, className: 'kb-tagwrap' },
		                  el('button', { className: 'kb-tagpick' + (labels.includes(l.name) ? ' on' : ''), style: labels.includes(l.name) ? { color: l.color, borderColor: l.color } : null, onClick: () => {
		                    const next = labels.includes(l.name) ? labels.filter(x => x !== l.name) : [...labels, l.name]
		                    setLabels(next)
		                    savePatch({ labels: next })
		                  } }, l.name),
		                  el('button', { className: 'kb-tagdel', title: '删除标签「' + l.name + '」', onClick: () => { deleteLabel(l.name); setLabels(prev => prev.filter(x => x !== l.name)) } }, '✕'),
		                )),
		              ),
		              el('div', { style: { display: 'flex', gap: 6, marginTop: 6 } },
		                el('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '新建标签名', value: newLabel, onChange: (e) => setNewLabel(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') { const n = newLabel.trim(); if (n) { addLabel(n); setNewLabel('') } } } }),
		                el('button', { className: 'kb-mini', onClick: () => { const n = newLabel.trim(); if (n) { addLabel(n); setNewLabel('') } } }, '新建标签'),
		              ),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '截止日期'),
		              el('input', { type: 'date', value: due, onChange: (e) => { setDue(e.target.value); savePatch({ dueDate: e.target.value || null }) } }),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '周期'),
		              el('select', { value: recurrence, onChange: (e) => { const f = e.target.value; setRecurrence(f); savePatch({ recurrence: f ? { freq: f, interval: 1, endDate: null } : null }) } },
		                el('option', { value: '' }, '不重复'),
		                el('option', { value: 'daily' }, '每天'),
		                el('option', { value: 'weekly' }, '每周'),
		                el('option', { value: 'monthly' }, '每月'),
		                el('option', { value: 'yearly' }, '每年'),
		              ),
		            ),
		            el('div', null,
		              el('h4', null, '子议题'),
		              (detail.children && detail.children.length > 0) ? el('div', { className: 'kb-tagrow' }, detail.children.map(cid => { const c = issueById(cid); return c ? el('span', { key: cid, className: 'kb-chip2 ' + (c.status === 'done' ? 'kb-lbl-ok' : 'kb-lbl'), onClick: () => openDetail(cid), style: { cursor: 'pointer' } }, c.title) : null })) : null,
		              el('div', { style: { display: 'flex', gap: 6, marginTop: 6 } },
		                el('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '添加子议题标题…', value: childTitle, onChange: (e) => setChildTitle(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') addChild() } }),
		                el('button', { className: 'kb-mini', onClick: addChild }, '添加子议题'),
		              ),
		            ),
		            (detail.blockedBy || []).length > 0 ? el('div', null,
		              el('h4', null, '被阻塞于'),
		              el('div', { className: 'kb-tagrow' }, detail.blockedBy.map(bid => { const b = issueById(bid); return el('span', { key: bid, className: 'kb-chip2 kb-lbl-fail' }, b ? b.title : bid) })),
		            ) : null,
		            el('div', null,
		              el('h4', null, '关联议题'),
		              el('div', { className: 'kb-tagrow' }, (detail.related || []).map(rid => { const r = issueById(rid); return el('span', { key: rid, className: 'kb-chip2 kb-lbl', style: { cursor: 'pointer' }, onClick: () => openDetail(rid) }, (r ? r.title : rid), el('button', { className: 'kb-chip-x', title: '解除关联', onClick: (e) => { e.stopPropagation(); savePatch({ related: (detail.related || []).filter(x => x !== rid) }) } }, '✕')) })),
		              // 关联搜索：输入关键词自动匹配标题/ID，点击候选即关联
		              el('div', { style: { display: 'flex', gap: 6, marginTop: 6 } },
		                el('input', {
		                  className: 'kb-input', style: { flex: 1 }, placeholder: '搜索标题/ID 关联…',
		                  value: relQuery, onChange: (e) => setRelQuery(e.target.value),
		                  onKeyDown: (e) => { if (e.key === 'Enter' && relQuery.trim()) { savePatch({ related: [...(detail.related || []), relQuery.trim()] }); setRelQuery('') } },
		                }),
		                el('button', { className: 'kb-mini', onClick: () => { const q = relQuery.trim(); if (!q) return; savePatch({ related: [...(detail.related || []), q] }); setRelQuery('') } }, '添加'),
		              ),
		              relQuery.trim() ? el('div', { className: 'kb-tagrow', style: { marginTop: 6 } },
		                issues
		                  .filter(i => i.id !== detail.id && !(detail.related || []).includes(i.id))
		                  .filter(i => i.title.toLowerCase().includes(relQuery.trim().toLowerCase()) || i.id.toLowerCase().includes(relQuery.trim().toLowerCase()))
		                  .slice(0, 6)
		                  .map(i => el('span', { key: i.id, className: 'kb-chip2 kb-lbl', style: { cursor: 'pointer', color: 'var(--kb-accent-hover)', border: '1px solid var(--kb-accent)' }, title: i.title, onClick: () => { savePatch({ related: [...(detail.related || []), i.id] }); setRelQuery('') } }, i.id + ' · ' + i.title.slice(0, 18))),
		              ) : null,
		            ),
		            el('div', null,
		              el('h4', null, '评论'),
		              (detail.comments || []).map((c, i) => el('div', { key: i, className: 'kb-comment' },
		                el('span', { className: 'who' }, c.who), el('span', { className: 'when' }, fmtWhen(c.at)), el('div', null, c.text),
		              )),
		              el('div', { style: { display: 'flex', gap: 6, marginTop: 8 } },
		                el('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '写评论…', value: comment, onChange: (e) => setComment(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') { const t = comment.trim(); if (t) { void act(() => call('addComment', { workspaceId: selWs.id, id: detail.id, text: t })); setComment('') } } } }),
		                el('button', { className: 'kb-mini primary', onClick: () => { const t = comment.trim(); if (t) { void act(() => call('addComment', { workspaceId: selWs.id, id: detail.id, text: t })); setComment('') } } }, '发送'),
		              ),
		            ),
		            el('div', null,
		              el('h4', null, '活动流'),
		              el('div', { className: 'kb-activity' },
		                (detail.activity || []).slice().reverse().map((a, i) => el('div', { key: i, className: 'kb-act' },
		                  a.kind === 'status' ? (a.by + ' 将状态从「' + statusLabel(a.from) + '」移至「' + statusLabel(a.to) + '」') : a.kind === 'create' ? '创建议题' : a.kind === 'archive' ? (a.to === 'archived' ? '已归档' : '已恢复') : '更新',
		                  el('span', { className: 'at' }, fmtWhen(a.at)),
		                )),
		              ),
		            ),
		            detail.archivedAt ? el('div', { className: 'kb-field' },
		              el('button', { className: 'kb-mini danger', onClick: () => { void act(() => call('deleteIssue', { workspaceId: selWs.id, id: detail.id, version: detail.version })); closeDetail() } }, '永久删除'),
		            ) : null,
		            el('div', { className: 'kb-modal-actions', style: { marginTop: 12 } },
		              el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => closeDetail() }, '取消'),
		            ),
		          ),
		        ),
		      )
		    }
		
		    function DashboardView({ state, issues, selWs, act, openDetail }) {
		      const [dash, setDash] = React.useState(null)
		      const [loading, setLoading] = React.useState(false)
		      const [err, setErr] = React.useState('')
		
		      const load = React.useCallback(() => {
		        if (!selWs) { setDash(null); setLoading(false); return }
		        setLoading(true)
		        call('getDashboard', { workspaceId: selWs.id })
		          .then((r) => {
		            if (r && r.ok) { setDash(r.dashboard); setErr('') }
		            else setErr((r && r.message) || '读取仪表盘失败')
		          })
		          .catch((e) => setErr('读取仪表盘失败: ' + String(e)))
		          .finally(() => setLoading(false))
		        // eslint-disable-next-line react-hooks/exhaustive-deps
		      }, [selWs && selWs.id])
		      React.useEffect(() => { load() }, [load])
		
		      if (!selWs) return el('div', { className: 'kb-dash' }, el('div', { className: 'kb-dash-empty' }, '请先选择工作区'))
		      if (loading && !dash) return el('div', { className: 'kb-dash' }, el('div', { className: 'kb-dash-empty' }, '仪表盘加载中…'))
		      if (!dash) return el('div', { className: 'kb-dash' }, el('div', { className: 'kb-dash-empty' }, err || '暂无数据'))
		
		      const { totals, completion, priority, labels, contributors, attention, inProgress, dueSoon, activityByDay, childrenProgress, forecast } = dash
		      const PRI_COLORS = Object.fromEntries(PRIORITIES.map(p=>[p.key,p.key>=8?'var(--kb-blocked)':p.key>=6?'var(--kb-orange-text)':p.key>=4?'var(--kb-yellow-text)':'var(--kb-blue-text)']))
		      const STATUS_KEYS = ['backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'canceled']
		      const maxStatus = Math.max(1, ...STATUS_KEYS.map(k => totals[k] || 0))
		      const maxAct = Math.max(1, ...activityByDay.map(d => d.count))
		      const maxLabel = Math.max(1, ...labels.map(l => l.count))
		
		      const barRow = (label, n, max, color, extra) => el('div', { className: 'kb-dash-bar-row' },
		        el('span', { className: 'kb-dash-bar-label' }, label),
		        el('div', { className: 'kb-dash-bar-track' },
		          el('div', { className: 'kb-dash-bar-fill', style: { width: Math.round(n / max * 100) + '%', background: color } }),
		        ),
		        el('span', { className: 'kb-dash-bar-num' }, n),
		        extra || null,
		      )
		
		      const issueItem = (i, extra) => el('div', { key: i.id, className: 'kb-dash-item', onClick: () => openDetail(i.id), title: i.title },
		        el('span', { className: 'kb-dash-item-id' }, i.id),
		        el('span', { className: 'kb-dash-item-title' }, i.title),
		        extra || null,
		      )
		
		      const sectionTitle = (text, n) => el('div', { className: 'kb-dash-sec-title' }, text, n > 0 ? el('span', { className: 'kb-dash-sec-count' }, n) : null)
		      const empty = (text) => el('div', { className: 'kb-dash-empty' }, text)
		
		      // 项目总结（P2）：从聚合数据生成一段可复制摘要，供发送到 DSH 会话
		      const buildSummary = () => {
		        const lines = []
		        lines.push('完成度：' + completion.percent + '%（' + completion.done + '/' + completion.total + '）')
		        lines.push('状态：' + STATUS_KEYS.map(k => statusMeta(k).label + ' ' + (totals[k] || 0)).join(' · ') + (totals.archived ? ' · 已归档 ' + totals.archived : ''))
		        const running = inProgress.filter(i => i.run === 'running')
		        if (running.length) lines.push('执行中：' + running.map(i => i.title).join('、'))
		        if (attention.blocked) lines.push('阻塞 ' + attention.blocked + ' 个')
		        if (attention.unread) lines.push('未读 ' + attention.unread + ' 个')
		        if (dueSoon.length) lines.push('7 天内到期：' + dueSoon.map(i => i.title).join('、'))
		        if (forecast.estDays !== null) lines.push('进度预测：近 7 天日均完成 ' + forecast.avgDonePerDay + ' 个，预计 ' + forecast.estDays + ' 天完成剩余 ' + forecast.remaining + ' 个')
		        else if (forecast.note) lines.push('进度预测：' + forecast.note)
		        return lines
		      }
		
		      return el('div', { className: 'kb-dash' },
		        // 完成度 + 进度预测（跨整行）
		        el('div', { className: 'kb-dash-card kb-dash-hero' },
		          el('div', { className: 'kb-dash-hero-left' },
		            el('div', { className: 'kb-dash-hero-num' }, completion.percent + '%'),
		            el('div', { className: 'kb-dash-hero-sub' }, '完成度 · ' + completion.done + ' / ' + completion.total),
		            el('div', { className: 'kb-dash-bar kb-dash-hero-bar' },
		              el('div', { className: 'kb-dash-bar-fill', style: { width: completion.percent + '%', background: 'var(--kb-accent)' } }),
		            ),
		          ),
		          el('div', { className: 'kb-dash-hero-right' },
		            el('div', { className: 'kb-dash-card-title' }, '进度预测'),
		            forecast.estDays !== null
		              ? el('div', { className: 'kb-dash-hero-stat' }, '预计 ', el('b', null, forecast.estDays), ' 天 · 日均完成 ', el('b', null, forecast.avgDonePerDay), ' 个')
		              : el('div', { className: 'kb-dash-hero-stat' }, forecast.note),
		            el('div', { className: 'kb-dash-hero-stat kb-dash-hero-sub2' }, '剩余 ', el('b', null, forecast.remaining), ' 个待完成'),
		            el('button', { className: 'kb-mini kb-dash-refresh', onClick: () => load() }, '↻ 刷新'),
		          ),
		        ),
		
		        // 状态分布（横条）
		        el('div', { className: 'kb-dash-card' },
		          el('div', { className: 'kb-dash-card-title' }, '状态分布'),
		          STATUS_KEYS.map(k => barRow(statusMeta(k).label, totals[k] || 0, maxStatus, statusMeta(k).color, null)),
		          totals.archived > 0 ? barRow('已归档', totals.archived, Math.max(maxStatus, totals.archived), 'var(--kb-text3)', null) : null,
		        ),
		
		        // 优先级分布（彩色条）
		        el('div', { className: 'kb-dash-card' },
		          el('div', { className: 'kb-dash-card-title' }, '优先级分布'),
		          PRIORITIES.map(p => barRow(p.label, priority[p.key] || 0, maxStatus, PRI_COLORS[p.key] || 'var(--kb-text3)', null)),
		        ),
		
		        // 标签分布（按标签定义色）
		        el('div', { className: 'kb-dash-card' },
		          el('div', { className: 'kb-dash-card-title' }, '标签分布'),
		          labels.filter(l => l.count > 0).map(l => barRow(l.name, l.count, maxLabel, l.color, null)),
		          labels.filter(l => l.count > 0).length === 0 ? empty('暂无标签') : null,
		        ),
		
		        // 贡献图：近 14 天活动（CSS 柱状，高度按 count 百分比）
		        el('div', { className: 'kb-dash-card kb-dash-chart-card' },
		          el('div', { className: 'kb-dash-card-title' }, '近 14 天活动'),
		          el('div', { className: 'kb-dash-chart' },
		            activityByDay.map((d, i) => el('div', { key: d.date, className: 'kb-dash-col', title: d.date + ' · ' + d.count + ' 条' },
		              el('div', { className: 'kb-dash-col-bar-wrap' },
		                el('div', { className: 'kb-dash-col-bar', style: { height: (d.count ? Math.max(6, Math.round(d.count / maxAct * 100)) : 3) + '%' } }),
		              ),
		              el('span', { className: 'kb-dash-col-day' }, d.date.slice(5)),
		            )),
		          ),
		        ),
		
		        // 需要关注：未读 / 阻塞 卡片列表
		        el('div', { className: 'kb-dash-card' },
		          el('div', { className: 'kb-dash-card-title' }, '需要关注'),
		          sectionTitle('未读', attention.unread),
		          attention.unreadList.length ? el('div', { className: 'kb-dash-list' }, attention.unreadList.map(i => issueItem(i, null))) : empty('暂无未读'),
		          sectionTitle('阻塞', attention.blocked),
		          attention.blockedList.length ? el('div', { className: 'kb-dash-list' }, attention.blockedList.map(i => issueItem(i, el('span', { className: 'kb-dash-item-tag kb-dash-tag-block' }, '阻塞')))) : empty('暂无阻塞'),
		        ),
		
		        // 进行中
		        el('div', { className: 'kb-dash-card' },
		          el('div', { className: 'kb-dash-card-title' }, '进行中 (' + inProgress.length + ')'),
		          inProgress.length ? el('div', { className: 'kb-dash-list' }, inProgress.map(i => issueItem(i,
		            i.run === 'running' ? el('span', { className: 'kb-dash-item-tag kb-dash-tag-run' }, '● 运行中') : null,
		          ))) : empty('暂无进行中议题'),
		        ),
		
		        // 即将到期
		        el('div', { className: 'kb-dash-card' },
		          el('div', { className: 'kb-dash-card-title' }, '7 天内到期 (' + dueSoon.length + ')'),
		          dueSoon.length ? el('div', { className: 'kb-dash-list' }, dueSoon.map(i => issueItem(i,
		            el('span', { className: 'kb-dash-item-tag kb-dash-tag-due' }, '📅 ' + i.dueDate),
		          ))) : empty('7 天内无到期议题'),
		        ),
		
		        // 子议题进度（含小进度条）
		        el('div', { className: 'kb-dash-card kb-dash-span2' },
		          el('div', { className: 'kb-dash-card-title' }, '子议题进度'),
		          childrenProgress.length ? el('div', { className: 'kb-dash-list' },
		            childrenProgress.map(p => el('div', { key: p.id, className: 'kb-dash-item kb-dash-item-prog', onClick: () => openDetail(p.id) },
		              el('span', { className: 'kb-dash-item-id' }, p.id),
		              el('span', { className: 'kb-dash-item-title' }, p.title),
		              el('span', { className: 'kb-dash-item-pct' }, p.done + '/' + p.total + ' · ' + p.percent + '%'),
		              el('div', { className: 'kb-dash-subbar' }, el('div', { className: 'kb-dash-subbar-fill', style: { width: p.percent + '%' } })),
		            )),
		          ) : empty('暂无带子议题的父议题'),
		        ),
		
		        // 项目总结（P2：Codex 式项目总结 → 可复制发送到 DSH 会话）
		        el('div', { className: 'kb-dash-card kb-dash-span2' },
		          el('div', { className: 'kb-dash-card-title' }, '项目总结'),
		          el('div', { className: 'kb-dash-summary' },
		            buildSummary().map((l, i) => el('div', { key: i, className: 'kb-dash-sum-line' }, l)),
		          ),
		          el('button', { className: 'kb-mini', style: { alignSelf: 'flex-start' }, onClick: () => { try { window.navigator.clipboard.writeText(buildSummary().join('\n')) } catch (e) {} } }, '复制摘要'),
		        ),
		      )
		    }
		
		    function OtherPanelView({ otherOpen, otherTab, setOtherTab, issues, openDetail, moveIssue, act, selWs }) {
	      // 授权类挂起在「解除阻塞」上不能复用 moveIssue（必被 retryGuard 拦下），改为就地调出确认面板。
	      const [authFor, setAuthFor] = React.useState(null)
	      const isAuthHold = (i) => !!(i && i.status === 'blocked' && i.failureControl && i.failureControl.action === 'hold' && i.failureControl.category === 'authorization')
		      if (!otherOpen) return null
		      const tabs = [
		        { key: 'blocked', label: '受阻', color: 'var(--kb-blocked)' },
		        { key: 'canceled', label: '取消', color: 'var(--kb-canceled)' },
		        { key: 'archived', label: '归档', color: 'var(--kb-text3)' },
		      ]
		      const list = issues.filter(i => otherTab === 'archived' ? i.archivedAt : (i.status === otherTab && !i.archivedAt))
		      return el('div', { className: 'kb-other' },
		        el('div', { className: 'kb-other-tabs' },
		          tabs.map(t => el('button', { key: t.key, className: 'kb-other-tab' + (otherTab === t.key ? ' active' : ''), onClick: () => setOtherTab(t.key) }, t.label + ' ' + issues.filter(i => t.key === 'archived' ? i.archivedAt : (i.status === t.key && !i.archivedAt)).length)),
		        ),
		        el('div', { className: 'kb-other-body' },
		          list.length === 0 ? el('div', { className: 'kb-empty' }, '暂无' + tabs.find(t => t.key === otherTab).label + '议题') : null,
		          list.map(i => el('div', { key: i.id, className: 'kb-other-item' },
		            el('div', { className: 'row' },
		              el('span', { className: 'kb-card-id' }, i.id),
		              el('span', { className: 't', onClick: () => openDetail(i.id), style: { cursor: 'pointer' } }, i.title),
		            ),
		            el('div', { className: 'act' },
		              otherTab === 'blocked' ? el('button', { className: 'kb-mini ok', onClick: () => { if (isAuthHold(i)) setAuthFor(authFor === i.id ? null : i.id); else moveIssue(i.id, 'todo') } }, isAuthHold(i) ? (authFor === i.id ? '收起授权确认' : '确认授权…') : '解除阻塞') : null,
		              otherTab === 'canceled' ? el('button', { className: 'kb-mini', onClick: () => moveIssue(i.id, 'backlog') }, '重开') : null,
		              otherTab === 'archived' ? el('button', { className: 'kb-mini', onClick: () => void act(() => call('archiveIssue', { workspaceId: selWs.id, id: i.id, version: i.version, archived: false })) }, '恢复') : null,
		              otherTab === 'archived' ? el('button', { className: 'kb-mini danger', onClick: () => void act(() => call('deleteIssue', { workspaceId: selWs.id, id: i.id, version: i.version })) }, '永久删除') : null,
		              el('button', { className: 'kb-mini', onClick: () => openDetail(i.id) }, '查看'),
		            ),
		            (isAuthHold(i) && authFor === i.id) ? el(AuthorizationGrantView, { key: i.id + '-grant', detail: i, selWs, act }) : null,
		          )),
		        ),
		      )
		    }
		
		    // ============ list view (P2) ============
		    const PRI_RANK = Object.fromEntries(PRIORITIES.map(p=>[p.key,9-p.key]))
		    const LIST_COLS = [
		      { key: 'id', label: 'ID', sortable: true },
		      { key: 'title', label: '标题', sortable: true },
		      { key: 'status', label: '状态', sortable: false },
		      { key: 'priority', label: '优先级', sortable: true },
		      { key: 'labels', label: '标签', sortable: false },
		      { key: 'dueDate', label: '截止日期', sortable: true },
		      { key: 'retries', label: '重试', sortable: false },
		      { key: 'updatedAt', label: '更新时间', sortable: true },
		    ]
		    const LIST_COL_LABEL = { id: 'ID', title: '标题', dueDate: '截止日期', priority: '优先级', updatedAt: '更新时间' }
		    const listFmtTime = (iso) => {
		      if (!iso) return '—'
		      const d = new Date(iso)
		      if (isNaN(d.getTime())) return String(iso).slice(0, 10)
		      const p = (n) => String(n).padStart(2, '0')
		      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
		    }
		
		    function ListView({ issues, state, openDetail, act, selWs, query, filter }) {
		      // 排序状态放组件内部；sort.key 为 null 表示不排序（保持 issues 传入顺序）
		      const [sort, setSort] = React.useState({ key: null, dir: 1 })
		      const today = new Date().toISOString().slice(0, 10)
		      const sortVal = (i) => {
		        switch (sort.key) {
		          case 'id': return i.id
		          case 'title': return (i.title || '').toLowerCase()
		          case 'dueDate': return i.dueDate || ''
		          case 'updatedAt': return i.updatedAt || ''
		          case 'priority': return PRI_RANK[priorityLevel(i.priority)]
		          default: return ''
		        }
		      }
		      const rows = sort.key ? issues.slice().sort((a, b) => {
		        const x = sortVal(a), y = sortVal(b)
		        if (x === y) return 0
		        if (x === null || x === undefined || x === '') return 1 // 空值恒排最后
		        if (y === null || y === undefined || y === '') return -1
		        return (x < y ? -1 : 1) * sort.dir
		      }) : issues
		      const onSort = (key) => setSort(s => s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 })
		
		      const headCells = LIST_COLS.map(c => el('th', {
		        key: c.key,
		        className: 'kb-list-th' + (c.sortable ? ' sortable' : '') + (sort.key === c.key ? (sort.dir === 1 ? ' sort-asc' : ' sort-desc') : ''),
		        onClick: c.sortable ? () => onSort(c.key) : undefined,
		      }, c.label))
		
		      const bodyRows = rows.map(i => {
		        const st = statusMeta(i.status)
		        const p = PRIORITIES.find(x => x.key === priorityLevel(i.priority)) || PRIORITIES[0]
		        const labels = i.labels || []
		        const overdue = !!i.dueDate && i.dueDate < today && i.status !== 'done' && i.status !== 'canceled'
		        return el('tr', { key: i.id, className: 'kb-list-row', title: i.title, onClick: () => openDetail(i.id) },
		          el('td', { className: 'kb-list-id' }, i.id),
		          el('td', null, el('div', { className: 'kb-list-title' }, i.title)),
		          el('td', null, el('span', { className: 'kb-chip2 kb-lbl', style: { color: st.color, background: st.color + '1a' } }, st.label)),
		          el('td', null, (i.priority !== undefined && i.priority !== null) ? el('span', { className: 'kb-chip2 ' + p.cls }, p.label) : '—'),
		          el('td', null, el('div', { className: 'kb-list-tags' },
		            labels.slice(0, 2).map(l => {
		              const lb = (state.labels || []).find(x => x.name === l)
		              return el('span', { key: l, className: 'kb-chip2 kb-lbl', style: lb ? { color: lb.color, background: lb.color + '1a' } : null }, l)
		            }),
		            labels.length > 2 ? el('span', { key: '+', className: 'kb-chip2 kb-lbl' }, '+' + (labels.length - 2)) : null,
		            labels.length === 0 ? '—' : null,
		          )),
		          el('td', { className: 'kb-list-mono' + (overdue ? ' kb-list-due overdue' : '') }, i.dueDate || '—'),
		          el('td', null, i.retries > 0 ? el('span', { className: 'kb-chip2 kb-lbl-fail' }, '重试×' + i.retries) : '—'),
		          el('td', { className: 'kb-list-mono' }, listFmtTime(i.updatedAt)),
		        )
		      })
		
		      return el('div', { className: 'kb-list' },
		        el('div', { className: 'kb-list-bar' },
		          '共 ', el('b', null, rows.length), ' 条',
		          sort.key
		            ? el('span', null, '· 按 ' + (LIST_COL_LABEL[sort.key] || sort.key) + (sort.dir === 1 ? ' 升序' : ' 降序') + '（再点表头切换）')
		            : el('span', null, '· 点击表头排序'),
		        ),
		        el('div', { className: 'kb-list-scroll' },
		          issues.length === 0
		            ? el('div', { className: 'kb-list-empty' },
		                (query || filter.status || filter.priority || filter.label) ? '当前筛选下无匹配议题' : '暂无议题')
		            : el('table', { className: 'kb-list-table' },
		                el('thead', null, el('tr', null, headCells)),
		                el('tbody', null, bodyRows),
		              ),
		        ),
		      )
		    }
		
		    function WorkspacePickerModalView({ wsPicker, wsGo, wsSelectFrom, closeWs }) {
		      const wsInputRef = React.useRef(null)
		      const wsGoFromInput = () => {
		        const v = wsInputRef.current ? wsInputRef.current.value : ''
		        if (v.trim()) wsGo(v.trim())
		      }
		      const wsSelectFromInput = () => {
		        const v = wsInputRef.current ? wsInputRef.current.value : ''
		        wsSelectFrom(v)
		      }
		      if (!wsPicker) return null
		      const listing = wsPicker.listing
		      return el('div', { className: 'kb-modal' },
		        el('div', { className: 'kb-modal-box kb-modal-wide', onClick: (e) => e.stopPropagation() },
		          el('div', { className: 'kb-modal-head' },
		            el('h3', null, '选择文件夹创建工作区'),
		            el('div', { className: 'kb-spacer' }),
		            el('button', { className: 'kb-btn kb-btn-ghost kb-btn-close', onClick: () => closeWs() }, '✕'),
		          ),
		          el('p', null, '浏览或输入文件夹路径，选择后注册为工作区。'),
		          listing ? el('div', { className: 'kb-crumbs' },
		            listing.crumbs.map((c, i) => el('span', { key: c.path, style: { display: 'contents' } },
		              i > 0 ? el('span', { key: 'sep' + i, className: 'kb-crumb-sep' }, '›') : null,
		              el('span', { key: c.path, className: 'kb-crumb' + (i === listing.crumbs.length - 1 ? ' cur' : ''), onClick: () => wsGo(c.path) },
		                i === 0 ? (c.name || 'Home') : c.name,
		              ),
		            )),
		          ) : null,
		          listing ? el('div', { className: 'kb-dir-list' },
		            listing.entries.filter(e => !e.hidden).map(e => el('div', { key: e.path, className: 'kb-dir-row', title: e.path, onClick: () => wsGo(e.path) },
		              el('span', { className: 'kb-dir-ico' }, '📁'),
		              el('span', { className: 'kb-dir-name' }, e.name),
		            )),
		            listing.entries.filter(e => !e.hidden).length === 0 ? el('div', { className: 'kb-empty' }, '空目录') : null,
		          ) : null,
		          el('div', { className: 'kb-field', style: { marginTop: 12 } },
		            el('label', null, '文件夹路径'),
		            el('input', {
		              ref: wsInputRef,
		              defaultValue: wsPicker.input || '',
		              placeholder: '/Users/you/Projects',
		              onKeyDown: (e) => { if (e.key === 'Enter') wsGoFromInput() },
		            }),
		          ),
		          wsPicker.err ? el('div', { className: 'kb-dir-err' }, wsPicker.err) : null,
		          el('div', { className: 'kb-modal-actions', style: { marginTop: 14 } },
		            el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => closeWs() }, '取消'),
		            el('button', { className: 'kb-btn kb-btn-primary', onClick: wsSelectFromInput }, '选择此目录'),
		          ),
		        ),
		      )
		    }
		
		    function AddIssueModalView({ showAdd, state, addStatus, setAddStatus, addPri, setAddPri, addLabels, setAddLabels, addDue, setAddDue, setAddTitle, setAddDesc, createIssue, closeAdd, addLabel }) {
		      const [newLabel, setNewLabel] = React.useState('')
		      const titleRef = React.useRef(null)
		      const descRef = React.useRef(null)
		      // IME-safe input: uncontrolled fields (React never rewrites value mid-composition)
		      const imeSafe = (setter) => (e) => {
		        if (e.nativeEvent && e.nativeEvent.isComposing) return
		        setter(e.target.value)
		      }
		      const submit = () => {
		        const title = titleRef.current ? titleRef.current.value : ''
		        const desc = descRef.current ? descRef.current.value : ''
		        void createIssue(addStatus, title, desc, addPri, addLabels, addDue)
		      }
		      React.useEffect(() => {
		        if (showAdd && titleRef.current) { try { titleRef.current.focus() } catch (e) {} }
		      }, [showAdd])
		      if (!showAdd) return null
		      return el('div', { className: 'kb-modal' },
		        el('div', { className: 'kb-modal-box kb-modal-wide', onClick: (e) => e.stopPropagation() },
		          el('div', { className: 'kb-modal-head' },
		            el('h3', null, '新建议题'),
		            el('div', { className: 'kb-spacer' }),
		            el('button', { className: 'kb-btn kb-btn-ghost kb-btn-close', onClick: () => closeAdd() }, '✕'),
		          ),
		          el('div', { className: 'kb-field' },
		            el('label', null, '标题'),
		            el('input', { ref: titleRef, defaultValue: '', placeholder: '议题标题', onInput: imeSafe(setAddTitle) }),
		          ),
		          el('div', { className: 'kb-field', style: { marginTop: 10 } },
		            el('label', null, '需求描述'),
		            el('textarea', { ref: descRef, defaultValue: '', placeholder: '需求描述（可选）', onInput: imeSafe(setAddDesc) }),
		          ),
		          el('div', { style: { display: 'flex', gap: 10, marginTop: 10 } },
		            el('div', { className: 'kb-field', style: { flex: 1 } },
		              el('label', null, '放入列'),
		              el('select', { value: addStatus, onChange: (e) => setAddStatus(e.target.value) },
		                STATUSES.filter(s => MAIN_COLS.includes(s.key)).map(s => el('option', { key: s.key, value: s.key }, s.label)),
		              ),
		            ),
		            el('div', { className: 'kb-field', style: { flex: 1 } },
		              el('label', null, '优先级'),
		              el('select', { value: addPri, onChange: (e) => setAddPri(Number(e.target.value)) },
		                PRIORITIES.map(p => el('option', { key: p.key, value: p.key }, p.label)),
		              ),
		            ),
		          ),
		          el('div', { style: { marginTop: 12 } },
		            el('h4', null, '标签'),
		            el('div', { className: 'kb-tagrow' },
		              (state ? state.labels : []).map(l => el('button', {
		                key: l.name,
		                className: 'kb-tagpick' + (addLabels.includes(l.name) ? ' on' : ''),
		                style: addLabels.includes(l.name) ? { color: l.color, borderColor: l.color } : null,
		                onClick: () => setAddLabels(prev => prev.includes(l.name) ? prev.filter(x => x !== l.name) : [...prev, l.name]),
		              }, l.name)),
		            ),
		            el('div', { style: { display: 'flex', gap: 6, marginTop: 6 } },
		              el('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '新建标签名', value: newLabel, onChange: (e) => setNewLabel(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') { const n = newLabel.trim(); if (n) { addLabel(n); setNewLabel('') } } } }),
		              el('button', { className: 'kb-mini', onClick: () => { const n = newLabel.trim(); if (n) { addLabel(n); setNewLabel('') } } }, '新建标签'),
		            ),
		          ),
		          el('div', { style: { display: 'flex', gap: 10, marginTop: 10 } },
		            el('div', { className: 'kb-field', style: { flex: 1 } },
		              el('label', null, '截止日期'),
		              el('input', { type: 'date', value: addDue, onChange: (e) => setAddDue(e.target.value) }),
		            ),
		          ),
		          el('div', { className: 'kb-modal-actions', style: { marginTop: 16 } },
		            el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => closeAdd() }, '取消'),
		            el('button', { className: 'kb-btn kb-btn-primary', onClick: submit }, '添加'),
		          ),
		        ),
		      )
		    }
		
		
		    // ============ 甘特图（P3，模块级组件） ============
		    function GanttView({ issues, state, openDetail }) {
		      const [unit, setUnit] = React.useState('day') // day | week | month
		      const [hideDone, setHideDone] = React.useState(false)
		      const DAY = 86400000
		      const todayISO = new Date().toISOString().slice(0, 10)
		      const parseDay = (s) => {
		        const p = String(s || '').split('-')
		        if (p.length !== 3) return null
		        const d = new Date(+p[0], +p[1] - 1, +p[2])
		        return isNaN(d.getTime()) ? null : Math.floor(d.getTime() / DAY)
		      }
		      const fmtDay = (n) => {
		        const d = new Date(n * DAY)
		        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
		      }
		      const items = issues
		        .filter(i => !i.archivedAt)
		        .filter(i => !(hideDone && i.status === 'done'))
		        .map(i => {
		          const start = parseDay((i.createdAt || '').slice(0, 10)) || parseDay(todayISO)
		          const end = parseDay(i.dueDate) || parseDay(todayISO) || start
		          return { ...i, start: Math.min(start, end), end: Math.max(start, end) }
		        })
		        .sort((a, b) => a.start - b.start || a.end - b.end)
		      if (!items.length) return el('div', { className: 'kb-list' }, el('div', { className: 'kb-list-empty' }, '暂无议题'))
		      const todayN = parseDay(todayISO)
		      const minD = Math.min(...items.map(i => i.start), todayN - 7)
		      const maxD = Math.max(...items.map(i => i.end), todayN + 30)
		      const span = maxD - minD + 1
		      const pct = (d) => ((d - minD) / span * 100)
		      // 刻度：日/周/月
		      const ticks = []
		      if (unit === 'day' && span > 60) {
		        for (let d = minD; d <= maxD; d += 7) ticks.push({ d, label: fmtDay(d).slice(5) })
		      } else if (unit === 'day') {
		        for (let d = minD; d <= maxD; d++) ticks.push({ d, label: fmtDay(d).slice(5) })
		      } else if (unit === 'week') {
		        for (let d = minD; d <= maxD; d += 7) ticks.push({ d, label: fmtDay(d).slice(5) })
		      } else {
		        for (let d = minD; d <= maxD;) {
		          const dt = new Date(d * DAY)
		          ticks.push({ d, label: dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') })
		          d = Math.floor(new Date(dt.getFullYear(), dt.getMonth() + 1, 1).getTime() / DAY)
		        }
		      }
		      const gridW = Math.max(640, span * (unit === 'month' ? 90 : unit === 'week' ? 42 : 14))
		      return el('div', { className: 'kb-gantt' },
		        el('div', { className: 'kb-gantt-bar' },
		          el('span', { className: 'kb-gantt-bar-title' }, '甘特图'),
		          el('select', { value: unit, onChange: (e) => setUnit(e.target.value) },
		            el('option', { value: 'day' }, '日'), el('option', { value: 'week' }, '周'), el('option', { value: 'month' }, '月'),
		          ),
		          el('label', { className: 'kb-switch', style: { marginLeft: 10 } },
		            el('input', { type: 'checkbox', checked: hideDone, onChange: (e) => setHideDone(e.target.checked) }),
		            el('span', { className: 'track' }),
		            '隐藏已完成',
		          ),
		          el('span', { className: 'kb-gantt-range' }, fmtDay(minD) + ' ~ ' + fmtDay(maxD)),
		        ),
		        el('div', { className: 'kb-gantt-scroll' },
		          el('div', { className: 'kb-gantt-grid', style: { width: gridW + 'px' } },
		            el('div', { className: 'kb-gantt-ticks' }, ticks.map(t => el('span', { key: t.d, className: 'kb-gantt-tick', style: { left: pct(t.d) + '%' } }, t.label))),
		            el('div', { className: 'kb-gantt-today', style: { left: pct(todayN) + '%' }, title: '今天 ' + todayISO }),
		            items.map(i => el('div', { key: i.id, className: 'kb-gantt-row', onClick: () => openDetail(i.id) },
		              el('div', { className: 'kb-gantt-label' },
		                el('span', { className: 'kb-card-id' }, i.id),
		                el('span', { className: 'kb-gantt-title' }, i.title),
		              ),
		              el('div', { className: 'kb-gantt-track' },
		                el('div', {
		                  className: 'kb-gantt-bar2 kb-gantt-' + i.status,
		                  title: i.title + '\n' + fmtDay(i.start) + ' ~ ' + fmtDay(i.end),
		                  style: { left: pct(i.start) + '%', width: Math.max(1.5, (i.end - i.start + 1) / span * 100) + '%' },
		                }),
		              ),
		            )),
		          ),
		        ),
		      )
		    }
		
		    // ============ 节点模式（P3，模块级组件） ============
		    // 把议题按生命周期映射到 DSH agent 能力节点：规划 / 开发 / API·集成 / 验收 / 结果
		    function NodesView({ issues, state, openDetail }) {
		      const NODES = [
		        { key: 'plan', label: '规划', icon: '🧭', desc: '待立项（backlog）', match: (i) => i.status === 'backlog' },
		        { key: 'dev', label: '开发', icon: '🛠️', desc: '待执行 + 执行中', match: (i) => i.status === 'todo' || i.status === 'in_progress' },
		        { key: 'api', label: 'API / 集成', icon: '🔌', desc: '受阻待疏通（blocked）', match: (i) => i.status === 'blocked' },
		        { key: 'accept', label: '验收', icon: '🔍', desc: '待验收（in_review）', match: (i) => i.status === 'in_review' },
		        { key: 'result', label: '结果', icon: '🏁', desc: '完成 / 取消', match: (i) => i.status === 'done' || i.status === 'canceled' },
		      ]
		      const live = issues.filter(i => !i.archivedAt)
		      return el('div', { className: 'kb-nodes' },
		        el('div', { className: 'kb-nodes-bar' },
		          el('span', { className: 'kb-nodes-bar-title' }, '节点模式'),
		          el('span', { className: 'kb-nodes-bar-sub' }, '议题按生命周期映射到 DSH agent 能力节点 · 点击卡片查看详情'),
		        ),
		        el('div', { className: 'kb-nodes-flow' },
		          NODES.map(n => {
		            const items = live.filter(n.match)
		            return el('div', { key: n.key, className: 'kb-node' },
		              el('div', { className: 'kb-node-head' },
		                el('span', { className: 'kb-node-icon' }, n.icon),
		                el('span', { className: 'kb-node-label' }, n.label),
		                el('span', { className: 'kb-count' }, items.length),
		              ),
		              el('div', { className: 'kb-node-desc' }, n.desc),
		              el('div', { className: 'kb-node-body' },
		                items.length === 0 ? el('div', { className: 'kb-empty' }, '暂无') : null,
		                items.map(i => {
		                  const st = statusMeta(i.status)
		                  const tags = (i.labels || []).slice(0, 2).map(l => el('span', { key: l, className: 'kb-chip2 kb-lbl', style: { fontSize: 9 } }, l))
		                  return el('div', { key: i.id, className: 'kb-node-item', onClick: () => openDetail(i.id), title: i.title },
		                    el('div', { className: 'kb-node-item-top' },
		                      el('span', { className: 'kb-card-id' }, i.id),
		                      el('span', { className: 'kb-dot', style: { background: st.color } }),
		                    ),
		                    el('div', { className: 'kb-node-item-title' }, i.title),
		                    tags.length ? el('div', { className: 'kb-node-item-tags' }, tags) : null,
		                  )
		                }),
		              ),
		            )
		          }),
		        ),
		      )
		    }
		
		    // ============ 标签管理页（P2 增量，模块级组件：Board 重渲染不会重挂载） ============
		    function LabelsView({ state, selWs, act, refresh }) {
		      const [newName, setNewName] = React.useState('')
		      const [newColor, setNewColor] = React.useState('#ff7236')
		      const [renaming, setRenaming] = React.useState(null) // 正在改名的标签名
		      const [renameValue, setRenameValue] = React.useState('')
		      const renameDone = React.useRef(false) // 防止 Enter 保存后 blur 重复提交
		      const [arm, setArm] = React.useState(null) // 删除二次确认
		      React.useEffect(() => {
		        if (!arm) return
		        const t = setTimeout(() => setArm(null), 3000)
		        return () => clearTimeout(t)
		      }, [arm])
		      const labels = (state && state.labels) || []
		      const issues = (state && state.issues) || []
		      const live = issues.filter(i => !i.archivedAt)
		      const countOf = (name) => live.filter(i => (i.labels || []).includes(name)).length
		      const updateLabel = (name, patch) => {
		        if (!selWs) return
		        void act(() => call('updateLabel', Object.assign({ workspaceId: selWs.id, name }, patch)))
		      }
		      const startRename = (name) => { renameDone.current = false; setRenaming(name); setRenameValue(name) }
		      const commitRename = (name) => {
		        if (renameDone.current) return
		        renameDone.current = true
		        const v = renameValue.trim()
		        setRenaming(null)
		        if (v && v !== name) updateLabel(name, { nextName: v })
		      }
		      const delLabel = (name) => {
		        if (!selWs) return
		        if (arm !== name) { setArm(name); return }
		        setArm(null)
		        void act(() => call('deleteLabel', { workspaceId: selWs.id, name }))
		      }
		      const addLabel = () => {
		        const n = newName.trim()
		        if (!n || !selWs) return
		        void act(() => call('addLabel', { workspaceId: selWs.id, name: n, color: newColor }))
		        setNewName('')
		      }
		      return el('div', { className: 'kb-lblmgr' },
		        !selWs ? el('div', { className: 'kb-banner' }, '⚠ 请先选择工作区后再管理标签') : null,
		        el('div', { className: 'kb-lblmgr-head' },
		          el('span', null, '标签管理'),
		          el('span', { className: 'kb-count' }, '共 ' + labels.length + ' 个'),
		        ),
		        el('div', { className: 'kb-lblmgr-addrow' },
		          el('input', { className: 'kb-input', placeholder: '新标签名称', value: newName, onChange: (e) => setNewName(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') addLabel() } }),
		          el('input', { type: 'color', className: 'kb-lblmgr-color', value: newColor, onChange: (e) => setNewColor(e.target.value), title: '新标签颜色' }),
		          el('button', { className: 'kb-mini primary', disabled: !selWs || !newName.trim(), onClick: addLabel }, '＋ 添加标签'),
		        ),
		        labels.length === 0 ? el('div', { className: 'kb-empty' }, '暂无标签，在上方输入名称创建') : null,
		        el('div', { className: 'kb-lblmgr-list' },
		          labels.map(l => {
		            const cnt = countOf(l.name)
		            const isArm = arm === l.name
		            return el('div', { key: l.name, className: 'kb-lblmgr-row' },
		              el('span', { className: 'kb-lblmgr-dot', style: { background: l.color } }),
		              renaming === l.name
		                ? el('input', {
		                    className: 'kb-input', style: { flex: 1 }, value: renameValue, autoFocus: true,
		                    onChange: (e) => setRenameValue(e.target.value),
		                    onKeyDown: (e) => { if (e.key === 'Enter') commitRename(l.name); if (e.key === 'Escape') setRenaming(null) },
		                    onBlur: () => commitRename(l.name),
		                  })
		                : el('span', { className: 'kb-lblmgr-name', title: l.name }, l.name),
		              el('span', { className: 'kb-lblmgr-count' }, cnt === 0 ? '未使用' : '使用 ' + cnt),
		              el('div', { className: 'kb-lblmgr-ops' },
		                el('input', {
		                  type: 'color', className: 'kb-lblmgr-color', defaultValue: l.color,
		                  key: 'c-' + l.name + '-' + l.color, title: '改色',
		                  onBlur: (e) => { if (e.target.value && e.target.value !== l.color) updateLabel(l.name, { color: e.target.value }) },
		                }),
		                renaming === l.name ? null : el('button', { className: 'kb-mini', onClick: () => startRename(l.name) }, '改名'),
		                el('button', { className: 'kb-mini danger' + (isArm ? ' kb-lblmgr-armed' : ''), onClick: () => delLabel(l.name) }, isArm ? '确认删除' : '删除'),
		              ),
		            )
		          }),
		        ),
		      )
		    }
		
		    function Board() {
		      const open = useOpen()
		      const offline = useConnOffline()
		      const [view, setView] = React.useState(null) // { workspaces, defaultWsId }
		      const [state, setState] = React.useState(null)
		      const [selWs, setSelWs] = React.useState(null) // workspace object
		      const [msg, setMsg] = React.useState('')
		      const [query, setQuery] = React.useState('')
		      const [filter, setFilter] = React.useState({ status: '', priority: '', label: '' })
		      const [showFilter, setShowFilter] = React.useState(false)
		      const [showAdd, setShowAdd] = React.useState(false)
		      const [addStatus, setAddStatus] = React.useState('backlog')
		      const [addTitle, setAddTitle] = React.useState('')
		      const [addDesc, setAddDesc] = React.useState('')
		      const [addPri, setAddPri] = React.useState(1)
		      const [addLabels, setAddLabels] = React.useState([])
		      const [addDue, setAddDue] = React.useState('')
		      const [wsPicker, setWsPicker] = React.useState(null)
		      const [detailId, setDetailId] = React.useState(null)
		      const [ctxMenu, setCtxMenu] = React.useState(null) // { id, x, y, sub }
		      const [otherTab, setOtherTab] = React.useState('blocked')
		      const [otherOpen, setOtherOpen] = React.useState(true)
		      const [confirmDel, setConfirmDel] = React.useState(null) // workspace object
		      const [dragOver, setDragOver] = React.useState('')
		      const [busy, setBusy] = React.useState(false)
		      const [topOff, setTopOff] = React.useState(0)
		      const [tab, setTab] = React.useState('board') // 视图切换：board | dashboard | list | labels
		      const [autoOpen, setAutoOpen] = React.useState(false)
		      const [modelCatalog, setModelCatalog] = React.useState(null)
		      const searchRef = React.useRef(null)
		
		      const refreshMeta = React.useCallback(async () => {
		        try {
		          const r = await call('getWorkspaces')
		          if (r && r.ok) {
		            setView(r)
		            if (!selWs || !r.workspaces.some(w => w.id === selWs.id)) {
		              const next = r.workspaces.find(w => w.id === store.selectedWsId) || r.workspaces.find(w => w.id === r.defaultWorkspaceId) || r.workspaces[0] || null
		              store.selectedWsId = next ? next.id : null
		              setSelWs(next || null)
		            } else {
		              const cur = r.workspaces.find(w => w.id === selWs.id)
		              if (cur) setSelWs(cur)
		            }
		          }
		        } catch (e) { setMsg('读取工作区失败: ' + String(e)) }
		      }, [selWs])
		
		      const refresh = React.useCallback(async () => {
		        const wsId = selWs ? selWs.id : (store.selectedWsId || null)
		        if (!wsId) return
		        try {
		          const r = await call('getState', { workspaceId: wsId })
		          if (r && r.ok) setState(r.state)
		          else if (r) setMsg(r.message || '读取失败')
		        } catch (e) { setMsg('读取失败: ' + String(e)) }
		      }, [selWs])
		
		      React.useEffect(() => {
		        if (open) {
		          void refreshMeta()
		          if (selWs) void refresh()
		        }
		        // eslint-disable-next-line react-hooks/exhaustive-deps
		      }, [open, selWs && selWs.id])
		
		      React.useEffect(() => {
		        if (!open || !timer) return
		        return timer.interval(() => { void refreshMeta(); if (store.selectedWsId) void refresh() }, 3000)
		        // eslint-disable-next-line react-hooks/exhaustive-deps
		      }, [open, timer, selWs && selWs.id])
		
		      // measure the session header (title bar + conversation/trajectory tabs) so the
		      // overlay starts below it instead of covering it
		      React.useEffect(() => {
		        if (!open) return
		        const measure = () => {
		          let h = 0
		          try {
		            // the header toggle lives inside the session <header>; the sidebar
		            // toggle does not, so scan all toggles and pick one inside a header
		            let header = null
		            const toggles = document.querySelectorAll('.kb-toggle')
		            for (const t of toggles) {
		              header = t.closest('header')
		              if (header) break
		            }
		            if (!header) header = document.querySelector('header')
		            if (header) h = Math.max(0, Math.round(header.getBoundingClientRect().bottom))
		          } catch (e) { h = 0 }
		          setTopOff(h)
		        }
		        measure()
		        window.addEventListener('resize', measure)
		        return () => window.removeEventListener('resize', measure)
		        // eslint-disable-next-line react-hooks/exhaustive-deps
		      }, [open])
		
		      // shortcuts
		      React.useEffect(() => {
		        if (!open) return
		        // IME composition guard: never intercept keys while the input method is composing
		        let composing = false
		        const onCompStart = () => { composing = true }
		        const onCompEnd = () => { composing = false }
		        document.addEventListener('compositionstart', onCompStart)
		        document.addEventListener('compositionend', onCompEnd)
		        const onKey = (e) => {
		          if (e.isComposing || composing) return
		          const t = e.target
		          const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')
		          if (typing) return
		          // strict shortcut matching: no modifier keys (Cmd/Ctrl/Alt) so copy/paste
		          // (⌘C/⌘F/⌘V…) never triggers board actions; also ignore key repeats
		          const mod = e.metaKey || e.ctrlKey || e.altKey
		          if (!mod && !e.repeat && e.key === '/') { e.preventDefault(); if (searchRef.current) searchRef.current.focus() }
		          else if (!mod && !e.repeat && e.key.toLowerCase() === 'c' && selWs) { e.preventDefault(); setShowAdd(true) }
		          else if (!mod && !e.repeat && e.key.toLowerCase() === 'f') { e.preventDefault(); setShowFilter(v => !v) }
		          else if (e.key === 'Escape') {
		            if (autoOpen) setAutoOpen(false)
		            else if (detailId) setDetailId(null)
		            else if (ctxMenu) setCtxMenu(null)
		            else if (showAdd) setShowAdd(false)
		            else if (confirmDel) setConfirmDel(null)
		            else setOpen(false)
		          } else if ((e.metaKey || e.ctrlKey) && e.key === 'Backspace') {
		            const id = detailId || (ctxMenu && ctxMenu.id)
		            if (id && selWs) { e.preventDefault(); void act(() => call('archiveIssue', { workspaceId: selWs.id, id, archived: true })).then(() => setDetailId(null)) }
		          }
		        }
		        window.addEventListener('keydown', onKey)
		        return () => {
		          window.removeEventListener('keydown', onKey)
		          document.removeEventListener('compositionstart', onCompStart)
		          document.removeEventListener('compositionend', onCompEnd)
		        }
		        // eslint-disable-next-line react-hooks/exhaustive-deps
		      }, [open, detailId, ctxMenu, showAdd, confirmDel, selWs])
		
		      if (!open) return null
		
		      const act = async (fn, optimistic) => {
		        setBusy(true)
		        try {
		          if (optimistic) optimistic()
		          const r = await fn()
		          if (r && r.ok) {
		            setMsg(r.message || '完成')
		            void refresh()
		          } else if (r && r.conflict) {
		            setMsg(r.message || '已在其他位置更新，已重新同步')
		            void refresh()
		          } else if (r) {
		            setMsg(r.message || '操作失败')
		            void refresh()
		          }
		        } catch (e) {
		          setMsg('操作失败: ' + String(e))
		          void refresh()
		        } finally { setBusy(false) }
		      }
		
		      const selectWorkspace = (ws) => {
		        store.selectedWsId = ws.id
		        setSelWs(ws)
		        setShowAdd(false)
		        setDetailId(null)
		        setState(null)
		        if (workspacesSvc) {
		          try { void workspacesSvc.connectWorkspace(ws.id).catch(() => {}) } catch (e) {}
		        }
		        void refresh()
		      }
		
		      const addWorkspace = async () => {
		        // web 部署使用 browse 能力（无 native 系统选择器）：打开内置目录浏览对话框
		        if (!workspacesSvc || !workspacesSvc.listDirectory) { setMsg('当前环境不支持目录浏览'); return }
		        setWsPicker({ cwd: null, listing: null, input: '', err: '' })
		        try {
		          const listing = await workspacesSvc.listDirectory()
		          setWsPicker({ cwd: listing.path, listing, input: listing.path, err: '' })
		        } catch (e) { setWsPicker(p => ({ ...p, err: '读取目录失败: ' + String(e) })) }
		      }
		
		      const wsGo = async (path) => {
		        if (!path) return
		        try {
		          const listing = await workspacesSvc.listDirectory(path)
		          setWsPicker(p => ({ ...p, cwd: listing.path, listing, input: listing.path, err: '' }))
		        } catch (e) { setWsPicker(p => ({ ...p, err: '读取目录失败: ' + String(e) })) }
		      }
		
		      const wsSelectFrom = async (path) => {
		        const p = (path || '').trim() || (wsPicker && wsPicker.cwd) || ''
		        if (!p) { setWsPicker(prev => ({ ...prev, err: '请输入或选择文件夹路径' })); return }
		        try {
		          const r = await call('createWorkspace', { path: p })
		          if (r && r.ok) {
		            setWsPicker(null)
		            setMsg(r.message)
		            await refreshMeta()
		            if (r.workspace) selectWorkspace(r.workspace)
		          } else setWsPicker(prev => ({ ...prev, err: (r && r.message) || '创建工作区失败' }))
		        } catch (e) { setWsPicker(prev => ({ ...prev, err: '创建工作区失败: ' + String(e) })) }
		      }
		
		      const wsSelect = (path) => wsSelectFrom(path || (wsPicker && wsPicker.cwd) || '')
		
		      const delWorkspace = async () => {
		        if (!confirmDel) return
		        const ws = confirmDel
		        setConfirmDel(null)
		        const r = await call('deleteWorkspace', { id: ws.id })
		        setMsg((r && r.message) || '操作完成')
		        await refreshMeta()
		        if (store.selectedWsId === ws.id) { store.selectedWsId = null; setSelWs(null); setState(null) }
		      }
		
		      const createIssue = async (status, title, desc, pri, labels, due) => {
		        if (!selWs) { setMsg('请先选择工作区'); return }
		        if (!title.trim()) { setMsg('请填写标题'); return }
		        const r = await call('createIssue', { workspaceId: selWs.id, title, description: desc, priority: pri, labels: labels || [], dueDate: due || null })
		        if (r && r.ok) { setMsg(r.message); setShowAdd(false); setAddTitle(''); setAddDesc(''); setAddPri(1); setAddLabels([]); setAddDue(''); void refresh() }
		        else setMsg((r && r.message) || '创建失败')
		      }
		
		      const addLabel = async (name) => {
		        const n = (name || '').trim()
		        if (!n || !selWs) return
		        const r = await call('addLabel', { workspaceId: selWs.id, name: n })
		        setMsg((r && r.message) || '操作完成')
		        void refresh()
		      }
		
		      const deleteLabel = async (name) => {
		        const n = (name || '').trim()
		        if (!n || !selWs) return
		        const r = await call('deleteLabel', { workspaceId: selWs.id, name: n })
		        setMsg((r && r.message) || '操作完成')
		        void refresh()
		      }
		
		      const openAutoPanel = async () => {
		        const next = !autoOpen
		        setAutoOpen(next)
		        if (next && !modelCatalog) {
		          try {
		            const r = await call('getModels')
		            if (r && r.ok) setModelCatalog(r)
		          } catch (e) { setMsg('读取模型列表失败: ' + String(e)) }
		        }
		      }
		
		      const updateAutoExec = async (patch) => {
		        if (!selWs) return
		        const r = await call('setAutoExec', { workspaceId: selWs.id, patch })
		        if (r && r.ok) { setMsg(r.message); void refresh() }
		        else setMsg((r && r.message) || '更新自动化设置失败')
		      }
		
		      const moveIssue = (id, to, note) => {
		        const optimistic = () => {
		          setState(s => s ? { ...s, issues: s.issues.map(i => i.id === id ? { ...i, status: to } : i) } : s)
		        }
		        void act(() => call('moveIssue', { workspaceId: selWs.id, id, to, note }), optimistic)
		      }
		
		      const statusLabel = (s) => statusMeta(s).label
		      // 完整议题列表（含归档，供「归档」面板与详情查看）；各列/搜索用 visible 排除归档
		      const issues = (state ? state.issues : [])
		      const visible = issues.filter(i => {
		        if (i.archivedAt) return false
		        if (filter.status && i.status !== filter.status) return false
		        if (filter.priority && priorityLevel(i.priority) !== Number(filter.priority)) return false
		        if (filter.label && !(i.labels || []).includes(filter.label)) return false
		        if (query && !(i.title + ' ' + (i.description || '') + ' ' + i.id).toLowerCase().includes(query.toLowerCase())) return false
		        return true
		      })
		      const byCol = (key) => visible.filter(i => i.status === key)
		      const issueById = (id) => issues.find(i => i.id === id)
		      const detail = detailId ? issueById(detailId) : null
		      const runningBatches = [...new Set(issues.filter(i => i.run && i.run.status === 'running').map(i => i.run.batchId).filter(Boolean))]
		
		      function Card({ issue }) {
		        const st = statusMeta(issue.status)
		        const labels = issue.labels || []
		        const tags = []
		        if (issue.priority !== undefined && issue.priority !== null) {
		          const p = PRIORITIES.find(x => x.key === priorityLevel(issue.priority))
		          tags.push(el('span', { className: 'kb-chip2 ' + (p ? p.cls : 'kb-pri-none') }, (p ? p.label : issue.priority)))
		        }
		        labels.slice(0, 2).forEach(l => {
		          const lb = (state.labels || []).find(x => x.name === l)
		          tags.push(el('span', { className: 'kb-chip2 kb-lbl', style: lb ? { color: lb.color, background: lb.color + '1a' } : null }, l))
		        })
		        if (labels.length > 2) tags.push(el('span', { className: 'kb-chip2 kb-lbl' }, '+' + (labels.length - 2)))
		        if (issue.dueDate) tags.push(el('span', { className: 'kb-chip2 kb-pri-low' }, '📅 ' + issue.dueDate))
		        if (issue.assignee) tags.push(el('span', { className: 'kb-chip2 kb-pri-none' }, '👤 ' + issue.assignee))
		        if (issue.retries > 0) tags.push(el('span', { className: 'kb-chip2 kb-lbl-fail' }, '重试×' + issue.retries))
		        if ((issue.blockedBy || []).length) tags.push(el('span', { className: 'kb-chip2 kb-lbl-fail' }, '被阻塞'))
		        if (issue.parentId) tags.push(el('span', { className: 'kb-chip2 kb-lbl' }, '子议题'))
		        if ((issue.children || []).length) tags.push(el('span', { className: 'kb-chip2 kb-lbl' }, '子议题×' + issue.children.length))
		        if (issue.run && issue.run.status === 'running') tags.push(el('span', { className: 'kb-chip2 kb-lbl-s' }, '● 运行中'))
		
		        const batch = state.batches.find(b => b.id === (issue.run && issue.run.batchId))
		        const total = batch ? batch.issueIds.length : 0
		        const idx = batch ? batch.issueIds.indexOf(issue.id) : -1
		
		        return el('div', {
		          className: 'kb-card' + (issue.run && issue.run.status === 'running' ? ' dragging' : ''),
		          style: { '--kb-card-c': st.color },
		          draggable: true,
		          onDragStart: (e) => { e.dataTransfer.setData('text/kanban-id', issue.id); e.dataTransfer.effectAllowed = 'move' },
		          onClick: () => setDetailId(issue.id),
		          onContextMenu: (e) => {
		            e.preventDefault(); e.stopPropagation()
		            setCtxMenu({ id: issue.id, x: Math.min(e.clientX, window.innerWidth - 210), y: Math.min(e.clientY, window.innerHeight - 320), sub: null })
		          },
		        },
		          el('div', { className: 'kb-card-top' },
		            el('span', { className: 'kb-card-id' }, issue.id),
		            issue.unread ? el('span', { className: 'kb-unread', title: '有新的活动' }) : null,
		            issue.status === 'in_review'
		              ? el('button', { className: 'kb-donebtn', onClick: (e) => { e.stopPropagation(); void act(() => call('accept', { workspaceId: selWs.id, id: issue.id, pass: true, report: '' })) } }, '✓ 完成')
		              : null,
		          ),
		          el('div', { className: 'kb-card-title' }, issue.title),
		          el('div', { className: 'kb-card-meta' }, tags),
		          total > 0 ? el('div', { className: 'kb-progress', title: '批次 ' + (issue.run.batchId) },
		            Array.from({ length: total }, (_, i) => el('span', { key: i, className: 'seg' + (i === idx ? ' cur' : i < idx ? ' on' : '') }))
		          ) : null,
		          (issue.children || []).length > 0 ? (() => {
		            const kids = issues.filter(c => (issue.children || []).includes(c.id))
		            const doneN = kids.filter(c => c.status === 'done').length
		            return el('div', { className: 'kb-subprogress' },
		              el('div', { className: 'bar' }, el('div', { className: 'fill', style: { width: (doneN / kids.length * 100) + '%' } })),
		            )
		          })() : null,
		        )
		      }
		
		      function ContextMenu() {
		        if (!ctxMenu) return null
		        const issue = issueById(ctxMenu.id)
		        if (!issue) return null
		        const sub = ctxMenu.sub
		        const items = []
		        const menu = (children) => el('div', { className: 'kb-ctxmenu', style: { left: ctxMenu.x, top: ctxMenu.y }, onClick: (e) => e.stopPropagation(), onContextMenu: (e) => { e.preventDefault(); e.stopPropagation() } }, children)
		
		        if (sub === 'status') {
		          return menu(STATUSES.map(s => el('div', { key: s.key, className: 'item' + (issue.status === s.key ? ' active' : ''), onClick: () => { moveIssue(issue.id, s.key); setCtxMenu(null) } },
		            el('span', { style: { width: 9, height: 9, borderRadius: 3, background: s.color } }),
		            s.label,
		            s.key === issue.status ? el('span', { className: 'k' }, '✓') : null,
		          )))
		        }
		        if (sub === 'priority') {
		          return menu(PRIORITIES.map(p => el('div', { key: p.key, className: 'item' + (priorityLevel(issue.priority) === p.key ? ' active' : ''), onClick: () => { void act(() => call('updateIssue', { workspaceId: selWs.id, id: issue.id, version: issue.version, patch: { priority: p.key } })); setCtxMenu(null) } }, p.label)))
		        }
		        if (sub === 'labels') {
		          const cur = issue.labels || []
		          return menu((state.labels || []).map(l => el('div', { key: l.name, className: 'item' + (cur.includes(l.name) ? ' active' : ''), onClick: () => {
		            const next = cur.includes(l.name) ? cur.filter(x => x !== l.name) : [...cur, l.name]
		            void act(() => call('updateIssue', { workspaceId: selWs.id, id: issue.id, version: issue.version, patch: { labels: next } }))
		            setCtxMenu(null)
		          } }, el('span', { style: { width: 9, height: 9, borderRadius: 3, background: l.color } }), l.name)))
		        }
		
		        items.push(
		          el('div', { key: 'status', className: 'kb-ctxsub' },
		            el('div', { className: 'item', onClick: () => setCtxMenu({ ...ctxMenu, sub: 'status' }) }, '状态', el('span', { className: 'k' }, 'S')),
		            ctxMenu.sub === 'status' ? el('div', { className: 'fly' }, STATUSES.map(s => el('div', { key: s.key, className: 'item', onClick: () => { moveIssue(issue.id, s.key); setCtxMenu(null) } }, s.label))) : null,
		          ),
		          el('div', { key: 'pri', className: 'item', onClick: () => setCtxMenu({ ...ctxMenu, sub: 'priority' }) }, '优先级', el('span', { className: 'k' }, 'P')),
		          el('div', { key: 'lbl', className: 'item', onClick: () => setCtxMenu({ ...ctxMenu, sub: 'labels' }) }, '标签', el('span', { className: 'k' }, 'L')),
		          el('div', { key: 'sep1', className: 'sep' }),
		          el('div', { key: 'edit', className: 'item', onClick: () => { setDetailId(issue.id); setCtxMenu(null) } }, '编辑议题', el('span', { className: 'k' }, '↵')),
		          el('div', { key: 'dup', className: 'item', onClick: () => { void act(() => call('createIssue', { workspaceId: selWs.id, title: issue.title + '（副本）', description: issue.description, priority: priorityLevel(issue.priority), labels: issue.labels })); setCtxMenu(null) } }, '创建副本'),
		          el('div', { key: 'sep2', className: 'sep' }),
		          el('div', { key: 'copyid', className: 'item', onClick: () => { try { window.navigator.clipboard.writeText(issue.id) } catch (e) {} setCtxMenu(null) } }, '复制议题 ID'),
		          el('div', { key: 'copyt', className: 'item', onClick: () => { try { window.navigator.clipboard.writeText(issue.title) } catch (e) {} setCtxMenu(null) } }, '复制标题'),
		          el('div', { key: 'copymd', className: 'item', onClick: () => { try { window.navigator.clipboard.writeText('[' + issue.id + '] ' + issue.title + '\n' + (issue.description || '')) } catch (e) {} setCtxMenu(null) } }, '复制 Markdown'),
		          el('div', { key: 'sep3', className: 'sep' }),
		          el('div', { key: 'open', className: 'item', onClick: () => {
		            if (issue.run && issue.run.subagentId && sessionsSvc) { try { sessionsSvc.open(issue.run.subagentId) } catch (e) {} }
		            else if (workspacesSvc && selWs) { try { void workspacesSvc.connectWorkspace(selWs.id) } catch (e) {} }
		            setCtxMenu(null); setOpen(false)
		          } }, '在对话中打开'),
		          el('div', { key: 'arch', className: 'item danger', onClick: () => { void act(() => call('archiveIssue', { workspaceId: selWs.id, id: issue.id, version: issue.version, archived: true })); setCtxMenu(null) } }, '归档议题', el('span', { className: 'k' }, '⌘⌫')),
		        )
		        return menu(items)
		      }
		
		      function Detail() {
		        if (!detail) return null
		        const [title, setTitle] = React.useState(detail.title)
		        const [desc, setDesc] = React.useState(detail.description || '')
		        const [pri, setPri] = React.useState(priorityLevel(detail.priority))
		        const [labels, setLabels] = React.useState(detail.labels || [])
		        const [due, setDue] = React.useState(detail.dueDate || '')
		        const [assignee, setAssignee] = React.useState(detail.assignee || '')
		        const [parts, setParts] = React.useState((detail.participants || []).join(', '))
		        const [relId, setRelId] = React.useState('')
		        const [comment, setComment] = React.useState('')
		        const savePatch = (patch) => {
		          void act(() => call('updateIssue', { workspaceId: selWs.id, id: detail.id, version: detail.version, patch })).then(() => {
		            void call('updateIssue', { workspaceId: selWs.id, id: detail.id, patch: { unread: false } }).catch(() => {})
		          })
		        }
		        return el('div', { className: 'kb-modal' },
		          el('div', { className: 'kb-modal-box kb-edit-box', onClick: (e) => e.stopPropagation() },
		            el('div', { className: 'kb-modal-head' },
		              el('h3', null, '编辑议题'),
		              el('span', { className: 'kb-card-id' }, detail.id),
		              el('span', { className: 'kb-chip2 kb-lbl' }, statusLabel(detail.status)),
		              el('div', { className: 'kb-spacer' }),
		              detail.archivedAt ? null : el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => { void act(() => call('archiveIssue', { workspaceId: selWs.id, id: detail.id, version: detail.version, archived: true })); setDetailId(null) } }, '归档'),
		              el('button', { className: 'kb-btn kb-btn-ghost kb-btn-close', onClick: () => setDetailId(null) }, '✕'),
		            ),
		            el('div', { className: 'kb-edit-body' },
		            el('div', { className: 'kb-field' },
		              el('label', null, '标题'),
		              el('input', { value: title, onChange: (e) => setTitle(e.target.value), onBlur: () => { if (title.trim() && title.trim() !== detail.title) savePatch({ title }) } }),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '描述'),
		              el('textarea', { value: desc, onChange: (e) => setDesc(e.target.value), onBlur: () => { if (desc !== (detail.description || '')) savePatch({ description: desc }) } }),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '优先级'),
		              el('select', { value: pri, onChange: (e) => { setPri(Number(e.target.value)); savePatch({ priority: Number(e.target.value) }) } },
		                PRIORITIES.map(p => el('option', { key: p.key, value: p.key }, p.label)),
		              ),
		            ),
		            el('div', null,
		              el('h4', null, '标签'),
		              el('div', { className: 'kb-tagrow' },
		                (state.labels || []).map(l => el('button', { key: l.name, className: 'kb-tagpick' + (labels.includes(l.name) ? ' on' : ''), style: labels.includes(l.name) ? { color: l.color, borderColor: l.color } : null, onClick: () => {
		                  const next = labels.includes(l.name) ? labels.filter(x => x !== l.name) : [...labels, l.name]
		                  setLabels(next)
		                  savePatch({ labels: next })
		                } }, l.name)),
		              ),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '截止日期'),
		              el('input', { type: 'date', value: due, onChange: (e) => { setDue(e.target.value); savePatch({ dueDate: e.target.value || null }) } }),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '负责人'),
		              el('input', { value: assignee, placeholder: 'agent:executor 或 用户名', onChange: (e) => setAssignee(e.target.value), onBlur: () => { if (assignee !== (detail.assignee || '')) savePatch({ assignee: assignee || null }) } }),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '参与人（逗号分隔）'),
		              el('input', { value: parts, onChange: (e) => setParts(e.target.value), onBlur: () => { const arr = parts.split(',').map(x => x.trim()).filter(Boolean); if (arr.join(',') !== (detail.participants || []).join(',')) savePatch({ participants: arr }) } }),
		            ),
		            (detail.children && detail.children.length > 0) ? el('div', null,
		              el('h4', null, '子议题进度 ' + issues.filter(c => detail.children.includes(c.id)).filter(c => c.status === 'done').length + '/' + detail.children.length),
		              el('div', { className: 'kb-tagrow' }, detail.children.map(cid => { const c = issueById(cid); return c ? el('span', { key: cid, className: 'kb-chip2 ' + (c.status === 'done' ? 'kb-lbl-ok' : 'kb-lbl'), onClick: () => setDetailId(cid), style: { cursor: 'pointer' } }, c.title) : null })),
		            ) : null,
		            (detail.blockedBy || []).length > 0 ? el('div', null,
		              el('h4', null, '被阻塞于'),
		              el('div', { className: 'kb-tagrow' }, detail.blockedBy.map(bid => { const b = issueById(bid); return el('span', { key: bid, className: 'kb-chip2 kb-lbl-fail' }, b ? b.title : bid) })),
		            ) : null,
		            el('div', null,
		              el('h4', null, '关联议题'),
		              el('div', { className: 'kb-tagrow' }, (detail.related || []).map(rid => { const r = issueById(rid); return el('span', { key: rid, className: 'kb-chip2 kb-lbl', style: { cursor: 'pointer' }, onClick: () => setDetailId(rid) }, (r ? r.title : rid) + ' ✕') })),
		              el('div', { style: { display: 'flex', gap: 6, marginTop: 6 } },
		                el('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '输入议题 id 添加关联', value: relId, onChange: (e) => setRelId(e.target.value) }),
		                el('button', { className: 'kb-mini', onClick: () => { const id = relId.trim(); if (!id) return; savePatch({ related: [...(detail.related || []), id] }); setRelId('') } }, '添加'),
		              ),
		            ),
		            el('div', null,
		              el('h4', null, '评论'),
		              (detail.comments || []).map((c, i) => el('div', { key: i, className: 'kb-comment' },
		                el('span', { className: 'who' }, c.who), el('span', { className: 'when' }, fmtWhen(c.at)), el('div', null, c.text),
		              )),
		              el('div', { style: { display: 'flex', gap: 6, marginTop: 8 } },
		                el('input', { className: 'kb-input', style: { flex: 1 }, placeholder: '写评论…', value: comment, onChange: (e) => setComment(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') { const t = comment.trim(); if (t) { void act(() => call('addComment', { workspaceId: selWs.id, id: detail.id, text: t })); setComment('') } } } }),
		                el('button', { className: 'kb-mini primary', onClick: () => { const t = comment.trim(); if (t) { void act(() => call('addComment', { workspaceId: selWs.id, id: detail.id, text: t })); setComment('') } } }, '发送'),
		              ),
		            ),
		            el('div', null,
		              el('h4', null, '活动流'),
		              el('div', { className: 'kb-activity' },
		                (detail.activity || []).slice().reverse().map((a, i) => el('div', { key: i, className: 'kb-act' },
		                  a.kind === 'status' ? (a.by + ' 将状态从「' + statusLabel(a.from) + '」移至「' + statusLabel(a.to) + '」') : a.kind === 'create' ? '创建议题' : a.kind === 'archive' ? (a.to === 'archived' ? '已归档' : '已恢复') : '更新',
		                  el('span', { className: 'at' }, fmtWhen(a.at)),
		                )),
		              ),
		            ),
		            detail.archivedAt ? el('div', { className: 'kb-field' },
		              el('button', { className: 'kb-mini danger', onClick: () => { void act(() => call('deleteIssue', { workspaceId: selWs.id, id: detail.id, version: detail.version })); setDetailId(null) } }, '永久删除'),
		            ) : null,
		            el('div', { className: 'kb-modal-actions', style: { marginTop: 12 } },
		              el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => setDetailId(null) }, '取消'),
		            ),
		          ),
		          ),
		        )
		      }
		
		      function WorkspacePickerModal() {
		        const wsInputRef = React.useRef(null)
		        const wsGoFromInput = () => {
		          const v = wsInputRef.current ? wsInputRef.current.value : ''
		          if (v.trim()) wsGo(v.trim())
		        }
		        const wsSelectFromInput = () => {
		          const v = wsInputRef.current ? wsInputRef.current.value : ''
		          wsSelectFrom(v)
		        }
		        if (!wsPicker) return null
		        const listing = wsPicker.listing
		        return el('div', { className: 'kb-modal', onClick: () => setWsPicker(null) },
		          el('div', { className: 'kb-modal-box kb-modal-wide', onClick: (e) => e.stopPropagation() },
		            el('h3', null, '选择文件夹创建工作区'),
		            el('p', null, '浏览或输入文件夹路径，选择后注册为工作区。'),
		            listing ? el('div', { className: 'kb-crumbs' },
		              listing.crumbs.map((c, i) => el('span', { key: c.path, style: { display: 'contents' } },
		                i > 0 ? el('span', { key: 'sep' + i, className: 'kb-crumb-sep' }, '›') : null,
		                el('span', { key: c.path, className: 'kb-crumb' + (i === listing.crumbs.length - 1 ? ' cur' : ''), onClick: () => wsGo(c.path) },
		                  i === 0 ? (c.name || 'Home') : c.name,
		                ),
		              )),
		            ) : null,
		            listing ? el('div', { className: 'kb-dir-list' },
		              listing.entries.filter(e => !e.hidden).map(e => el('div', { key: e.path, className: 'kb-dir-row', title: e.path, onClick: () => wsGo(e.path) },
		                el('span', { className: 'kb-dir-ico' }, '📁'),
		                el('span', { className: 'kb-dir-name' }, e.name),
		              )),
		              listing.entries.filter(e => !e.hidden).length === 0 ? el('div', { className: 'kb-empty' }, '空目录') : null,
		            ) : null,
		            el('div', { className: 'kb-field', style: { marginTop: 12 } },
		              el('label', null, '文件夹路径'),
		              el('input', {
		                ref: wsInputRef,
		                defaultValue: wsPicker.input || '',
		                placeholder: '/Users/you/Projects',
		                onKeyDown: (e) => { if (e.key === 'Enter') wsGoFromInput() },
		              }),
		            ),
		            wsPicker.err ? el('div', { className: 'kb-dir-err' }, wsPicker.err) : null,
		            el('div', { className: 'kb-modal-actions', style: { marginTop: 14 } },
		              el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => setWsPicker(null) }, '取消'),
		              el('button', { className: 'kb-btn kb-btn-primary', onClick: wsSelectFromInput }, '选择此目录'),
		            ),
		          ),
		        )
		      }
		
		      function AddIssueModal() {
		        const titleRef = React.useRef(null)
		        const descRef = React.useRef(null)
		        const assigneeRef = React.useRef(null)
		        const partsRef = React.useRef(null)
		        // IME-safe input: uncontrolled fields (React never rewrites value mid-composition)
		        const imeSafe = (setter) => (e) => {
		          if (e.nativeEvent && e.nativeEvent.isComposing) return
		          setter(e.target.value)
		        }
		        const submit = () => {
		          const title = titleRef.current ? titleRef.current.value : ''
		          const desc = descRef.current ? descRef.current.value : ''
		          const assignee = assigneeRef.current ? assigneeRef.current.value : ''
		          const parts = partsRef.current ? partsRef.current.value : ''
		          void createIssue(addStatus, title, desc, addPri, addLabels, addDue, assignee, parts)
		        }
		        React.useEffect(() => {
		          if (showAdd && titleRef.current) { try { titleRef.current.focus() } catch (e) {} }
		        }, [showAdd])
		        if (!showAdd) return null
		        return el('div', { className: 'kb-modal' },
		          el('div', { className: 'kb-modal-box kb-modal-wide', onClick: (e) => e.stopPropagation() },
		            el('div', { className: 'kb-modal-head' },
		              el('h3', null, '新建议题'),
		              el('div', { className: 'kb-spacer' }),
		              el('button', { className: 'kb-btn kb-btn-ghost kb-btn-close', onClick: () => setShowAdd(false) }, '✕'),
		            ),
		            el('div', { className: 'kb-field' },
		              el('label', null, '标题'),
		              el('input', { ref: titleRef, defaultValue: '', placeholder: '议题标题', onInput: imeSafe(setAddTitle) }),
		            ),
		            el('div', { className: 'kb-field', style: { marginTop: 10 } },
		              el('label', null, '需求描述'),
		              el('textarea', { ref: descRef, defaultValue: '', placeholder: '需求描述（可选）', onInput: imeSafe(setAddDesc) }),
		            ),
		            el('div', { style: { display: 'flex', gap: 10, marginTop: 10 } },
		              el('div', { className: 'kb-field', style: { flex: 1 } },
		                el('label', null, '放入列'),
		                el('select', { value: addStatus, onChange: (e) => setAddStatus(e.target.value) },
		                  STATUSES.filter(s => MAIN_COLS.includes(s.key)).map(s => el('option', { key: s.key, value: s.key }, s.label)),
		                ),
		              ),
		              el('div', { className: 'kb-field', style: { flex: 1 } },
		                el('label', null, '优先级'),
		                el('select', { value: addPri, onChange: (e) => setAddPri(Number(e.target.value)) },
		                  PRIORITIES.map(p => el('option', { key: p.key, value: p.key }, p.label)),
		                ),
		              ),
		            ),
		            el('div', { style: { marginTop: 12 } },
		              el('h4', null, '标签'),
		              el('div', { className: 'kb-tagrow' },
		                (state ? state.labels : []).map(l => el('button', {
		                  key: l.name,
		                  className: 'kb-tagpick' + (addLabels.includes(l.name) ? ' on' : ''),
		                  style: addLabels.includes(l.name) ? { color: l.color, borderColor: l.color } : null,
		                  onClick: () => setAddLabels(prev => prev.includes(l.name) ? prev.filter(x => x !== l.name) : [...prev, l.name]),
		                }, l.name)),
		              ),
		            ),
		            el('div', { style: { display: 'flex', gap: 10, marginTop: 10 } },
		              el('div', { className: 'kb-field', style: { flex: 1 } },
		                el('label', null, '截止日期'),
		                el('input', { type: 'date', value: addDue, onChange: (e) => setAddDue(e.target.value) }),
		              ),
		              el('div', { className: 'kb-field', style: { flex: 1 } },
		                el('label', null, '负责人'),
		                el('input', { ref: assigneeRef, defaultValue: '', placeholder: 'agent:executor 或 用户名', onInput: imeSafe(setAddAssignee) }),
		              ),
		            ),
		            el('div', { className: 'kb-field', style: { marginTop: 10 } },
		              el('label', null, '参与人（逗号分隔）'),
		              el('input', { ref: partsRef, defaultValue: '', placeholder: 'user:me, user:you', onInput: imeSafe(setAddParts) }),
		            ),
		            el('div', { className: 'kb-modal-actions', style: { marginTop: 16 } },
		              el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => setShowAdd(false) }, '取消'),
		              el('button', { className: 'kb-btn kb-btn-primary', onClick: submit }, '添加'),
		            ),
		          ),
		        )
		      }
		
		      function OtherPanel() {
		        if (!otherOpen) return null
		        const tabs = [
		          { key: 'blocked', label: '受阻', color: 'var(--kb-blocked)' },
		          { key: 'canceled', label: '取消', color: 'var(--kb-canceled)' },
		          { key: 'archived', label: '归档', color: 'var(--kb-text3)' },
		        ]
		        const list = issues.filter(i => i.status === otherTab || (otherTab === 'archived' && i.archivedAt))
		        return el('div', { className: 'kb-other' },
		          el('div', { className: 'kb-other-tabs' },
		            tabs.map(t => el('button', { key: t.key, className: 'kb-other-tab' + (otherTab === t.key ? ' active' : ''), onClick: () => setOtherTab(t.key) }, t.label + ' ' + issues.filter(i => i.status === t.key || (t.key === 'archived' && i.archivedAt)).length)),
		          ),
		          el('div', { className: 'kb-other-body' },
		            list.length === 0 ? el('div', { className: 'kb-empty' }, '暂无' + tabs.find(t => t.key === otherTab).label + '议题') : null,
		            list.map(i => el('div', { key: i.id, className: 'kb-other-item' },
		              el('div', { className: 'row' },
		                el('span', { className: 'kb-card-id' }, i.id),
		                el('span', { className: 't', onClick: () => setDetailId(i.id), style: { cursor: 'pointer' } }, i.title),
		              ),
		              el('div', { className: 'act' },
		                otherTab === 'blocked' ? el('button', { className: 'kb-mini ok', onClick: () => moveIssue(i.id, 'todo') }, '解除阻塞') : null,
		                otherTab === 'canceled' ? el('button', { className: 'kb-mini', onClick: () => moveIssue(i.id, 'backlog') }, '重开') : null,
		                otherTab === 'archived' ? el('button', { className: 'kb-mini', onClick: () => void act(() => call('archiveIssue', { workspaceId: selWs.id, id: i.id, version: i.version, archived: false })) }, '恢复') : null,
		                otherTab === 'archived' ? el('button', { className: 'kb-mini danger', onClick: () => void act(() => call('deleteIssue', { workspaceId: selWs.id, id: i.id, version: i.version })) }, '永久删除') : null,
		                el('button', { className: 'kb-mini', onClick: () => setDetailId(i.id) }, '查看'),
		              ),
		            )),
		          ),
		        )
		      }
		
		      const wsTitle = selWs ? selWs.title : '未选择'
		      return el('div', {
		        className: 'kb-overlay', style: { '--kb-top': topOff + 'px' },
		        onClick: (e) => {
		          if (e.target !== e.currentTarget) return
		          // with a dialog open (add/edit/workspace picker/delete confirm), clicking
		          // the empty overlay area must NOT close the board — only ✕/取消 closes it
		          if (showAdd || detailId || wsPicker || confirmDel) return
		          // otherwise clicking the blank area closes popovers first, then the board
		          if (autoOpen) { setAutoOpen(false); return }
		          if (ctxMenu) { setCtxMenu(null); return }
		          setOpen(false)
		        },
		      },
		        el('div', { className: 'kb-board' },
		          el('div', { className: 'kb-topbar' },
		            el('div', { className: 'kb-brand' },
		              el('div', { className: 'kb-brand-mark' }, '◫'),
		              el('div', null,
		                el('div', { className: 'kb-brand-name' }, '任务看板'),
		                el('div', { className: 'kb-brand-sub' }, 'Agent-Driven Feature Board'),
		              ),
		            ),
		            el('label', { className: 'kb-chip', title: '当前工作区' },
		              '工作区：',
		              el('select', { value: selWs ? selWs.id : '', onChange: (e) => { const w = (view && view.workspaces || []).find(x => x.id === e.target.value); if (w) selectWorkspace(w) } },
		                !selWs ? el('option', { value: '' }, '未选择') : null,
		                (view ? view.workspaces : []).map(w => el('option', { key: w.id, value: w.id }, w.title)),
		              ),
		            ),
		            el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => setShowFilter(v => !v), title: '筛选 (F)' }, '⚲ 筛选'),
		            el('div', { className: 'kb-spacer' }),
		            el('div', { className: 'kb-search' },
		              el('span', { className: 'ico' }, '⌕'),
		              el('input', { ref: searchRef, placeholder: '搜索议题… (/)', value: query, onChange: (e) => setQuery(e.target.value) }),
		            ),
		            el('div', { className: 'kb-auto-wrap' },
		              el('button', {
		                className: 'kb-btn kb-btn-ghost' + (state && state.autoExec && state.autoExec.enabled ? ' kb-auto-btn on' : ''),
		                disabled: !selWs,
		                onClick: () => void openAutoPanel(),
		                title: '自动化执行设置',
		              }, '⚙ 自动化' + (state && state.autoExec && state.autoExec.enabled ? ' · 开' : '')),
		              autoOpen ? el('div', { className: 'kb-auto-pop', onClick: (e) => e.stopPropagation() },
		                el('div', { className: 'kb-auto-title' }, '自动化执行'),
		                el('label', { className: 'kb-switch', title: '开启后按间隔自动检索工作区待执行任务' },
		                  el('input', { type: 'checkbox', checked: !!(state && state.autoExec && state.autoExec.enabled), disabled: !selWs, onChange: (e) => void updateAutoExec({ enabled: e.target.checked }) }),
		                  el('span', { className: 'track' }),
		                  '启用自动化',
		                ),
		                el('label', { className: 'kb-switch', title: '进入待验收后自动派发验收 agent（与执行共享推理强度/模型等参数）' },
		                  el('input', { type: 'checkbox', checked: !!(state && state.autoAccept), disabled: !selWs, onChange: (e) => void act(() => call('setAutoAccept', { workspaceId: selWs.id, enabled: e.target.checked })) }),
		                  el('span', { className: 'track' }),
		                  '自动验收',
		                ),
		                el('label', { className: 'kb-switch', title: '待立项是否自动进入自动化流程：开启后新建需求与失败自动生成的修复前置都会自动转入等待认领并派发；你手动拖回待立项的任务视为停用，不会被自动领取；有前置依赖的任务等前置验收通过后再入队' },
		                  el('input', { type: 'checkbox', checked: !!(state && state.autoExec && state.autoExec.promoteBacklog), disabled: !selWs || !(state && state.autoExec && state.autoExec.enabled), onChange: (e) => void updateAutoExec({ promoteBacklog: e.target.checked }) }),
		                  el('span', { className: 'track' }),
		                  '待立项自动进流程',
		                ),
		                el('div', { className: 'kb-auto-row' },
		                  el('span', null, '检索间隔'),
		                  el('select', {
		                    value: (state && state.autoExec && state.autoExec.intervalSec) || 60,
		                    onChange: (e) => void updateAutoExec({ intervalSec: Number(e.target.value) }),
		                  },
		                    [15, 30, 60, 120, 300, 600, 1800, 3600].map(sec => el('option', { key: sec, value: sec }, sec < 60 ? sec + ' 秒' : (sec % 3600 === 0 ? sec / 3600 + ' 小时' : sec / 60 + ' 分钟'))),
		                  ),
		                ),
		                el('div', { className: 'kb-auto-row' },
		                  el('span', null, '并发数'),
		                  el('select', {
		                    value: (state && state.autoExec && state.autoExec.concurrency) || 3,
		                    onChange: (e) => void updateAutoExec({ concurrency: Number(e.target.value) }),
		                  },
		                    [1, 2, 3, 4, 5, 6, 8, 10].map(n => el('option', { key: n, value: n }, n + ' 个并行')),
		                  ),
		                ),
		                el('div', { className: 'kb-auto-row' },
		                  el('span', null, '推理强度'),
		                  el('select', {
		                    value: (state && state.autoExec && state.autoExec.effort) || '',
		                    onChange: (e) => void updateAutoExec({ effort: e.target.value || null }),
		                  },
		                    el('option', { value: '' }, '默认'),
		                    el('option', { value: 'off' }, 'off（不思考）'),
		                    el('option', { value: 'high' }, 'high（高）'),
		                    el('option', { value: 'max' }, 'max（最大）'),
		                  ),
		                ),
		                el('div', { className: 'kb-auto-row' },
		                  el('span', null, '推理模型'),
		                  el('select', {
		                    value: (state && state.autoExec && state.autoExec.model) || '',
		                    onChange: (e) => void updateAutoExec({ model: e.target.value || null }),
		                  },
		                    el('option', { value: '' }, '默认' + (modelCatalog && modelCatalog.current ? '（' + modelCatalog.current.model + '）' : '')),
		                    (modelCatalog ? modelCatalog.models : []).map(m => el('option', { key: m.id, value: m.id }, m.name)),
		                  ),
		                ),
		                el('div', { className: 'kb-auto-hint' }, '开启后每隔设定间隔自动检索待执行任务并派发 executor；「待立项自动进流程」统一控制待立项（含新建需求与失败自动生成的修复前置）是否自动转入等待认领——你手动停回待立项的任务除外；有前置依赖的任务等前置验收通过后才入队；并发数=同时运行的执行 agent 数（仅 git 工作区生效，非 git 自动串行）；推理强度与模型同时作用于执行与验收子 agent。'),
		              ) : null,
		            ),
		            el('button', { className: 'kb-btn kb-btn-primary', disabled: !selWs, onClick: () => { setAddStatus('backlog'); setShowAdd(true) }, title: '新建 (C)' }, '＋ 新建需求'),
		            el('button', { className: 'kb-btn kb-btn-ghost kb-btn-close', onClick: () => setOpen(false) }, '✕'),
		          ),
		          el('div', { className: 'kb-body' },
		            el('div', { className: 'kb-wscol' },
		              el('div', { className: 'kb-wscol-head' }, el('span', null, '工作区'), el('span', null, (view ? view.workspaces.length : 0))),
		              el('div', { className: 'kb-ws-list' },
		                (view ? view.workspaces : []).length === 0 ? el('div', { className: 'kb-empty' }, '暂无工作区\n点击「＋」创建') : null,
		                (view ? view.workspaces : []).map(w => el('div', { key: w.id, className: 'kb-ws-item' + (selWs && selWs.id === w.id ? ' active' : ''), onClick: () => selectWorkspace(w), title: w.path },
		                  el('span', { className: 't' }, w.title),
		                  el('span', { className: 'p' }, w.path),
		                )),
		              ),
		              el('div', { className: 'kb-ws-actions' },
		                el('button', { className: 'kb-ws-btn', onClick: () => void addWorkspace() }, '＋ 新增'),
		                el('button', { className: 'kb-ws-btn danger', disabled: !selWs, onClick: () => setConfirmDel(selWs) }, '⌫ 删除'),
		              ),
		            ),
		            el('div', { className: 'kb-main' },
		              !selWs ? el('div', { className: 'kb-banner' }, '⚠ 请先选择工作区（左侧列或顶部下拉），未设置工作区不能新建需求、派发执行。') : null,
		              offline ? el('div', { className: 'kb-banner kb-banner-conn' }, '⚠ 正在重新连接… 看板将在恢复后自动同步') : null,
		              el('div', { className: 'kb-toolbar' },
		                el('button', { className: 'kb-viewtab' + (tab === 'board' ? ' active' : ''), onClick: () => setTab('board') }, '看板'),
		                el('button', { className: 'kb-viewtab' + (tab === 'dashboard' ? ' active' : ''), onClick: () => setTab('dashboard') }, '仪表盘'),
		                el('button', { className: 'kb-viewtab' + (tab === 'list' ? ' active' : ''), onClick: () => setTab('list') }, '列表'),
		                el('button', { className: 'kb-viewtab' + (tab === 'gantt' ? ' active' : ''), onClick: () => setTab('gantt') }, '甘特'),
		                el('button', { className: 'kb-viewtab' + (tab === 'nodes' ? ' active' : ''), onClick: () => setTab('nodes') }, '节点'),
		                el('button', { className: 'kb-viewtab' + (tab === 'labels' ? ' active' : ''), onClick: () => setTab('labels') }, '标签'),
		                el('div', { className: 'kb-spacer' }),
		                el('button', { className: 'kb-viewtab' + (otherOpen ? ' active' : ''), onClick: () => setOtherOpen(v => !v) }, otherOpen ? '关闭其他任务' : '打开其他任务'),
		              ),
		              tab === 'board' && showFilter ? el('div', { className: 'kb-filterrow' },
		                '状态', el('select', { value: filter.status, onChange: (e) => setFilter({ ...filter, status: e.target.value }) },
		                  el('option', { value: '' }, '全部'), STATUSES.map(s => el('option', { key: s.key, value: s.key }, s.label))),
		                '优先级', el('select', { value: filter.priority, onChange: (e) => setFilter({ ...filter, priority: e.target.value }) },
		                  el('option', { value: '' }, '全部'), PRIORITIES.map(p => el('option', { key: p.key, value: p.key }, p.label))),
		                '标签', el('select', { value: filter.label, onChange: (e) => setFilter({ ...filter, label: e.target.value }) },
		                  el('option', { value: '' }, '全部'), (state ? state.labels : []).map(l => el('option', { key: l.name, value: l.name }, l.name))),
		              ) : null,
		              el('div', { className: 'kb-msg' }, msg),
		              tab === 'dashboard'
		                ? el(DashboardView, { state, issues, selWs, act, openDetail: setDetailId })
		                : tab === 'list'
		                  ? el(ListView, { issues: visible, state, openDetail: setDetailId, act, selWs, query, filter })
		                  : tab === 'labels'
		                    ? el(LabelsView, { state, selWs, act, refresh })
		                    : tab === 'gantt'
		                      ? el(GanttView, { issues: visible, state, openDetail: setDetailId })
		                      : tab === 'nodes'
		                        ? el(NodesView, { issues: visible, state, openDetail: setDetailId })
		                        : el('div', { className: 'kb-cols' },
		                MAIN_COLS.map(colKey => {
		                  const st = statusMeta(colKey)
		                  const cards = byCol(colKey)
		                  return el('div', {
		                    className: 'kb-col' + (dragOver === colKey ? ' kb-col-drop' : ''), key: colKey,
		                    onDragOver: (e) => { e.preventDefault(); if (dragOver !== colKey) setDragOver(colKey) },
		                    onDragLeave: () => setDragOver(''),
		                    onDrop: (e) => {
		                      e.preventDefault(); setDragOver('')
		                      const id = e.dataTransfer.getData('text/kanban-id')
		                      if (id && selWs) moveIssue(id, colKey)
		                    },
		                  },
		                    el('div', { className: 'kb-col-head' },
		                      el('span', { className: 'dot', style: { background: st.color } }),
		                      el('h3', null, st.label),
		                      el('span', { className: 'kb-count' }, cards.length),
		                      el('button', { className: 'kb-addcol', title: '在「' + st.label + '」中新建', disabled: !selWs, onClick: () => { setAddStatus(colKey); setShowAdd(true) } }, '＋'),
		                    ),
		                    el('div', { className: 'kb-col-body' },
		                      cards.map(c => el(CardView, { key: c.id, issue: c, state, issues, selWs, openDetail: setDetailId, act, openMenu: setCtxMenu })),
		                      cards.length === 0 ? el('div', { className: 'kb-empty' },
		                        (query || filter.status || filter.priority || filter.label) ? '当前筛选下无匹配议题' : (st.key === 'backlog' ? el('div', null, el('b', null, '暂无待立项议题'), el('div', null, '点击「＋ 新建需求」把想法放进管线')) : '暂无「' + st.label + '」议题'),
		                      ) : null,
		                    ),
		                  )
		                }),
		              ),
		            ),
		            el(OtherPanelView, { otherOpen, otherTab, setOtherTab, issues, openDetail: setDetailId, moveIssue, act, selWs }),
		          ),
		          el(ContextMenuView, { ctxMenu, issueById, state, selWs, moveIssue, act, closeMenu: () => setCtxMenu(null), setSub: (sub) => setCtxMenu(m => m ? { ...m, sub } : m), openDetail: setDetailId, sessionsSvc, workspacesSvc, closeBoard: () => setOpen(false) }),
		          el(AddIssueModalView, { key: showAdd ? 'add-open' : 'add-closed', showAdd, state, addStatus, setAddStatus, addPri, setAddPri, addLabels, setAddLabels, addDue, setAddDue, setAddTitle, setAddDesc, createIssue, closeAdd: () => setShowAdd(false), addLabel }),
		          el(WorkspacePickerModalView, { wsPicker, wsGo, wsSelectFrom, closeWs: () => setWsPicker(null) }),
		          detail ? el(DetailView, { detail, state, issues, issueById, statusLabel, selWs, act, closeDetail: () => setDetailId(null), openDetail: setDetailId, addLabel, deleteLabel }) : null,
		          confirmDel ? el('div', { className: 'kb-modal', onClick: () => setConfirmDel(null) },
		            el('div', { className: 'kb-modal-box', onClick: (e) => e.stopPropagation() },
		              el('h3', null, '删除项目"' + confirmDel.title + '"？'),
		              el('p', null, '仅空项目可以删除。删除后无法恢复。'),
		              el('div', { className: 'kb-modal-actions' },
		                el('button', { className: 'kb-btn kb-btn-ghost', onClick: () => setConfirmDel(null) }, '取消'),
		                el('button', { className: 'kb-btn kb-btn-primary', style: { background: 'var(--kb-danger)' }, onClick: () => void delWorkspace() }, '永久删除'),
		              ),
		            ),
		          ) : null,
		          el('div', { className: 'kb-statusbar' },
		            el('span', { className: 'path' }, state && state.statePath ? '状态文件: ' + state.statePath : ''),
		            el('span', null, '运行中批次: ' + (runningBatches.length ? runningBatches.join(', ') : '无')),
		            el('span', { className: 'sum' },
		              MAIN_COLS.map(k => el('span', { key: k }, statusMeta(k).label + ' ', el('b', null, byCol(k).length))),
		            ),
		          ),
		        ),
		      )
		    }
		
		    function Toggle() {
		      const open = useOpen()
		      return el('button', {
		        className: 'kb-toggle',
		        onClick: () => setOpen(!open),
		        title: '任务看板',
		        'aria-label': '任务看板',
		      }, el('span', null, '任务看板'))
		    }
		
		    function SidebarAction() {
		      const open = useOpen()
		      return el('button', { className: 'kb-toggle', onClick: () => setOpen(!open), title: '任务看板' }, '◫ 看板')
		    }
		
		    function StartPanel() {
		      const open = useOpen()
		      return el('div', { className: 'kb-startpanel' },
		        el('span', { style: { fontSize: 15 } }, '◫'),
		        el('span', { style: { fontSize: 12.5, fontWeight: 700, color: 'var(--kb-text)' } }, '任务看板已启动'),
		        el('button', { className: 'kb-mini primary', onClick: () => setOpen(!open) }, open ? '关闭看板' : '打开看板'),
		      )
		    }
		
		    // 入口：仅保留会话标题行 utilities（Session log 左边）与全屏浮层
		    slots.inject('conversation.session.header.utilities', () => slots.register(
		      { name: 'conversation.session.header.utilities', id: 'kanban-toggle', order: -10 },
		      () => el(Toggle),
		    ))
		    slots.inject('shell.overlay', () => slots.register(
		      { name: 'shell.overlay', id: 'kanban-board' },
		      () => el(Board),
		    ))
		}
		
		module.exports = { apply, inject: ["slots", "sessions", "workspaces"] }
		
		return module.exports;
	}
});
