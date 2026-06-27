// Pure description-builder for settings fields (used via x-html in
// partials/settings/field_types.html). Extracted from settingsPanel so the
// HTML-assembly logic can be unit- and mutation-tested.

/**
 * Build the rich description HTML for a setting from its optional help entry,
 * falling back to the API-provided description.
 * @param {{description?: string, whenToChange?: string, defaultNote?: string, tip?: string}|null} help
 * @param {string} apiDesc  description from the API/options
 * @returns {string} HTML string
 */
export function buildDescription(help, apiDesc) {
  apiDesc = apiDesc || '';
  if (!help) return apiDesc;
  let html = help.description || apiDesc;
  if (help.whenToChange) {
    html += '<br><span class="text-cp-accent">When to change:</span> ' + help.whenToChange;
  }
  if (help.defaultNote) {
    html += '<br><span class="text-cp-muted">💡 ' + help.defaultNote + '</span>';
  }
  if (help.tip) {
    html += '<br><span class="text-cp-warning/80">Tip:</span> ' + help.tip;
  }
  return html;
}
