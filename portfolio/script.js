/* ════════════════════════════════════════════════
   ПОРТФОЛИО — СКРИПТЫ (ВКЛАДКИ)
   ════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initMobileMenu();
    initScrollReveal();
});

/* ── Переключение вкладок ── */
function initTabs() {
    const navLinks = document.querySelectorAll('.nav-link[data-tab]');
    const tabs = document.querySelectorAll('.tab-content');

    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = link.dataset.tab;

            // Переключаем активный пункт навигации
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');

            // Переключаем видимую вкладку
            tabs.forEach(tab => {
                tab.classList.remove('active');
                if (tab.id === targetId) {
                    tab.classList.add('active');
                    // Прокрутка наверх
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                    // Перезапускаем reveal-анимации для новой вкладки
                    requestAnimationFrame(() => initScrollReveal());
                }
            });
        });
    });
}

/* ── Мобильное меню ── */
function initMobileMenu() {
    const toggle = document.getElementById('nav-toggle');
    const links = document.getElementById('nav-links');

    toggle.addEventListener('click', () => {
        toggle.classList.toggle('active');
        links.classList.toggle('open');
    });

    // Закрыть при клике на ссылку
    links.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            toggle.classList.remove('active');
            links.classList.remove('open');
        });
    });
}

/* ── Scroll Reveal: анимация появления элементов ── */
function initScrollReveal() {
    const selectors = [
        '.about-card', '.contact-card', '.stack-card',
        '.study-block', '.grade-item', '.olympiad-item', '.extra-edu-item',
        '.college-hero', '.college-card',
        '.excursion-card',
        '.project-card',
        '.stat-card', '.timeline-item', '.cert-card'
    ];

    const revealElements = document.querySelectorAll(selectors.join(', '));

    revealElements.forEach(el => {
        // Сбросим, чтобы анимация могла перезапуститься при смене вкладки
        if (!el.classList.contains('reveal')) {
            el.classList.add('reveal');
        }
    });

    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    // Каскадная задержка — вычисляем по позиции среди сиблингов
                    const parent = entry.target.parentElement;
                    const siblings = Array.from(parent.children).filter(c => c.classList.contains('reveal'));
                    const index = siblings.indexOf(entry.target);
                    const delay = Math.min(index * 70, 420);

                    setTimeout(() => {
                        entry.target.classList.add('visible');
                    }, delay);

                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.08, rootMargin: '0px 0px -30px 0px' }
    );

    revealElements.forEach(el => {
        if (!el.classList.contains('visible')) {
            observer.observe(el);
        }
    });
}
