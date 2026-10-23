/// <reference types="svelte" />
/// <reference types="vite/client" />
interface ImportMetaEnv { readonly VITE_FAKE?: string }
declare module '*.jsonl?raw' { const text: string; export default text; }
