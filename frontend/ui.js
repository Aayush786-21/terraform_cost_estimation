// Lightweight UI enhancements shared across landing, app shell, and share views.
// Keeps existing app.js/share.js behavior intact while adding motion and polish.

(function () {
  const prefersReducedMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

  // Parallax scroll: light, vanilla, replaces Lenis smooth scrolling
  function initParallax() {
    if (prefersReducedMotion) return;

    const layers = Array.from(document.querySelectorAll("[data-parallax-depth]")).map(
      (el) => ({
        el,
        depth: parseFloat(el.getAttribute("data-parallax-depth") || "0.2"),
      })
    );

    if (!layers.length) return;

    let ticking = false;

    function onScroll() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(() => {
        const scrollY = window.scrollY || window.pageYOffset || 0;
        layers.forEach(({ el, depth }) => {
          const translate = -(scrollY * depth);
          el.style.transform = `translate3d(0, ${translate}px, 0)`;
        });
        ticking = false;
      });
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  function initReveal() {
    const revealEls = document.querySelectorAll("[data-reveal]");
    if (!revealEls.length) return;

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            io.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.18,
      }
    );

    revealEls.forEach((el) => io.observe(el));
  }

  function initNavScroll() {
    const nav = document.querySelector(".site-nav");
    if (!nav) return;

    let ticking = false;

    function onScroll() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(() => {
        const scrolled = window.scrollY > 8;
        nav.classList.toggle("site-nav-scrolled", scrolled);
        ticking = false;
      });
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  function initMobileNav() {
    const toggle = document.getElementById("nav-toggle");
    const mobile = document.getElementById("nav-mobile");
    if (!toggle || !mobile) return;

    function close() {
      mobile.classList.add("hidden");
    }

    toggle.addEventListener("click", () => {
      mobile.classList.toggle("hidden");
    });

    mobile.addEventListener("click", (e) => {
      if (e.target.tagName === "A") {
        close();
      }
    });
  }

  function initSpotlight() {
    if (prefersReducedMotion) return;

    const spotlightLayer = document.querySelector(".cursor-spotlight-layer");
    if (!spotlightLayer) return;

    const root = document.documentElement;
    let frameRequested = false;
    let latestX = window.innerWidth / 2;
    let latestY = window.innerHeight / 3;

    function setSpotlight(x, y) {
      const vw = window.innerWidth || 1;
      const vh = window.innerHeight || 1;
      const px = (x / vw) * 100;
      const py = (y / vh) * 100;
      root.style.setProperty("--spotlight-x", px + "%");
      root.style.setProperty("--spotlight-y", py + "%");
    }

    function update() {
      frameRequested = false;
      setSpotlight(latestX, latestY);
    }

    function handleMove(e) {
      if (e.type === "touchmove") return;
      latestX = e.clientX;
      latestY = e.clientY;
      if (!frameRequested) {
        frameRequested = true;
        requestAnimationFrame(update);
      }
      document.body.classList.add("cursor-spotlight-active");
    }

    window.addEventListener("pointermove", handleMove, { passive: true });

    window.addEventListener(
      "pointerleave",
      () => {
        document.body.classList.remove("cursor-spotlight-active");
      },
      { passive: true }
    );

    // Initial position
    setSpotlight(latestX, latestY);
  }

  function initFaqAccordion() {
    const toggles = document.querySelectorAll("[data-faq-toggle]");
    if (!toggles.length) return;

    toggles.forEach((btn) => {
      btn.addEventListener("click", () => {
        const panel = btn.closest(".faq-panel");
        if (!panel) return;
        const body = panel.querySelector("[data-faq-body]");
        if (!body) return;

        const isOpen = panel.dataset.open === "true";
        panel.dataset.open = isOpen ? "false" : "true";
        body.classList.toggle("hidden", isOpen);
      });
    });
  }

  function init() {
    initParallax();
    initReveal();
    initNavScroll();
    initMobileNav();
    initSpotlight();
    initFaqAccordion();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

// UI enhancements for landing page: smooth scroll, reveals, cursor glow

// Section reveal animations (legacy helper used by landing.css theme classes)
function initRevealOnScroll() {
    const elements = document.querySelectorAll('.reveal');
    if (!elements.length) return;

    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-visible');
                    observer.unobserve(entry.target);
                }
            });
        },
        {
            threshold: 0.15
        }
    );

    elements.forEach((el) => observer.observe(el));
}

// Cursor spotlight glow
function initCursorSpotlight() {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced || window.matchMedia('(pointer: coarse)').matches) {
        return;
    }

    let spotlight = document.getElementById('cursor-spotlight');
    if (!spotlight) {
        spotlight = document.createElement('div');
        spotlight.id = 'cursor-spotlight';
        spotlight.className = 'cursor-spotlight';
        document.body.appendChild(spotlight);
    }

    let rafId = null;
    let targetX = window.innerWidth / 2;
    let targetY = window.innerHeight / 2;

    function updatePosition() {
        spotlight.style.transform = `translate3d(${targetX}px, ${targetY}px, 0)`;
        rafId = null;
    }

    window.addEventListener(
        'pointermove',
        (event) => {
            targetX = event.clientX;
            targetY = event.clientY;
            if (!rafId) {
                rafId = requestAnimationFrame(updatePosition);
            }
        },
        { passive: true }
    );

    window.addEventListener(
        'pointerenter',
        () => {
            spotlight.classList.add('visible');
        },
        { passive: true }
    );
    window.addEventListener(
        'pointerleave',
        () => {
            spotlight.classList.remove('visible');
        },
        { passive: true }
    );
}

// Glass navbar behavior
function initNavbar() {
    const nav = document.getElementById('main-nav');
    if (!nav) return;

    const toggleScrolled = () => {
        if (window.scrollY > 32) {
            nav.classList.add('nav-scrolled');
        } else {
            nav.classList.remove('nav-scrolled');
        }
    };

    toggleScrolled();
    window.addEventListener('scroll', toggleScrolled, { passive: true });

    // Simple mobile toggle
    const toggleBtn = document.getElementById('nav-toggle');
    const menu = document.getElementById('nav-menu');
    if (toggleBtn && menu) {
        toggleBtn.addEventListener('click', () => {
            const expanded = toggleBtn.getAttribute('aria-expanded') === 'true';
            toggleBtn.setAttribute('aria-expanded', String(!expanded));
            menu.dataset.open = !expanded ? 'true' : 'false';
        });
    }
}

// FAQ accordion (if present)
function initFaq() {
    const toggles = document.querySelectorAll('[data-faq-toggle]');
    if (!toggles.length) return;

    toggles.forEach((btn) => {
        btn.addEventListener('click', () => {
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            const panelId = btn.getAttribute('aria-controls');
            const panel = panelId ? document.getElementById(panelId) : null;
            btn.setAttribute('aria-expanded', String(!expanded));
            if (panel) {
                panel.hidden = expanded;
            }
        });
    });
}

// Initialize UI enhancements after DOM + app.js hooks
function initUI() {
    // Smooth scrolling is now handled natively; we just keep reveals + micro-interactions
    initRevealOnScroll();
    initCursorSpotlight();
    initNavbar();
    initFaq();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUI);
} else {
    initUI();
}

