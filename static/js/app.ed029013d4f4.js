(() => {
    "use strict";

    const html = document.documentElement;

    const STORAGE_KEYS = {
        theme: "carobra_theme",
        sidebarCollapsed: "carobra_sidebar_collapsed",
    };

    const DESKTOP_BREAKPOINT = 1120;

    const qs = (selector, root = document) => root.querySelector(selector);
    const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

    function isDesktop() {
        return window.innerWidth > DESKTOP_BREAKPOINT;
    }

    /* =====================================================
       TEMA
    ====================================================== */

    function getPreferredTheme() {
        const saved = localStorage.getItem(STORAGE_KEYS.theme);

        if (saved === "light" || saved === "dark") {
            return saved;
        }

        return window.matchMedia("(prefers-color-scheme: light)").matches
            ? "light"
            : "dark";
    }

    function applyTheme(theme) {
        html.setAttribute("data-theme", theme);

        const button = qs("#themeToggle") || qs("#loginThemeToggle");

        if (button) {
            button.setAttribute(
                "aria-pressed",
                theme === "light" ? "true" : "false"
            );
        }
    }

    function toggleTheme() {
        const current = html.getAttribute("data-theme") || "dark";
        const next = current === "dark" ? "light" : "dark";

        applyTheme(next);
        localStorage.setItem(STORAGE_KEYS.theme, next);
    }

    /* =====================================================
       SIDEBAR DESKTOP
    ====================================================== */

    function getSavedSidebarState() {
        return localStorage.getItem(STORAGE_KEYS.sidebarCollapsed) === "true";
    }

    function applySidebarState(collapsed, save = false) {
        if (!isDesktop()) {
            html.classList.remove("sidebar-collapsed");
            return;
        }

        html.classList.toggle("sidebar-collapsed", collapsed);

        const button = qs("#sidebarCollapse");
        const navigationButton = qs("#mobileMenuToggle");

        if (button) {
            button.setAttribute("aria-expanded", collapsed ? "false" : "true");
            button.setAttribute(
                "aria-label",
                collapsed ? "Expandir menú" : "Contraer menú"
            );
        }

        if (navigationButton) {
            navigationButton.setAttribute(
                "aria-expanded",
                collapsed ? "false" : "true"
            );
            navigationButton.setAttribute(
                "aria-label",
                collapsed ? "Expandir navegación" : "Contraer navegación"
            );
        }

        if (save) {
            localStorage.setItem(
                STORAGE_KEYS.sidebarCollapsed,
                collapsed ? "true" : "false"
            );
        }
    }

    function toggleSidebarDesktop() {
        if (!isDesktop()) return;

        const collapsed = !html.classList.contains("sidebar-collapsed");

        applySidebarState(collapsed, true);
    }

    /* =====================================================
       SIDEBAR MOBILE
    ====================================================== */

    function openMobileSidebar() {
        if (isDesktop()) return;

        html.classList.add("sidebar-open");

        const button = qs("#mobileMenuToggle");

        if (button) {
            button.setAttribute("aria-expanded", "true");
            button.setAttribute("aria-label", "Cerrar menú");
        }

        document.body.style.overflow = "hidden";
    }

    function closeMobileSidebar() {
        html.classList.remove("sidebar-open");

        const button = qs("#mobileMenuToggle");

        if (button) {
            button.setAttribute("aria-expanded", "false");
            button.setAttribute("aria-label", "Abrir menú");
        }

        document.body.style.overflow = "";
    }

    function toggleMobileSidebar() {
        if (isDesktop()) return;

        if (html.classList.contains("sidebar-open")) {
            closeMobileSidebar();
        } else {
            openMobileSidebar();
        }
    }

    function toggleNavigation() {
        if (isDesktop()) {
            toggleSidebarDesktop();
        } else {
            toggleMobileSidebar();
        }
    }

    /* =====================================================
       TRANSICIONES DE AUTENTICACIÓN
    ====================================================== */

    function initAuthTransitions() {
        const app = qs("#app");
        const authenticated = app?.dataset.authenticated === "true";
        const transition = sessionStorage.getItem("carobra_auth_transition");

        if (authenticated && transition === "enter-app") {
            html.classList.add("app-auth-enter");
            sessionStorage.removeItem("carobra_auth_transition");
        } else if (
            !authenticated &&
            (transition === "enter-login" || transition === "enter-app")
        ) {
            html.classList.add("login-auth-enter");
            sessionStorage.removeItem("carobra_auth_transition");
        }

        const logoutForm = qs(".logout-form");

        logoutForm?.addEventListener("submit", (event) => {
            if (logoutForm.dataset.leaving === "true") return;

            event.preventDefault();
            logoutForm.dataset.leaving = "true";
            sessionStorage.setItem("carobra_auth_transition", "enter-login");
            html.classList.add("app-auth-leave");

            window.setTimeout(() => logoutForm.submit(), 230);
        });
    }

    /* =====================================================
       USER DROPDOWN
    ====================================================== */

    function getUserMenuWrapper() {
        return qs(".user-menu-wrapper");
    }

    function openUserMenu() {
        const wrapper = getUserMenuWrapper();
        const toggle = qs("#userMenuToggle");
        const dropdown = qs("#userDropdown");

        if (!wrapper || !toggle || !dropdown) return;

        wrapper.classList.add("is-open");
        toggle.setAttribute("aria-expanded", "true");
        dropdown.setAttribute("aria-hidden", "false");
    }

    function closeUserMenu() {
        const wrapper = getUserMenuWrapper();
        const toggle = qs("#userMenuToggle");
        const dropdown = qs("#userDropdown");

        if (!wrapper || !toggle || !dropdown) return;

        wrapper.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        dropdown.setAttribute("aria-hidden", "true");
    }

    function toggleUserMenu() {
        const wrapper = getUserMenuWrapper();

        if (!wrapper) return;

        if (wrapper.classList.contains("is-open")) {
            closeUserMenu();
        } else {
            openUserMenu();
        }
    }

    /* =====================================================
       MENSAJES DJANGO
    ====================================================== */

    function dismissMessage(message) {
        if (!message || message.classList.contains("is-leaving")) {
            return;
        }

        message.classList.add("is-leaving");

        window.setTimeout(() => {
            message.remove();
        }, 240);
    }

    function initMessages() {
        const messages = qsa(".app-message");

        messages.forEach((message) => {
            const closeButton = qs(".app-message-close", message);

            if (closeButton) {
                closeButton.addEventListener("click", () => {
                    dismissMessage(message);
                });
            }

            if (message.dataset.autoDismiss === "true") {
                window.setTimeout(() => {
                    dismissMessage(message);
                }, 5200);
            }
        });
    }

    /* =====================================================
       PLACEHOLDERS TEMPORALES
    ====================================================== */

    function showTemporaryToast(message) {
        const container = qs("#toastContainer");

        if (!container) return;

        const toast = document.createElement("div");

        toast.className = "app-message";

        toast.innerHTML = `
            <div class="app-message-icon">i</div>
            <div class="app-message-content">
                <span>${escapeHtml(message)}</span>
            </div>
            <button
                type="button"
                class="app-message-close"
                aria-label="Cerrar mensaje"
            >
                <svg viewBox="0 0 24 24" fill="none">
                    <path
                        d="m7 7 10 10M17 7 7 17"
                        stroke="currentColor"
                        stroke-width="1.8"
                        stroke-linecap="round"
                    />
                </svg>
            </button>
        `;

        container.appendChild(toast);

        const close = qs(".app-message-close", toast);

        if (close) {
            close.addEventListener("click", () => dismissMessage(toast));
        }

        window.setTimeout(() => {
            dismissMessage(toast);
        }, 3200);
    }

    function escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    /* =====================================================
       CIERRE AUTOMÁTICO DEL DRAWER EN MÓVIL
    ====================================================== */

    function bindMobileNavClose() {
        qsa("#appSidebar a.nav-link").forEach((link) => {
            link.addEventListener("click", () => {
                if (!isDesktop()) {
                    closeMobileSidebar();
                }
            });
        });
    }

    /* =====================================================
       ENTRADA ESCALONADA DE CONTENIDO
    ====================================================== */

    function initStaggeredReveal() {
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            return;
        }

        const items = qsa([
            ".dashboard-kpi",
            ".user-stat",
            ".ticket-stat",
            ".dashboard-panel",
            ".user-panel",
            ".tickets-panel",
            ".import-card",
            ".import-results",
            ".profile-card",
        ].join(","));

        items.forEach((item, index) => {
            item.classList.add("system-reveal");
            item.style.setProperty(
                "--reveal-delay",
                `${Math.min(index * 42, 250)}ms`
            );
        });

        window.requestAnimationFrame(() => {
            items.forEach((item) => item.classList.add("is-visible"));
        });
    }

    /* =====================================================
       TECLADO
    ====================================================== */

    function handleKeyboard(event) {
        if (event.key === "Escape") {
            closeUserMenu();

            if (!isDesktop()) {
                closeMobileSidebar();
            }

            return;
        }

        const target = event.target;

        const isTyping =
            target instanceof HTMLInputElement ||
            target instanceof HTMLTextAreaElement ||
            target instanceof HTMLSelectElement ||
            target?.isContentEditable;

        if (isTyping) return;

        if (event.key === "/") {
            const searchButton = qs("#globalSearchButton");

            if (searchButton) {
                event.preventDefault();
                searchButton.click();
            }
        }

        if (event.key.toLowerCase() === "t" && event.altKey) {
            event.preventDefault();
            toggleTheme();
        }
    }

    /* =====================================================
       RESIZE
    ====================================================== */

    let resizeTimer = null;

    function handleResize() {
        window.clearTimeout(resizeTimer);

        resizeTimer = window.setTimeout(() => {
            closeUserMenu();

            if (isDesktop()) {
                closeMobileSidebar();

                applySidebarState(getSavedSidebarState(), false);
            } else {
                html.classList.remove("sidebar-collapsed");
            }
        }, 100);
    }

    /* =====================================================
       BINDINGS
    ====================================================== */

    function bindEvents() {
        const themeToggle = qs("#themeToggle") || qs("#loginThemeToggle");
        const sidebarCollapse = qs("#sidebarCollapse");
        const mobileMenuToggle = qs("#mobileMenuToggle");
        const sidebarBackdrop = qs("#sidebarBackdrop");
        const userMenuToggle = qs("#userMenuToggle");
        const globalSearchButton = qs("#globalSearchButton");
        const notificationsButton = qs("#notificationsButton");
        const preferencesButton = qs("#preferencesButton");

        themeToggle?.addEventListener("click", toggleTheme);

        sidebarCollapse?.addEventListener(
            "click",
            toggleSidebarDesktop
        );

        mobileMenuToggle?.addEventListener("click", toggleNavigation);

        sidebarBackdrop?.addEventListener(
            "click",
            closeMobileSidebar
        );

        userMenuToggle?.addEventListener(
            "click",
            (event) => {
                event.stopPropagation();
                toggleUserMenu();
            }
        );

        globalSearchButton?.addEventListener(
            "click",
            () => {
                showTemporaryToast(
                    "El buscador global se conectará en una siguiente etapa."
                );
            }
        );

        notificationsButton?.addEventListener(
            "click",
            () => {
                showTemporaryToast(
                    "Las notificaciones se conectarán con tickets y SLA."
                );
            }
        );

        preferencesButton?.addEventListener(
            "click",
            () => {
                closeUserMenu();

                showTemporaryToast(
                    "Preferencias estará disponible desde Mi perfil."
                );
            }
        );

        document.addEventListener(
            "click",
            (event) => {
                const wrapper = getUserMenuWrapper();

                if (
                    wrapper &&
                    !wrapper.contains(event.target)
                ) {
                    closeUserMenu();
                }
            }
        );

        document.addEventListener("keydown", handleKeyboard);

        window.addEventListener("resize", handleResize);
    }

    /* =====================================================
       INICIO
    ====================================================== */

    function init() {
        applyTheme(getPreferredTheme());

        if (isDesktop()) {
            applySidebarState(
                getSavedSidebarState(),
                false
            );
        } else {
            html.classList.remove("sidebar-collapsed");
        }

        initMessages();
        initAuthTransitions();
        initStaggeredReveal();
        bindMobileNavClose();
        bindEvents();
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            init,
            { once: true }
        );
    } else {
        init();
    }
})();
