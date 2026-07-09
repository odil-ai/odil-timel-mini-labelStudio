/* global anime */

// -------------------- URL PREFIX --------------------
// `APP_PREFIX` (e.g. "/odil-timel-labelstudio") is injected as a global by
// base.html/login.html from the server-side APP_PREFIX config, so that
// same-origin routes (API calls, redirects) still resolve correctly when
// the app is served behind a reverse-proxy path prefix.
/**
 * Prepend the configured app prefix to a root-relative path.
 *
 * @param {string} path - A root-relative path/URL, e.g. "/api/taxo_search".
 * @returns {string} The path with `APP_PREFIX` prepended (unchanged if the
 *   prefix isn't configured or `path` isn't root-relative).
 */
function withPrefix(path) {
    const prefix = (typeof APP_PREFIX !== "undefined" && APP_PREFIX) ? APP_PREFIX : "";
    if (!prefix || typeof path !== "string" || !path.startsWith("/")) return path;
    return prefix + path;
}

// -------------------- THEME --------------------
(function themeInit() {
    const root = document.documentElement;
    const key = "timel_theme";

    /**
     * Apply the light/dark theme by toggling the `data-theme` attribute on
     * the root `<html>` element.
     *
     * @param {"light"|"dark"} theme - Theme to apply.
     * @returns {void}
     */
    function applyTheme(theme) {
        if (theme === "dark") root.setAttribute("data-theme", "dark");
        else root.removeAttribute("data-theme");
    }

    /**
     * Resolve the theme to use on page load: the value saved in
     * localStorage if present, otherwise the OS/browser preference.
     *
     * @returns {"light"|"dark"} The preferred theme.
     */
    function getPreferredTheme() {
        const saved = localStorage.getItem(key);
        if (saved === "light" || saved === "dark") return saved;
        const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        return prefersDark ? "dark" : "light";
    }

    /**
     * Sync the theme toggle checkbox's checked state with the given theme.
     *
     * @param {"light"|"dark"} theme - Current theme.
     * @returns {void}
     */
    function syncToggle(theme) {
        const cb = document.getElementById("themeToggle");
        if (cb) cb.checked = (theme === "dark");
    }

    document.addEventListener("DOMContentLoaded", () => {
        const initial = getPreferredTheme();
        applyTheme(initial);
        syncToggle(initial);

        const cb = document.getElementById("themeToggle");
        if (!cb) return;

        cb.addEventListener("change", () => {
            const theme = cb.checked ? "dark" : "light";
            applyTheme(theme);
            localStorage.setItem(key, theme);
        });

    });
    document.addEventListener("DOMContentLoaded", () => {
        if (!document.body.classList.contains("login-body")) return;

        if (!window.anime) {
            console.error("anime.js is not loaded");
            return;
        }

        const svg = document.querySelector(".login-logo .logo-svg");
        if (!svg) {
            console.error("SVG logo not found");
            return;
        }

        const lines = svg.querySelectorAll(".line");
        if (!lines.length) {
            console.error("No .line found in the SVG");
            return;
        }

        // (optional) reset in case of a previous run
        lines.forEach((p) => {
            p.removeAttribute("stroke-dasharray");
            p.removeAttribute("stroke-dashoffset");
        });

        anime.remove(lines);

        anime({
            targets: lines,
            strokeDashoffset: [anime.setDashoffset, 0],
            easing: "easeInOutSine",
            duration: 1800,
            delay: anime.stagger(90),
            direction: "alternate",
            loop: true,
        });
    });
})();

// -------------------- SIDEBAR COLLAPSE --------------------
(function sidebarInit() {
    const root = document.documentElement;
    const key = "timel_sidebar_collapsed";

    /**
     * Toggle the collapsed state of the left sidebar by setting/removing
     * the `data-sidebar="collapsed"` attribute on the root `<html>` element.
     *
     * @param {boolean} collapsed - Whether the sidebar should be collapsed.
     * @returns {void}
     */
    function apply(collapsed) {
        if (collapsed) root.setAttribute("data-sidebar", "collapsed");
        else root.removeAttribute("data-sidebar");
    }

    document.addEventListener("DOMContentLoaded", () => {
        const btn = document.getElementById("sidebarToggle");
        if (!btn) return;

        btn.addEventListener("click", () => {
            const collapsed = root.getAttribute("data-sidebar") === "collapsed";
            apply(!collapsed);
            localStorage.setItem(key, !collapsed ? "1" : "0");
        });
    });
})();

// -------------------- UI helpers --------------------

/**
 * Show a transient toast notification.
 *
 * @param {string} msg - Message to display.
 * @param {boolean} [ok=true] - Whether to style the toast as success
 *   (true) or error (false).
 * @returns {void}
 */
function toast(msg, ok = true) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.className = ok ? "toast ok" : "toast err";
    el.textContent = msg;

    if (window.anime) {
        anime.remove(el);
        anime({targets: el, opacity: [0, 1], translateY: [10, 0], duration: 180, easing: "easeOutQuad"});
        anime({targets: el, opacity: [1, 0], delay: 1100, duration: 220, easing: "easeInQuad"});
    } else {
        el.style.opacity = "1";
        setTimeout(() => el.style.opacity = "0", 1100);
    }
}

/**
 * POST a JSON payload to a URL and parse the JSON response.
 *
 * Never throws: network/parse errors are caught and normalized to
 * `{ok: false, error: "network"}`.
 *
 * @param {string} url - Endpoint to POST to.
 * @param {object} data - Payload to JSON-encode as the request body.
 * @returns {Promise<object>} The parsed JSON response, always containing
 *   at least an `ok` boolean.
 */
async function postJSON(url, data) {
    try {
        const r = await fetch(withPrefix(url), {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(data),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) return {ok: false, ...j};
        return j;
    } catch (_e) {
        return {ok: false, error: "network"};
    }
}

/**
 * Open a modal dialog (sets `aria-hidden="false"` and animates it in).
 *
 * @param {HTMLElement} modalEl - The `.modal` root element to open.
 * @returns {void}
 */
function openModal(modalEl) {
    modalEl.setAttribute("aria-hidden", "false");
    if (window.anime) {
        const panel = modalEl.querySelector(".modal-panel");
        anime({targets: panel, scale: [0.98, 1], opacity: [0, 1], duration: 160, easing: "easeOutQuad"});
    }
}

/**
 * Close a modal dialog (sets `aria-hidden="true"`).
 *
 * @param {HTMLElement} modalEl - The `.modal` root element to close.
 * @returns {void}
 */
function closeModal(modalEl) {
    modalEl.setAttribute("aria-hidden", "true");
}

// -------------------- ONE-TIME global wiring --------------------
let APP_WIRED = false;

/**
 * Wire up global, page-agnostic event listeners exactly once per page
 * load (help modal open/close, Escape-to-close). Guarded by `APP_WIRED`
 * so calling it more than once is a no-op.
 *
 * @returns {void}
 */
function wireGlobalOnce() {
    if (APP_WIRED) return;
    APP_WIRED = true;

    // Help modal
    document.addEventListener("click", (e) => {
        if (e.target.closest("#kbdHelpBtn")) {
            const m = document.getElementById("kbdModal");
            if (m) openModal(m);
        }
        const closer = e.target.closest("[data-close-modal]");
        if (closer) {
            const modal = closer.closest(".modal");
            if (modal) closeModal(modal);
        }
    });

    // ESC closes modals + search results
    document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        document.querySelectorAll('.modal[aria-hidden="false"]').forEach(m => closeModal(m));
        const results = document.getElementById("taxoResults");
        if (results) results.innerHTML = "";
    });
}

// -------------------- Correction page logic (JSON navigation) --------------------

/**
 * Check whether the current page is the correction view.
 *
 * @returns {boolean} True if a `[data-page="correction"]` element is present.
 */
function isCorrectionPage() {
    return Boolean(document.querySelector('[data-page="correction"]'));
}

/**
 * Get the current page's URL query parameters (used to read/carry filters
 * such as `pending`, `conf`, `br`, `cursor` across AJAX navigation).
 *
 * @returns {URLSearchParams} The current URL's search params.
 */
function getQueryParamsForCorrection() {
    const url = new URL(window.location.href);
    return url.searchParams;
}

/**
 * Update the `cursor` query parameter in the address bar without
 * triggering a navigation/reload.
 *
 * @param {number} cursor - Cursor position to store in the URL.
 * @returns {void}
 */
function setCursorInUrl(cursor) {
    const url = new URL(window.location.href);
    url.searchParams.set("cursor", String(cursor));
    history.replaceState({}, "", url.toString());
}

/**
 * Resolve the cursor position to load on first page render.
 *
 * The `cursor` URL param is only present after an in-page navigation
 * (prev/next/goto). An external link (e.g. clicking a table row with
 * `?idx=N`) doesn't carry it: in that case we start from the cursor
 * already resolved server-side (`data-cursor` on the page container),
 * not from 0.
 *
 * @returns {number} The initial cursor position.
 */
function getInitialCursor() {
    const fromUrl = getQueryParamsForCorrection().get("cursor");
    if (fromUrl !== null) return parseInt(fromUrl, 10);
    const page = document.querySelector('[data-page="correction"]');
    return parseInt(page?.dataset?.cursor || "0", 10);
}

/**
 * Shorthand for `document.getElementById`.
 *
 * @param {string} id - Element id to look up.
 * @returns {HTMLElement|null} The matching element, or null.
 */
function $(id) {
    return document.getElementById(id);
}

/**
 * Render the image grid for the current row.
 *
 * @param {Array<{rel: string, old_name: string, new_name: ?string, src: string}>} images -
 *   Image descriptors as returned by the `/api/correction/row` endpoint
 *   (`src` is already resolved server-side to either the IIIF endpoint or
 *   the local `/image/<rel>` fallback).
 * @param {string[]} excluded - List of `rel` values currently excluded for
 *   this row.
 * @returns {void}
 */
function renderImages(images, excluded) {
    const grid = document.querySelector(".grid-images");
    if (!grid) return;

    const excludedSet = new Set(excluded || []);
    grid.innerHTML = (images || []).map(img => {
        const rel = img.rel;
        const checked = excludedSet.has(rel) ? "checked" : "";
        const src = img.src; // resolved server-side: IIIF endpoint (new filename) or local /image/<rel> fallback
        const newNameHtml = img.new_name ? `<div class="caption-alt">${img.new_name}</div>` : "";
        return `
      <div class="imgcard" data-rel="${rel}" data-old="${img.old_name}" data-new="${img.new_name || ""}">
        <button class="imgbtn" type="button" title="Ouvrir">
          <img src="${src}" class="thumb" loading="lazy" alt="image">
        </button>
        <div class="caption">
          <div>${img.old_name}</div>
          ${newNameHtml}
        </div>
        <label class="chip">
          <input type="checkbox" class="excl" value="${rel}" ${checked}>
          Exclure
        </label>
      </div>
    `;
    }).join("");
}

/**
 * Update the "N excluded" counter next to the image toolbar based on the
 * currently checked `.excl` checkboxes.
 *
 * @returns {void}
 */
function updateExclCount() {
    const c = document.querySelectorAll(".excl:checked").length;
    const el = $("exclCount");
    if (el) el.textContent = c ? `${c} exclue(s)` : "Aucune exclusion";
}

/**
 * Serialize the currently checked exclusion checkboxes to a JSON array
 * string, as expected by the `excluded_images_json` API field.
 *
 * @returns {string} JSON-encoded array of excluded image `rel` values.
 */
function getExcludedJson() {
    const arr = Array.from(document.querySelectorAll(".excl:checked")).map(x => x.value);
    return JSON.stringify(arr);
}

/**
 * Fetch a single row's data from the JSON API at a given cursor position,
 * carrying over the current filters from the URL.
 *
 * @param {number} cursor - Cursor position to fetch.
 * @returns {Promise<object>} The parsed `/api/correction/row` JSON response.
 */
async function fetchRow(cursor) {
    const params = getQueryParamsForCorrection();
    params.set("cursor", String(cursor));
    const url = withPrefix(`/api/correction/row?${params.toString()}`);
    const r = await fetch(url);
    return await r.json();
}

/**
 * Render the live sidebar progress widgets (overall done/total/percent and
 * the per-branch breakdown).
 *
 * @param {{done: number, total: number}} stats - Overall progress stats.
 * @param {Array<{first_level_timel: string, done: number, total: number, pct: number}>} perBranch -
 *   Per-branch progress records.
 * @returns {void}
 */
function renderSidebar(stats, perBranch) {
    if (!stats) return;

    const doneEl = document.getElementById("sbDone");
    const totalEl = document.getElementById("sbTotal");
    const pctEl = document.getElementById("sbPct");
    const barEl = document.getElementById("sbProgressBar");

    const done = Number(stats.done || 0);
    const total = Number(stats.total || 0);
    const pct = total ? (done / total * 100) : 0;

    if (doneEl) doneEl.textContent = String(done);
    if (totalEl) totalEl.textContent = String(total);
    if (pctEl) pctEl.textContent = `${pct.toFixed(1)}%`;

    if (barEl) {
        barEl.dataset.progress = String(pct);
        if (window.anime) {
            anime.remove(barEl);
            anime({
                targets: barEl,
                width: [`${barEl.style.width || 0}%`, `${pct}%`],
                duration: 450,
                easing: "easeOutCubic"
            });
        } else {
            barEl.style.width = `${pct}%`;
        }
    }

    const wrap = document.getElementById("sbPerBranch");
    if (wrap && Array.isArray(perBranch)) {
        wrap.innerHTML = perBranch.map(r => {
            const raw = r.first_level_timel ?? "";
        const b = (typeof BRANCH_LABELS !== "undefined" && BRANCH_LABELS[raw]) ? BRANCH_LABELS[raw] : raw;
            const d = Number(r.done || 0);
            const t = Number(r.total || 0);
            const p = Number(r.pct || 0);
            return `
        <div style="margin-bottom:12px">
          <div style="display:flex; justify-content:space-between; gap:10px">
            <b>${b}</b>
            <span class="muted">${d}/${t} (${p.toFixed(1)}%)</span>
          </div>
          <div class="progress small" aria-hidden="true">
            <div class="progress-bar" data-progress="${p}" style="width:${p}%"></div>
          </div>
        </div>
      `;
        }).join("");
    }
}

/**
 * Point a TIMEL id link (Suggéré/Final) at its DOI URL, or disable it when
 * there is no real TIMEL id to link to.
 *
 * @param {string} linkId - Id of the `<a>` element to update
 *   (`uiReconciledLink` or `uiFinalLink`).
 * @param {?string} tmId - TIMEL id (`"tm-..."`), `"none"`, or falsy.
 * @returns {void}
 */
function setTmLink(linkId, tmId) {
    const a = $(linkId);
    if (!a) return;
    if (tmId && tmId !== "none") {
        a.href = `https://doi.org/10.34817/${encodeURIComponent(tmId)}`;
        a.classList.remove("tm-link-disabled");
    } else {
        a.href = "#";
        a.classList.add("tm-link-disabled");
    }
}

/**
 * Render the row status badge (Validé / Modifié / À faire).
 *
 * @param {boolean} isValidated - Whether the current row is validated.
 * @param {boolean} hasDecision - Whether the current row has any recorded
 *   decision at all (validated or not).
 * @returns {void}
 */
function renderStatusBadge(isValidated, hasDecision) {
    const host = document.getElementById("uiStatusBadge");
    if (!host) return;

    if (isValidated) {
        host.innerHTML = `<span class="badge badge-ok"><i class="fa-solid fa-circle-check"></i> Validé</span>`;
    } else if (hasDecision) {
        host.innerHTML = `<span class="badge badge-warn"><i class="fa-solid fa-pen-to-square"></i> Modifié</span>`;
    } else {
        host.innerHTML = `<span class="badge badge-todo"><i class="fa-regular fa-circle"></i> À faire</span>`;
    }
}

/**
 * Load a row by cursor position and re-render the whole correction view
 * (labels, images, sidebar stats, status badge) without a full page reload.
 *
 * @param {number} cursor - Cursor position to navigate to.
 * @returns {Promise<void>}
 */
async function loadCursor(cursor) {
    const data = await fetchRow(cursor);
    if (!data.ok) {
        toast("Erreur chargement", false);
        return;
    }
    if (data.empty) {
        // Simple fallback: reload the page (rare case)
        window.location.href = withPrefix("/correction?" + getQueryParamsForCorrection().toString());
        return;
    }

    setCursorInUrl(data.cursor);

    // branch/conf in header
    if (document.getElementById("uiBranch")) {
        const rawBr = data.row.first_level_timel || "";
        document.getElementById("uiBranch").textContent = (typeof BRANCH_LABELS !== "undefined" && BRANCH_LABELS[rawBr]) ? BRANCH_LABELS[rawBr] : rawBr;
    }
    if (document.getElementById("uiConf")) document.getElementById("uiConf").textContent = data.row.confidence || "";

    // status badge
    renderStatusBadge(Boolean(data.is_validated), Boolean(data.has_decision));

    // sidebar stats live
    renderSidebar(data.stats, data.per_branch);

    // top status
    if ($("uiCursor")) $("uiCursor").textContent = String(data.cursor + 1);
    if ($("uiTotal")) $("uiTotal").textContent = String(data.nrows);

    // left labels
    if ($("rowId")) $("rowId").value = data.key;

    if ($("uiOrphanLabel")) $("uiOrphanLabel").textContent = data.row.orphan_label || "";
    if ($("uiReconciledId")) $("uiReconciledId").textContent = data.row.reconciled_timel_id || "";
    if ($("uiReconciledLabel")) $("uiReconciledLabel").textContent = data.row.reconciled_label || "";
    setTmLink("uiReconciledLink", data.row.reconciled_timel_id);

    // final
    if ($("currentFinalId")) $("currentFinalId").textContent = data.current_final_id || "";
    if ($("currentFinalLabel")) $("currentFinalLabel").textContent = data.current_final_label || "";
    setTmLink("uiFinalLink", data.current_final_id);

    // images
    renderImages(data.images_list, data.excluded_list);
    updateExclCount();


    // clear search results
    const results = $("taxoResults");
    if (results) results.innerHTML = "";
    const taxo = $("taxoSearch");
    if (taxo) taxo.value = "";
}

/**
 * Persist the currently checked image exclusions for the active row,
 * without changing its validation status.
 *
 * @returns {Promise<void>}
 */
async function persistExclusions() {
    const rowId = $("rowId")?.value;
    const finalId = $("currentFinalId")?.textContent || "";
    const res = await postJSON("/api/decision/set_exclusions", {
        row_id: rowId,
        final_timel_id: finalId,
        excluded_images_json: getExcludedJson(),
        validated: false,
    });
    if (res.ok) toast("Exclusions sauvegardées ✓", true);
    else toast("Erreur sauvegarde exclusions", false);
    updateExclCount();
}

/**
 * Set the final TIMEL id for the active row from a taxonomy search result
 * (does not mark the row as validated).
 *
 * @param {string} tmId - Chosen TIMEL id (or `"none"`).
 * @returns {Promise<void>}
 */
async function chooseTmId(tmId) {
    const rowId = $("rowId")?.value;
    const res = await postJSON("/api/decision/set_final", {
        row_id: rowId,
        final_timel_id: tmId,
        excluded_images_json: getExcludedJson(),
        validated: false
    });

    if (res.ok) {
        $("currentFinalId").textContent = res.final_timel_id || tmId;
        $("currentFinalLabel").textContent = res.pref_label || "";
        setTmLink("uiFinalLink", res.final_timel_id || tmId);
        toast("Label mis à jour ✓", true);
    } else {
        toast("Erreur label", false);
    }

    $("taxoResults").innerHTML = "";
    $("taxoSearch").value = "";
}

/**
 * Validate the active row's decision and move the cursor by `delta`.
 *
 * @param {string} finalId - Final TIMEL id to record (or `"none"`).
 * @param {number} delta - Cursor offset to apply after validating
 *   (typically `+1`).
 * @returns {Promise<void>}
 */
async function validateAndMove(finalId, delta) {
    const rowId = $("rowId")?.value;
    const res = await postJSON("/api/decision/validate", {
        row_id: rowId,
        final_timel_id: finalId,
        excluded_images_json: getExcludedJson()
    });
    if (!res.ok) {
        toast("Erreur validation", false);
        return;
    }
    toast("Validé ✓", true);

    const cur = parseInt(getQueryParamsForCorrection().get("cursor") || "0", 10);
    await loadCursor(cur + delta);
}

// -------------------- Image modal zoom --------------------
const IMG_ZOOM_MIN = 1;
const IMG_ZOOM_MAX = 4;
const IMG_ZOOM_STEP = 0.25;
let imgZoomScale = 1;
let imgZoomTx = 0;
let imgZoomTy = 0;

/**
 * Apply the current zoom scale/pan state to the modal image and update the
 * zoom UI (wrapper cursor class, percentage label).
 *
 * @returns {void}
 */
function applyImgZoom() {
    const img = $("imgModalImg");
    const wrap = $("imgModalWrap");
    if (!img || !wrap) return;
    img.style.transform = `scale(${imgZoomScale}) translate(${imgZoomTx}px, ${imgZoomTy}px)`;
    wrap.classList.toggle("zoomed", imgZoomScale > IMG_ZOOM_MIN);
    const pctEl = $("imgZoomPct");
    if (pctEl) pctEl.textContent = `${Math.round(imgZoomScale * 100)}%`;
}

/**
 * Reset the modal image zoom/pan to its default (100%, centered) state.
 *
 * @returns {void}
 */
function resetImgZoom() {
    imgZoomScale = 1;
    imgZoomTx = 0;
    imgZoomTy = 0;
    applyImgZoom();
}

/**
 * Set the modal image zoom scale, clamped to
 * `[IMG_ZOOM_MIN, IMG_ZOOM_MAX]`, resetting pan when back at 100%.
 *
 * @param {number} next - Desired zoom scale.
 * @returns {void}
 */
function setImgZoom(next) {
    imgZoomScale = Math.min(IMG_ZOOM_MAX, Math.max(IMG_ZOOM_MIN, next));
    if (imgZoomScale === IMG_ZOOM_MIN) {
        imgZoomTx = 0;
        imgZoomTy = 0;
    }
    applyImgZoom();
}

/**
 * Wire up the image modal's zoom/pan interactions (mouse wheel, drag,
 * double-click reset, +/-/reset buttons). Idempotent: guarded by a
 * `data-zoom-wired` flag so it's safe to call on every `mountCorrection()`.
 *
 * @returns {void}
 */
function wireImgZoom() {
    const wrap = $("imgModalWrap");
    if (!wrap || wrap.dataset.zoomWired) return;
    wrap.dataset.zoomWired = "1";

    wrap.addEventListener("wheel", (e) => {
        e.preventDefault();
        setImgZoom(imgZoomScale + (e.deltaY > 0 ? -IMG_ZOOM_STEP : IMG_ZOOM_STEP));
    }, {passive: false});

    wrap.addEventListener("dblclick", () => resetImgZoom());

    let dragging = false;
    let dragStart = {x: 0, y: 0};
    let startTx = 0, startTy = 0;

    wrap.addEventListener("mousedown", (e) => {
        if (imgZoomScale <= IMG_ZOOM_MIN) return;
        dragging = true;
        wrap.classList.add("dragging");
        dragStart = {x: e.clientX, y: e.clientY};
        startTx = imgZoomTx;
        startTy = imgZoomTy;
        e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        imgZoomTx = startTx + (e.clientX - dragStart.x) / imgZoomScale;
        imgZoomTy = startTy + (e.clientY - dragStart.y) / imgZoomScale;
        applyImgZoom();
    });
    document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        wrap.classList.remove("dragging");
    });

    $("imgZoomInBtn")?.addEventListener("click", () => setImgZoom(imgZoomScale + IMG_ZOOM_STEP));
    $("imgZoomOutBtn")?.addEventListener("click", () => setImgZoom(imgZoomScale - IMG_ZOOM_STEP));
    $("imgZoomResetBtn")?.addEventListener("click", () => resetImgZoom());
}

/**
 * Mount the correction page: run entry animations and wire every
 * interactive behavior (exclusions, prev/next/validate actions, image
 * modal + zoom, goto-index, taxonomy autocomplete, keyboard shortcuts).
 *
 * Called once per full page load, after the initial `loadCursor()` sync;
 * all event listeners are attached via delegation on `document`, so they
 * keep working across the AJAX row navigation driven by `loadCursor()`.
 *
 * @returns {void}
 */
function mountCorrection() {
    // Entry animations only in mainContent (never the sidebar)
    const scope = document.getElementById("mainContent") || document;
    if (window.anime && scope) {
        anime({
            targets: scope.querySelectorAll('[data-anim="hero"]'),
            opacity: [0, 1],
            translateY: [10, 0],
            duration: 260,
            easing: "easeOutQuad"
        });
        anime({
            targets: scope.querySelectorAll('[data-anim="card"]'),
            opacity: [0, 1],
            translateY: [10, 0],
            duration: 260,
            delay: anime.stagger(60),
            easing: "easeOutQuad"
        });
    } else {
        document.querySelectorAll(".progress-bar").forEach(el => el.style.width = `${Number(el.dataset.progress || 0)}%`);
    }

    wireImgZoom();

    // ---- Event delegation: wired once, never accumulates ----
    document.addEventListener("change", async (e) => {
        if (e.target.matches(".excl")) await persistExclusions();
    });

    document.addEventListener("click", async (e) => {
        if (e.target.closest("#exclAllBtn")) {
            document.querySelectorAll(".excl").forEach(cb => cb.checked = true);
            await persistExclusions();
            return;
        }
        if (e.target.closest("#exclNoneBtn")) {
            document.querySelectorAll(".excl").forEach(cb => cb.checked = false);
            await persistExclusions();
            return;
        }

        if (e.target.closest("#prevBtn")) {
            const cur = parseInt(getQueryParamsForCorrection().get("cursor") || "0", 10);
            await loadCursor(cur - 1);
            return;
        }
        if (e.target.closest("#nextBtn")) {
            const cur = parseInt(getQueryParamsForCorrection().get("cursor") || "0", 10);
            await loadCursor(cur + 1);
            return;
        }
        if (e.target.closest("#validateNextBtn")) {
            const finalId = $("currentFinalId")?.textContent || "";
            await validateAndMove(finalId, +1);
            return;
        }
        if (e.target.closest("#noneNextBtn")) {
            await validateAndMove("none", +1);
            return;
        }

        // image modal open
        const imgBtn = e.target.closest(".imgbtn");
        if (imgBtn) {
            const card = imgBtn.closest(".imgcard");
            const rel = card?.dataset?.rel;
            if (!rel) return;
            const oldName = card.dataset.old || rel;
            const newName = card.dataset.new || "";

            const imgModal = $("imgModal");
            const imgModalImg = $("imgModalImg");
            const imgModalPath = $("imgModalPath");
            const imgModalExcl = $("imgModalExcl");

            const thumb = card.querySelector("img.thumb");
            imgModalImg.src = thumb.src;
            imgModalPath.innerHTML = newName
                ? `<div>${oldName}</div><div class="caption-alt">${newName}</div>`
                : oldName;
            imgModalExcl.checked = card.querySelector(".excl")?.checked || false;

            imgModalExcl.onchange = async () => {
                const cb = card.querySelector(".excl");
                cb.checked = imgModalExcl.checked;
                await persistExclusions();
            };

            resetImgZoom();
            openModal(imgModal);
        }
    });

    // goto index (1-based)
    const goto = $("gotoIndex");
    if (goto) {
        goto.addEventListener("keydown", async (e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            const n = parseInt(goto.value || "1", 10);
            const targetCursor = Math.max(0, n - 1);
            await loadCursor(targetCursor);
        });
    }

    // ---- Autocomplete ----
    const taxoInput = $("taxoSearch");
    const results = $("taxoResults");
    let timer = null;
    let activeIndex = -1;
    let lastItems = [];

    /**
     * Render the taxonomy search result list.
     *
     * @param {Array<{id: string, label: string}>} items - Search results,
     *   as returned by `/api/taxo_search`.
     * @returns {void}
     */
    function renderResults(items) {
        lastItems = (items || []).slice(0, 30);
        activeIndex = -1;
        results.innerHTML = lastItems.map((item, idx) =>
            `<div class="result" data-id="${item.id}" data-idx="${idx}">${item.label}</div>`
        ).join("");
    }

    /**
     * Highlight the active (keyboard-navigated) search result item.
     *
     * @param {number} idx - Index of the item to activate, or -1/out of
     *   range to clear the active state.
     * @returns {void}
     */
    function setActive(idx) {
        const els = Array.from(results.querySelectorAll(".result"));
        els.forEach(e => e.classList.remove("active"));
        if (idx < 0 || idx >= els.length) return;
        els[idx].classList.add("active");
        els[idx].scrollIntoView({block: "nearest"});
    }

    taxoInput.oninput = () => {
        clearTimeout(timer);
        const q = taxoInput.value.trim();
        timer = setTimeout(async () => {
            if (!q) {
                results.innerHTML = "";
                return;
            }
            const r = await fetch(`/api/taxo_search?q=${encodeURIComponent(q)}`);
            const data = await r.json().catch(() => []);
            renderResults(data);
        }, 140);
    };

    taxoInput.onkeydown = (e) => {
        const els = results.querySelectorAll(".result");
        if (!els.length) return;

        if (e.key === "ArrowDown") {
            e.preventDefault();
            activeIndex = Math.min(activeIndex + 1, els.length - 1);
            setActive(activeIndex);
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            activeIndex = Math.max(activeIndex - 1, 0);
            setActive(activeIndex);
        } else if (e.key === "Enter") {
            if (activeIndex >= 0 && activeIndex < lastItems.length) {
                e.preventDefault();
                chooseTmId(lastItems[activeIndex].id);
            }
        } else if (e.key === "Escape") {
            results.innerHTML = "";
        }
    };

    results.onclick = (e) => {
        const el = e.target.closest(".result");
        if (!el) return;
        chooseTmId(el.dataset.id);
    };

    // "/" focuses the search box (single handler, no double binding)
    document.addEventListener("keydown", (e) => {
        const tag = document.activeElement?.tagName;
        const inInput = ["INPUT", "TEXTAREA", "SELECT"].includes(tag);
        if (e.key === "/" && !inInput) {
            e.preventDefault();
            taxoInput.focus();
        }
    }, {passive: false});

    // Keyboard shortcuts (single handler)
    document.addEventListener("keydown", async (e) => {
        const tag = document.activeElement?.tagName;
        const inInput = ["INPUT", "TEXTAREA", "SELECT"].includes(tag);

        if (!inInput && e.key === "ArrowRight") {
            e.preventDefault();
            const cur = parseInt(getQueryParamsForCorrection().get("cursor") || "0", 10);
            await loadCursor(cur + 1);
        }
        if (!inInput && e.key === "ArrowLeft") {
            e.preventDefault();
            const cur = parseInt(getQueryParamsForCorrection().get("cursor") || "0", 10);
            await loadCursor(cur - 1);
        }

        if (e.key === "Enter") {
            const hasResults = results.querySelectorAll(".result").length > 0;
            if (document.activeElement === taxoInput && hasResults) return;

            if (!inInput || document.activeElement === taxoInput) {
                e.preventDefault();
                if (e.shiftKey) await validateAndMove("none", +1);
                else {
                    const finalId = $("currentFinalId")?.textContent || "";
                    await validateAndMove(finalId, +1);
                }
            }
        }
    }, {passive: false});
}

// -------------------- Entry --------------------
document.addEventListener("DOMContentLoaded", async () => {
    wireGlobalOnce();

    // On the correction page: force an initial sync via the API (single
    // source of truth, avoids cursor/session drift).
    if (isCorrectionPage()) {
        const cur = getInitialCursor();
        await loadCursor(cur);
        mountCorrection();
    } else {
        // Entry animations, safe only in mainContent
        const scope = document.getElementById("mainContent");
        if (window.anime && scope) {
            anime({
                targets: scope.querySelectorAll('[data-anim="hero"]'),
                opacity: [0, 1],
                translateY: [10, 0],
                duration: 260,
                easing: "easeOutQuad"
            });
            anime({
                targets: scope.querySelectorAll('[data-anim="card"]'),
                opacity: [0, 1],
                translateY: [10, 0],
                duration: 260,
                delay: anime.stagger(60),
                easing: "easeOutQuad"
            });
            anime({
                targets: scope.querySelectorAll('.progress-bar'),
                width: (el) => `${Number(el.dataset.progress || 0)}%`,
                duration: 700,
                easing: "easeOutCubic",
                delay: anime.stagger(60, {start: 120}),
            });
        } else {
            document.querySelectorAll(".progress-bar").forEach(el => el.style.width = `${Number(el.dataset.progress || 0)}%`);
        }
    }
});
