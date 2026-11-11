/* Tab switching. The right tab opens by the time of day, or by the link. */
(function () {
  const TABS = ['command', 'premarket', 'alerts', 'algo', 'markets', 'room'];
  const show = (id) => {
    TABS.forEach((t) => { const sec = document.getElementById('tab-' + t); const btn = document.getElementById('tabbtn-' + t);
      if (sec) sec.hidden = t !== id; if (btn) btn.setAttribute('aria-selected', t === id ? 'true' : 'false'); });
    try { dash.setLink(id); } catch (e) { /* link is a convenience */ }
  };
  CD.goto = show;
  document.querySelectorAll('.cd-tab').forEach((b) => b.addEventListener('click', () => show(b.getAttribute('data-tab'))));
  const hash = (location.hash || '').replace('#', '');
  const k = CD.session().key;
  show(TABS.includes(hash) ? hash : k === 'early' || k === 'pre' ? 'premarket' : k === 'open' ? 'alerts' : 'command');
})();
