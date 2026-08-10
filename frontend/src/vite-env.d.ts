/// <reference types="vite/client" />

// Brings in Vite's declaration of `import.meta.env`, which is an extension to
// the standard `ImportMeta` type rather than part of it. Without this
// reference, every `import.meta.env.VITE_*` read is a TS2339 error even though
// Vite substitutes the value at build time and the app runs correctly.
