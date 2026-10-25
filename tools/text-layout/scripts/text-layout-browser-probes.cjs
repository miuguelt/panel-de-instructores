function createStressExpression(repeats = 5) {
  const numericRepeats = Number(repeats);
  const count = Number.isFinite(numericRepeats) ? Math.max(1, Math.min(20, numericRepeats)) : 5;
  return `(() => {
    const selector = 'p, li, dd, blockquote, figcaption, h1, h2, h3, h4, h5, h6, label, [class*="description"], [class*="subtitle"], [class*="summary"], [class*="paragraph"], [class*="lead"]';
    const phrase = 'Texto de comprobación extensa para validar el ajuste natural del contenido y el crecimiento vertical de cada bloque.';
    const isVisiblyRendered = element => {
      for (let parent = element; parent && parent !== document.body; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility) || Number(style.opacity) <= 0.05) return false;
      }
      return true;
    };
    let changed = 0;
    document.querySelectorAll('details').forEach(item => { item.open = true; });
    for (const element of document.querySelectorAll(selector)) {
      if (!element.getClientRects().length || !isVisiblyRendered(element) || element.closest('nav, button, [role="button"], [role="alert"], [role="status"], .toast, .notification, .alert, pre, code, .dbc, .badge, .chip, .tag, .sr-only, .visually-hidden, .screen-reader-only, [class*="visually-hidden"], [aria-hidden="true"]')) continue;
      if (!element.textContent.trim()) continue;
      element.append(document.createTextNode(' ' + phrase.repeat(${count})));
      changed += 1;
    }
    return changed;
  })()`;
}

function createAuditExpression(probeSelectors = []) {
  return `(() => {
    const naturalSelector = 'p, li, dd, blockquote, figcaption, h1, h2, h3, h4, h5, h6, label, [class*="description"], [class*="subtitle"], [class*="summary"], [class*="paragraph"], [class*="lead"]';
    const isVisiblyRendered = element => {
      for (let parent = element; parent && parent !== document.body; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility) || Number(style.opacity) <= 0.05) return false;
      }
      return true;
    };
    const natural = Array.from(document.querySelectorAll(naturalSelector)).filter(element =>
      element.getClientRects().length && isVisiblyRendered(element) && !element.closest('nav, button, [role="button"], [role="alert"], [role="status"], .toast, .notification, .alert, pre, code, .dbc, .badge, .chip, .tag, .sr-only, .visually-hidden, .screen-reader-only, [class*="visually-hidden"], [aria-hidden="true"]')
    );
    const findings = [];
    const add = (rule, element, detail) => {
      findings.push({
        rule,
        selector: element.tagName.toLowerCase() + (typeof element.className === 'string' && element.className.trim() ? '.' + element.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''),
        text: element.textContent.trim().slice(0, 80),
        detail
      });
    };
    for (const element of natural) {
      const style = getComputedStyle(element);
      if (style.textOverflow === 'ellipsis' || (style.webkitLineClamp && style.webkitLineClamp !== 'none' && style.webkitLineClamp !== 'unset')) add('content-truncation', element, 'el texto tiene truncamiento o límite de líneas');
      if (style.whiteSpace === 'nowrap') add('content-no-wrap', element, 'el texto no permite envoltura');
      if (style.wordBreak === 'break-all' || style.overflowWrap === 'anywhere') add('forced-word-break', element, 'el texto se puede partir dentro de una palabra');
      if (element.matches('p, dd, blockquote') && !element.matches('.eyebrow, .overline, .kicker, .document-type') && !element.closest('table, nav, button, [role="button"]') && !element.hasAttribute('data-text-layout-exception')) {
        const width = element.getBoundingClientRect().width;
        const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
        if (width < 40 * rem - 1 && style.textAlign === 'justify') add('narrow-region-justification', element, 'la región menor de 40rem debe alinearse al inicio');
        if (width >= 40 * rem && !['justify'].includes(style.textAlign)) add('missing-prose-justification', element, 'la región de al menos 40rem debe justificarse');
        if (style.hyphens === 'auto') add('automatic-hyphenation', element, 'la prosa divide palabras automáticamente');
        for (let region = element; region && region !== document.body; region = region.parentElement) {
          if (region.matches('dialog, [role="dialog"], .modal, .popover, .dropdown, .tooltip, .toast, .notification, .decoder, .device-inspection-shell, .inspection-shell')) break;
          const owner = region.parentElement;
          const regionStyle = getComputedStyle(region);
          const ownerStyle = getComputedStyle(owner);
          const available = owner.clientWidth - parseFloat(ownerStyle.paddingLeft) - parseFloat(ownerStyle.paddingRight);
          if (!['block', 'flow-root'].includes(ownerStyle.display)) continue;
          const maximum = regionStyle.maxWidth.trim().toLowerCase();
          const adaptiveOnly = maximum === '100%' || /^calc\\(\\s*100%\\s*-/.test(maximum);
          if (maximum !== 'none' && !adaptiveOnly && region.getBoundingClientRect().width < available - 2 && !region.hasAttribute('data-text-layout-exception')) {
            add('unused-region-width', element, 'un límite de ancho en ' + region.tagName.toLowerCase() + '.' + region.className + ' desaprovecha su región');
            break;
          }
        }
      }

      const range = document.createRange();
      range.selectNodeContents(element);
      const textRect = range.getBoundingClientRect();
      let horizontallyScrollable = false;
      let verticallyScrollable = false;
      for (let parent = element; parent && parent !== document.body; parent = parent.parentElement) {
        const parentStyle = getComputedStyle(parent);
        const rect = parent.getBoundingClientRect();
        horizontallyScrollable ||= ['auto', 'scroll'].includes(parentStyle.overflowX);
        verticallyScrollable ||= ['auto', 'scroll'].includes(parentStyle.overflowY);
        const clipsX = !horizontallyScrollable && ['hidden', 'clip'].includes(parentStyle.overflowX);
        const clipsY = !verticallyScrollable && ['hidden', 'clip'].includes(parentStyle.overflowY);
        const contentRight = rect.right - parseFloat(parentStyle.borderRightWidth);
        const contentBottom = rect.bottom - parseFloat(parentStyle.borderBottomWidth);
        const clippedX = clipsX && textRect.right > contentRight + 1;
        const clippedY = clipsY && textRect.bottom > contentBottom + 1;
        if (clippedX || clippedY) {
          const className = typeof parent.className === 'string' ? parent.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
          const axis = [clippedX && 'horizontal', clippedY && 'vertical'].filter(Boolean).join(' y ');
          add('content-clipping', element, 'el contenedor ' + parent.tagName.toLowerCase() + (className ? '.' + className : '') + ' oculta texto en el eje ' + axis + ' (texto ' + Math.round(textRect.right) + '×' + Math.round(textRect.bottom) + ', límite ' + Math.round(contentRight) + '×' + Math.round(contentBottom) + ')');
          break;
        }
      }
    }
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
    const pageWidth = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0);
    const visibleDocumentOverflow = Array.from(document.querySelectorAll('body *')).some(element => {
      if (!element.getClientRects().length || !isVisiblyRendered(element) || element.closest('.sr-only, .visually-hidden, .screen-reader-only, [class*="visually-hidden"], [aria-hidden="true"]')) return false;
      const rect = element.getBoundingClientRect();
      if (rect.right <= viewportWidth + 1) return false;
      for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
        if (['hidden', 'clip', 'auto', 'scroll'].includes(getComputedStyle(parent).overflowX)) return false;
      }
      return true;
    });
    if (pageWidth > viewportWidth + 1 && visibleDocumentOverflow) {
      findings.push({ rule: 'page-overflow', selector: 'document', text: '', detail: 'ancho del documento ' + pageWidth + 'px para una ventana de ' + viewportWidth + 'px' });
    }
    const matchingRulesFor = selector => {
      const matches = [];
      const visit = (rules, media = 'all') => {
        for (const rule of rules) {
          const currentMedia = rule.conditionText || media;
          if (rule.cssRules && rule.cssRules.length) visit(rule.cssRules, currentMedia);
          else if (rule.styleSheet) {
            try { visit(rule.styleSheet.cssRules, currentMedia); } catch (error) { matches.push({ error: error.message }); }
          }
          else if (rule.selectorText && rule.selectorText.includes(selector.replace(/^[.#]/, ''))) {
            matches.push({ selector: rule.selectorText, media: currentMedia, declarations: rule.style.cssText });
          }
        }
      };
      for (const sheet of document.styleSheets) {
        try { visit(sheet.cssRules); } catch (error) { matches.push({ error: error.message }); }
      }
      return matches;
    };
    const probes = {};
    for (const selector of ${JSON.stringify(probeSelectors)}) {
      try {
        const candidates = selector === '@overflow'
          ? Array.from(document.querySelectorAll('body *')).filter(element => {
            if (!isVisiblyRendered(element) || element.closest('.sr-only, .visually-hidden, .screen-reader-only, [class*="visually-hidden"], [aria-hidden="true"]')) return false;
            if (['auto', 'scroll'].includes(getComputedStyle(element).overflowX)) return false;
            for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
              if (['auto', 'scroll'].includes(getComputedStyle(parent).overflowX)) return false;
            }
            const rect = element.getBoundingClientRect();
            return rect.right > viewportWidth + 1 || element.scrollWidth > element.clientWidth + 1;
          }).sort((left, right) => {
            const leftRect = left.getBoundingClientRect();
            const rightRect = right.getBoundingClientRect();
            return Math.max(0, rightRect.right - viewportWidth) - Math.max(0, leftRect.right - viewportWidth)
              || (right.scrollWidth - right.clientWidth) - (left.scrollWidth - left.clientWidth);
          }).slice(0, 20)
          : Array.from(document.querySelectorAll(selector)).slice(0, 5);
        probes[selector] = candidates.map(element => {
          const rect = element.getBoundingClientRect();
          const computed = getComputedStyle(element);
          return {
            selector: element.tagName.toLowerCase() + (typeof element.className === 'string' && element.className.trim() ? '.' + element.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''),
            text: element.textContent.trim().slice(0, 120),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            clientWidth: element.clientWidth,
            scrollWidth: element.scrollWidth,
            display: computed.display,
            gridTemplateColumns: computed.gridTemplateColumns,
            cssWidth: computed.width,
            minWidth: computed.minWidth,
            maxWidth: computed.maxWidth,
            overflowX: computed.overflowX,
            overflowY: computed.overflowY,
            textAlign: computed.textAlign,
            whiteSpace: computed.whiteSpace,
            overflowWrap: computed.overflowWrap,
            transform: computed.transform,
            inlineStyle: element.getAttribute('style'),
            mediaMax768: window.matchMedia('(max-width: 768px)').matches,
            ancestors: selector === '@overflow' ? (() => {
              const chain = [];
              for (let parent = element.parentElement; parent && parent !== document.body && chain.length < 8; parent = parent.parentElement) {
                const parentRect = parent.getBoundingClientRect();
                const parentStyle = getComputedStyle(parent);
                chain.push({
                  selector: parent.tagName.toLowerCase() + (typeof parent.className === 'string' && parent.className.trim() ? '.' + parent.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''),
                  left: Math.round(parentRect.left),
                  right: Math.round(parentRect.right),
                  width: Math.round(parentRect.width),
                  scrollWidth: parent.scrollWidth,
                  overflowX: parentStyle.overflowX
                });
              }
              return chain;
            })() : undefined,
            matchingRules: matchingRulesFor(selector)
          };
        });
      } catch (error) {
        probes[selector] = { error: error.message };
      }
    }
    return { viewportWidth, pageWidth, naturalTextBlocks: natural.length, findings, probes };
  })()`;
}

module.exports = { createStressExpression, createAuditExpression };
