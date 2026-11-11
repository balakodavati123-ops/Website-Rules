/* Tab switching. The Live floor opens first, or the tab named in the link. */
(function () {
  const TABS = ['floor', 'command', 'premarket', 'alerts', 'algo', 'markets', 'room'];
  const show = (id) => {
    TABS.forEach((t) => { const sec = document.getElementById('tab-' + t); const btn = document.getElementById('tabbtn-' + t);
      if (sec) sec.hidden = t !== id; if (btn) btn.setAttribute('aria-selected', t === id ? 'true' : 'false'); });
    if (CD.ENG) CD.ENG.show(id === 'floor');   /* the desks only work while their tab is on screen */
    try { dash.setLink(id); } catch (e) { /* link is a convenience */ }
  };
  CD.goto = show;
  document.querySelectorAll('.cd-tab').forEach((b) => b.addEventListener('click', () => show(b.getAttribute('data-tab'))));
  const hash = (location.hash || '').replace('#', '');
  show(TABS.includes(hash) ? hash : 'floor');
})();
