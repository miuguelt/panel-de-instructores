/* Regla 7.4: medir la prosa sin introducir contención en su composición. */
(function (host) {
  function initProseLayout(document, view) {
    const selector = 'p, dd, blockquote';
    const excluded = 'nav, button, table, pre, code, [role="button"], [role="alert"], [role="status"], .toast, .notification, .alert, .eyebrow, .overline, .kicker, .document-type';
    const tracked = new Set();
    const initialAlignments = new Map();
    function update(element) {
      if (!element.isConnected || element.closest(excluded)) return;
      const width = element.getBoundingClientRect().width;
      const rem = parseFloat(view.getComputedStyle(document.documentElement).fontSize);
      const alignment = width >= 40 * rem ? 'justify' : 'start';
      if (!initialAlignments.has(element)) initialAlignments.set(element, {
        value:element.style.getPropertyValue('text-align'),
        priority:element.style.getPropertyPriority ? element.style.getPropertyPriority('text-align') : ''
      });
      if (element.style.getPropertyValue('--text-align-reading') !== alignment) element.style.setProperty('--text-align-reading', alignment);
      if (element.style.getPropertyValue('text-align') !== alignment) element.style.setProperty('text-align', alignment);
    }
    const resize = new view.ResizeObserver(function (entries) {
      for (const entry of entries) update(entry.target);
    });
    function refresh() {
      for (const element of tracked) {
        if (!element.isConnected) { resize.unobserve(element); tracked.delete(element); }
      }
      for (const element of document.querySelectorAll(selector)) {
        if (!element.isConnected) continue;
        if (!tracked.has(element)) { tracked.add(element); resize.observe(element); }
        update(element);
      }
    }
    const mutation = new view.MutationObserver(refresh);
    mutation.observe(document.documentElement, { childList:true, subtree:true });
    view.addEventListener('resize',refresh);
    document.addEventListener('load',refresh,true);
    refresh();
    function destroy() {
      resize.disconnect(); mutation.disconnect();
      view.removeEventListener('resize',refresh);
      document.removeEventListener('load',refresh,true);
      for (const element of tracked) {
        element.style.removeProperty('--text-align-reading');
        const initial = initialAlignments.get(element);
        if (initial?.value) element.style.setProperty('text-align', initial.value, initial.priority);
        else element.style.removeProperty('text-align');
      }
      initialAlignments.clear();
      tracked.clear();
    }
    return {refresh,destroy};
  }
  function start() {
    if (host.DevBrainProseLayout || !host.ResizeObserver) return;
    host.DevBrainProseLayout = initProseLayout(host.document,host);
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {initProseLayout,start};
  if (host.document) {
    if (host.document.readyState === 'loading') host.document.addEventListener('DOMContentLoaded',start,{once:true});
    else start();
  }
})(globalThis);
