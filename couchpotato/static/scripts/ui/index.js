// Barrel for the extracted UI logic modules. Loaded once in base.html as a
// module script that attaches these helpers to the global `CP.ui` namespace,
// so the inline Alpine components (classic scripts) can delegate to them.
export * from './movie-filter.js';
export * from './settings-values.js';
export * from './settings-help.js';
export * from './profile-editor.js';
export * from './category-editor.js';
