document.addEventListener("DOMContentLoaded", () => {
    const page = document.querySelector(".ticket-detail-page");
    if (!page) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const panels = [...page.querySelectorAll(".ticket-panel")];
    if (!reducedMotion && "IntersectionObserver" in window) {
        page.classList.add("is-motion-ready");
        const reveal = new IntersectionObserver((entries, observer) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                entry.target.classList.add("is-revealed");
                observer.unobserve(entry.target);
            });
        }, { rootMargin: "0px 0px -7%", threshold: .06 });
        panels.forEach((panel) => reveal.observe(panel));
    } else {
        panels.forEach((panel) => panel.classList.add("is-revealed"));
    }

    const navLinks = [...page.querySelectorAll(".ticket-section-nav a")];
    const sections = navLinks.map((link) => document.querySelector(link.hash)).filter(Boolean);
    if ("IntersectionObserver" in window) {
        const spy = new IntersectionObserver((entries) => {
            const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
            if (!visible) return;
            navLinks.forEach((link) => link.classList.toggle("is-active", link.hash === `#${visible.target.id}`));
        }, { rootMargin: "-18% 0px -68%", threshold: [0, .25, .6] });
        sections.forEach((section) => spy.observe(section));
    }

    page.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", () => {
            if (!form.checkValidity()) return;
            const button = form.querySelector("button[type='submit'], button:not([type])");
            if (button) {
                button.classList.add("is-loading");
                button.setAttribute("aria-busy", "true");
            }
        });
    });
});
