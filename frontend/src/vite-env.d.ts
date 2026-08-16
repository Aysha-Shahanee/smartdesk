/// <reference types="vite/client" />

// Brings in Vite's declaration of `import.meta.env`, which is an extension to
// the standard `ImportMeta` type rather than part of it. Without this
// reference, every `import.meta.env.VITE_*` read is a TS2339 error even though
// Vite substitutes the value at build time and the app runs correctly.
//
// `window.electronAPI` is declared in renderer/electron.d.ts, which is the one
// place that mirrors the preload bridge. Do not redeclare it here: a second
// `interface Window` shadows that declaration and every method missing from
// the copy becomes a TS2339 error at its call sites.
