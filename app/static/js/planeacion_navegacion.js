/* Navegación de la planeación y preferencias de lectura por ficha. */
'use strict';

function initPlaneacionNavigation(root = document, win = window) {
    const page = root.querySelector('.pl-page');
    if (!page) return;
    const doc = root.ownerDocument || root;
    const sections = page.querySelectorAll('section.pl-card[id]:not(.pl-carga-card)');
    const links = page.querySelectorAll('.pl-subnav-link');
    const controls = new Map();

    function storageKey(section) {
        return 'pl-collapse:f' + page.dataset.fichaId + ':' + section.id;
    }

    function setCollapsed(section, collapsed, persist = true) {
        const control = controls.get(section);
        if (!control) return;
        section.classList.toggle('is-collapsed', collapsed);
        const label = (collapsed ? 'Expandir ' : 'Contraer ') + control.title;
        control.button.setAttribute('aria-expanded', String(!collapsed));
        control.button.setAttribute('aria-label', label);
        control.button.title = label;
        if (persist) {
            try { win.localStorage.setItem(storageKey(section), collapsed ? '1' : '0'); }
            catch (_) { /* La navegación sigue disponible sin almacenamiento. */ }
        }
    }

    for (const section of sections) {
        const head = section.querySelector(':scope > .pl-card-head');
        if (!head) continue;
        const heading = head.querySelector('h2, h3');
        const button = doc.createElement('button');
        button.type = 'button';
        button.className = 'pl-card-toggle';
        button.setAttribute('aria-controls', section.id);
        const icon = doc.createElement('span');
        icon.className = 'pl-card-toggle-icon';
        icon.setAttribute('aria-hidden', 'true');
        button.appendChild(icon);
        if (win.getComputedStyle(head).display === 'flex') button.classList.add('is-inline');
        else head.classList.add('has-toggle');
        head.appendChild(button);
        controls.set(section, { button, title: heading ? heading.textContent.trim() : 'sección' });
        let collapsed = section.dataset.collapseDefault === 'cerrado';
        try {
            const saved = win.localStorage.getItem(storageKey(section));
            if (saved !== null) collapsed = saved === '1';
        } catch (_) { /* Se conserva la presentación inicial cuando no hay memoria. */ }
        setCollapsed(section, collapsed, false);
        button.addEventListener('click', function () {
            setCollapsed(section, !section.classList.contains('is-collapsed'));
        });
    }

    function setActive(id, revealMenu = false) {
        for (const link of links) {
            const active = link.getAttribute('href') === '#' + id;
            link.classList.toggle('is-active', active);
            if (active) {
                link.setAttribute('aria-current', 'location');
                const menu = link.closest('details.pl-nav-more');
                if (revealMenu && menu) menu.open = true;
            } else link.removeAttribute('aria-current');
        }
    }

    function revealHash(hash) {
        if (!hash || hash === '#') return;
        let id;
        try { id = decodeURIComponent(hash.slice(1)); }
        catch (_) { return; }
        const target = doc.getElementById(id);
        if (!target) return;
        const section = target.closest('section.pl-card[id]');
        if (section) setCollapsed(section, false);
        if (id === 'centro-carga') {
            const uploader = target.querySelector('details.pl-carga-actualizar');
            if (uploader) uploader.open = true;
        }
        setActive(section ? section.id : id, true);
    }

    function collapseAll(collapsed) {
        for (const section of controls.keys()) setCollapsed(section, collapsed);
    }

    const expandAll = doc.getElementById('pl-expandir-todo');
    const collapseButton = doc.getElementById('pl-colapsar-todo');
    if (expandAll) expandAll.addEventListener('click', function () { collapseAll(false); });
    if (collapseButton) collapseButton.addEventListener('click', function () { collapseAll(true); });
    root.addEventListener('click', function (event) {
        const link = event.target.closest('a[href^="#"]');
        if (link) revealHash(link.getAttribute('href'));
    });
    win.addEventListener('hashchange', function () { revealHash(win.location.hash); });

    for (const link of links) {
        if (link.classList.contains('is-active')) link.setAttribute('aria-current', 'location');
    }
    revealHash(win.location.hash);

    if (typeof win.IntersectionObserver === 'function' && links.length) {
        const observer = new win.IntersectionObserver(function (entries) {
            for (const entry of entries) {
                if (entry.isIntersecting) setActive(entry.target.id);
            }
        }, { rootMargin: '-20% 0px -70% 0px' });
        for (const link of links) {
            const target = doc.getElementById(link.getAttribute('href').slice(1));
            if (target) observer.observe(target);
        }
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { initPlaneacionNavigation };
} else {
    initPlaneacionNavigation();
}
