// app/frontend/js/chartRenderer.js
// Skill 2.7 — Interactive Plotly Chart Renderer for Ignite Chat UI

"use strict";

(function () {
    /**
     * Render an interactive Plotly chart HTML widget inside a target container element.
     * @param {string|HTMLElement} container - Target container ID or element.
     * @param {string} htmlWidget - Self-contained Plotly HTML document string.
     */
    function renderPlotlyChart(container, htmlWidget) {
        const targetEl = typeof container === "string" ? document.getElementById(container) : container;
        if (!targetEl) {
            console.error("[ChartRenderer] Target container element not found:", container);
            return;
        }

        const iframe = document.createElement("iframe");
        iframe.className = "plotly-chart-iframe";
        iframe.style.width = "100%";
        iframe.style.height = "320px";
        iframe.style.border = "none";
        iframe.style.borderRadius = "8px";
        iframe.style.backgroundColor = "transparent";

        targetEl.appendChild(iframe);

        const doc = iframe.contentWindow.document;
        doc.open();
        doc.write(htmlWidget);
        doc.close();
    }

    // Attach to global window scope
    window.renderPlotlyChart = renderPlotlyChart;
    console.debug("[ChartRenderer] Skill 2.7 Plotly Chart Renderer initialized.");
})();
